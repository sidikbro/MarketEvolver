import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation, ValidationError
from market_evolver.evolve.engine import (
    construct_challenger,
    evaluate_challenger,
    promotion_event,
    rollback_event,
)
from market_evolver.evolve.policy import DEFAULT_EVOLUTION_POLICY
from market_evolver.evolve.repository import SqlEvolutionRepository
from market_evolver.evolve.schemas import (
    ApprovalState,
    BenchmarkManifest,
    ChampionRegistryEvent,
    ExpertVersion,
    ImprovementProposal,
    ProposalStatus,
    ProposalType,
    RegistryAction,
    VersionMetrics,
)
from market_evolver.experiment.schemas import CostBreakdown
from market_evolver.integration import (
    PIPELINE_STAGES,
    IntegrationCheckpoint,
    IntegrationManifest,
    visible_checkpoints,
)
from market_evolver.paper.accounting import apply_fill
from market_evolver.paper.nav_store import NavHistoryStore
from market_evolver.paper.policy import NIS_2000_POLICY
from market_evolver.paper.risk import evaluate_order
from market_evolver.paper.schemas import (
    AuditRecord,
    ExecutionDecision,
    KillState,
    PaperAccountSnapshot,
    PaperFill,
    PaperOrderCandidate,
    PaperSide,
    RiskAction,
    SignalIntent,
)
from market_evolver.schemas import Event, Evidence, Source, SourceKind, TrustLevel
from market_evolver.storage.artifacts import LocalArtifactStore
from market_evolver.storage.models import Base
from market_evolver.storage.repositories import (
    SqlEventRepository,
    SqlEvidenceRepository,
    SqlSourceRepository,
)
from market_evolver.topology.repository import SqlTopologyRepository
from market_evolver.topology.schemas import (
    TopologyAction,
    TopologyNode,
    TopologyRegistryEvent,
    TopologyState,
    TopologyVersion,
)

pytestmark = pytest.mark.integration
T0 = datetime(2025, 1, 1, tzinfo=UTC)


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _account(drawdown="0"):
    return PaperAccountSnapshot(
        "paper:integration",
        T0,
        "2000",
        "0",
        "2000",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        (),
        (),
        drawdown,
        "2000",
        (),
        "2000",
        KillState.NORMAL,
    )


def test_complete_research_to_paper_pipeline_and_storage(tmp_path: Path) -> None:
    artifact_store = LocalArtifactStore(tmp_path / "artifacts")
    artifact = artifact_store.put(b'{"official":true}', mime_type="application/json")
    assert artifact_store.read(artifact) == b'{"official":true}'
    checkpoints = []
    previous = f"artifact:{artifact.sha256}"
    for index, stage in enumerate(PIPELINE_STAGES):
        item = IntegrationCheckpoint(
            stage, T0 + timedelta(minutes=index), (previous,), _hash(f"{stage}:{index}")
        )
        checkpoints.append(item)
        previous = item.checkpoint_id
    manifest = IntegrationManifest(T0 + timedelta(hours=1), tuple(checkpoints))
    assert manifest.checkpoints[-1].provenance_ids == (manifest.checkpoints[-2].checkpoint_id,)

    signal = SignalIntent(
        "paper:integration",
        "asset.xtae.nice",
        PaperSide.BUY,
        T0 + timedelta(minutes=12),
        "2025-01-02",
        "next_open",
        "experiment:validated",
        None,
        None,
        "300",
        (checkpoints[1].checkpoint_id, checkpoints[6].checkpoint_id),
        2,
        T0 + timedelta(minutes=7),
        (checkpoints[10].checkpoint_id,),
    )
    order = PaperOrderCandidate(
        signal.signal_id,
        signal.portfolio_id,
        signal.asset_id,
        signal.side,
        "3",
        "300",
        "experiment:validated",
        signal.generated_at,
        signal.intended_session,
        signal.execution_rule,
        signal.provenance,
    )
    evaluation = evaluate_order(
        signal,
        order,
        _account(),
        NIS_2000_POLICY,
        evaluated_at=T0 + timedelta(minutes=13),
        market_observed_at=T0 + timedelta(minutes=13),
        asset_class="equity",
        exchange="XTAE",
        sector="technology",
        currency="ILS",
        costs=CostBreakdown("1", "1", "0", "0", "0"),
        strategy_valid=True,
        evidence_valid=True,
    )
    assert evaluation.action is RiskAction.APPROVED
    decision = ExecutionDecision(
        order.candidate_id,
        evaluation.evaluation_id,
        T0 + timedelta(minutes=14),
        True,
        "risk-approved",
        "market:bar:1",
    )
    fill = PaperFill(
        decision.decision_id,
        signal.portfolio_id,
        signal.asset_id,
        signal.side,
        T0 + timedelta(minutes=14),
        "3",
        "100",
        "2",
        "0",
        "1698",
        "3",
        "market:bar:1",
    )
    snapshot = apply_fill(
        _account(), fill, T0 + timedelta(minutes=15), {signal.asset_id: Decimal(100)}
    )
    assert Decimal(snapshot.cash) + Decimal(snapshot.market_value) == Decimal(snapshot.nav)

    nav = NavHistoryStore(tmp_path / "derived")
    parquet = nav.export(signal.portfolio_id, (_account(), snapshot))
    expected_hash = nav.sha256(parquet)
    nav.verify(parquet, expected_hash)
    assert (
        nav.rows(parquet) == 2 and expected_hash == hashlib.sha256(parquet.read_bytes()).hexdigest()
    )
    payload = bytearray(parquet.read_bytes())
    payload[-1] ^= 1
    parquet.write_bytes(payload)
    with pytest.raises(IntegrityViolation):
        nav.verify(parquet, expected_hash)


def test_nis_2000_accounting_governance_lifecycle() -> None:
    signal = SignalIntent(
        "paper:integration",
        "asset.xtae.nice",
        PaperSide.BUY,
        T0,
        "2025-01-02",
        "next_open",
        "experiment:validated",
        None,
        None,
        "300",
        ("evidence:official", "evidence:filing"),
        2,
        T0,
        ("hypothesis:reviewed",),
    )
    order = PaperOrderCandidate(
        signal.signal_id,
        signal.portfolio_id,
        signal.asset_id,
        signal.side,
        "3",
        "300",
        signal.strategy_id,
        T0,
        signal.intended_session,
        signal.execution_rule,
        signal.provenance,
    )

    def assess(account: PaperAccountSnapshot, observed_at: datetime):
        return evaluate_order(
            signal,
            order,
            account,
            NIS_2000_POLICY,
            evaluated_at=T0 + timedelta(minutes=1),
            market_observed_at=observed_at,
            asset_class="equity",
            exchange="XTAE",
            sector="technology",
            currency="ILS",
            costs=CostBreakdown("0", "0", "0", "0", "0"),
            strategy_valid=True,
            evidence_valid=True,
        )

    assert assess(_account(), T0 + timedelta(minutes=1)).action is RiskAction.APPROVED
    assert assess(_account(), T0 - timedelta(days=1)).action is RiskAction.REJECTED
    concentrated = replace(_account(), sector_exposure=(("technology", "0.34"),))
    assert assess(concentrated, T0 + timedelta(minutes=1)).action is RiskAction.RESIZED
    halted = assess(replace(_account(), drawdown="0.13"), T0 + timedelta(minutes=1))
    assert halted.action is RiskAction.PORTFOLIO_HALTED
    assert halted.resulting_kill_state is KillState.HALTED
    recovery = AuditRecord(
        "paper:integration",
        T0 + timedelta(minutes=2),
        "operator_recovery",
        "operator:integration",
        (("reason", "accounting reconciled"),),
        KillState.HALTED,
        KillState.NORMAL,
    )
    recovered = replace(
        _account(), timestamp=recovery.timestamp, kill_state=recovery.resulting_state
    )
    assert recovery.actor.startswith("operator:") and recovered.kill_state is KillState.NORMAL


def test_cross_lab_cutoff_replay_with_revision() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        sources = SqlSourceRepository(session)
        evidence = SqlEvidenceRepository(session)
        events = SqlEventRepository(session)
        stages = (
            ("rumor", SourceKind.NEWS, TrustLevel.UNTRUSTED, T0),
            ("news-corroboration", SourceKind.NEWS, TrustLevel.CORROBORATED, T0 + timedelta(1)),
            (
                "official-confirmation",
                SourceKind.GOVERNMENT,
                TrustLevel.AUTHORITATIVE,
                T0 + timedelta(2),
            ),
            ("company-context", SourceKind.RESEARCH, TrustLevel.AUTHORITATIVE, T0 + timedelta(3)),
            ("macro-context", SourceKind.TRENDS, TrustLevel.AUTHORITATIVE, T0 + timedelta(4)),
            (
                "geopolitical-context",
                SourceKind.GEOPOLITICAL,
                TrustLevel.CORROBORATED,
                T0 + timedelta(5),
            ),
            (
                "official-correction",
                SourceKind.GOVERNMENT,
                TrustLevel.AUTHORITATIVE,
                T0 + timedelta(6),
            ),
        )
        created = []
        for name, kind, trust, observed in stages:
            source = Source(
                f"https://official.invalid/{name}",
                kind,
                name,
                observed,
                observed,
                observed,
                trust=trust,
                content_digest=_hash(name),
                mime_type="application/json",
            )
            sources.add(source)
            item = Evidence(
                f"{name} claim", (source.provenance_id,), observed, _hash(name + "-excerpt")
            )
            evidence.add(item)
            created.append(item)
        event = Event("Official market event", T0, T0 + timedelta(2), (created[2].provenance_id,))
        events.add(event)
        session.commit()
        assert len(evidence.visible_at(T0)) == 1
        assert len(evidence.visible_at(T0 + timedelta(5))) == 6
        assert created[-1] not in evidence.visible_at(T0 + timedelta(5))
        assert events.get(event.provenance_id) == event
    engine.dispose()


def test_manifest_corruption_timestamp_and_provenance_fail_closed(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    artifact = store.put(b"trusted", mime_type="text/plain")
    (tmp_path / artifact.relative_path).write_bytes(b"corrupt")
    with pytest.raises(IntegrityViolation):
        store.read(artifact)
    with pytest.raises(ValidationError):
        IntegrationCheckpoint("evidence", T0, (), _hash("missing"))
    with pytest.raises(ValidationError):
        IntegrationCheckpoint(
            "evidence",
            datetime(2025, 1, 1),  # noqa: DTZ001 - deliberately malformed test input
            ("source",),
            _hash("naive"),
        )
    records = tuple(
        IntegrationCheckpoint(
            stage,
            T0 + timedelta(minutes=index),
            (("root",) if index == 0 else ("wrong-parent",)),
            _hash(stage),
        )
        for index, stage in enumerate(PIPELINE_STAGES)
    )
    with pytest.raises(IntegrityViolation):
        IntegrationManifest(T0 + timedelta(hours=1), records)


def test_cross_lab_visible_checkpoint_helper_never_leaks_future() -> None:
    records = tuple(
        IntegrationCheckpoint(stage, T0 + timedelta(minutes=index), ("p",), _hash(stage))
        for index, stage in enumerate(PIPELINE_STAGES)
    )
    visible = visible_checkpoints(records, T0 + timedelta(minutes=5))
    assert len(visible) == 6
    assert all(item.observed_at <= T0 + timedelta(minutes=5) for item in visible)


def test_governed_self_improvement_promotion_and_rollback_integration() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repo = SqlEvolutionRepository(session)
        champion = ExpertVersion(
            "expert.integration",
            None,
            None,
            "prompt/1",
            (("max_items", "10"),),
            ("get_events",),
            ("check evidence",),
            ("official",),
            "mock/1",
            T0,
            "governance:seed",
            ApprovalState.CHAMPION,
            None,
            (),
            ("seed",),
        )
        repo.add_version(champion)
        repo.add_registry_event(
            ChampionRegistryEvent(
                champion.expert_id,
                champion.expert_version_id,
                None,
                RegistryAction.INITIAL_CHAMPION,
                "governance:seed",
                "initial",
                T0,
                (),
                None,
            )
        )
        proposal = ImprovementProposal(
            champion.expert_id,
            champion.expert_version_id,
            ProposalType.REASONING_CHECKLIST,
            (("reasoning_template", "check evidence|check gaps"),),
            "Reviewer found mechanism gaps.",
            ("case:1",),
            "operator",
            ("trace:1",),
            T0 + timedelta(1),
            ProposalStatus.PROPOSED,
            ("trace:1",),
        )
        repo.add_proposal(proposal)
        session.flush()
        challenger = construct_challenger(champion, proposal, T0 + timedelta(2), "operator")
        repo.add_version(challenger)
        manifest = BenchmarkManifest(
            "integration/1",
            ("dev",),
            ("validation",),
            ("protected",),
            ("holdout",),
            ("context",),
            "mock",
            "mock/1",
            "sha256:" + "a" * 64,
            T0,
        )
        repo.add_manifest(manifest)
        session.flush()
        baseline = VersionMetrics(0.9, 0.7, 0.8, 10, 0.6, 0, 0, 0, 0)
        improved = VersionMetrics(0.92, 0.8, 0.82, 10, 0.8, 0, 0, 0, 0)
        evaluation = evaluate_challenger(
            champion,
            challenger,
            manifest.manifest_id,
            baseline,
            improved,
            (0.1,) * 5,
            T0 + timedelta(3),
            DEFAULT_EVOLUTION_POLICY,
        )
        repo.add_evaluation(evaluation)
        session.flush()
        promoted = promotion_event(
            challenger, champion, evaluation, "governance:operator", "passed", T0 + timedelta(4)
        )
        repo.add_registry_event(promoted)
        repo.add_registry_event(
            rollback_event(
                champion.expert_id,
                champion.expert_version_id,
                challenger.expert_version_id,
                "governance:operator",
                "later degradation",
                T0 + timedelta(5),
                ("session:challenger",),
            )
        )
        session.flush()
        assert repo.current_champion_id(champion.expert_id) == champion.expert_version_id
        assert len(repo.history(champion.expert_id)) == 3
    engine.dispose()


def test_topology_and_historical_expert_replay_integration() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repo = SqlTopologyRepository(session)
        old = TopologyVersion(
            None,
            None,
            (TopologyNode("expert.general", "expert:v1", "general", T0),),
            (),
            (),
            "router:v1",
            T0,
            "governance:seed",
            TopologyState.ACTIVE,
            None,
            "passed",
            ("seed",),
        )
        new = TopologyVersion(
            old.topology_version_id,
            "proposal:new",
            (TopologyNode("expert.general", "expert:v2", "general", T0 + timedelta(2)),),
            (),
            (),
            "router:v2",
            T0 + timedelta(2),
            "operator",
            TopologyState.CHALLENGER,
            None,
            "passed",
            (old.topology_version_id, "proposal:new"),
        )
        repo.add_version(old)
        # Persist a minimal immutable proposal row through the ORM for the challenger FK contract.
        from market_evolver.storage.models import TopologyProposalModel

        session.add(
            TopologyProposalModel(
                proposal_id="proposal:new",
                proposal_type="change_routing",
                status="approved",
                created_at=T0 + timedelta(1),
                payload={"provenance": ["audit"]},
            )
        )
        session.flush()
        repo.add_version(new)
        repo.add_registry_event(
            TopologyRegistryEvent(
                old.topology_version_id,
                None,
                TopologyAction.INITIAL_ACTIVATION,
                "governance:seed",
                "initial",
                T0,
            )
        )
        repo.add_registry_event(
            TopologyRegistryEvent(
                new.topology_version_id,
                old.topology_version_id,
                TopologyAction.ACTIVATION,
                "governance:operator",
                "approved",
                T0 + timedelta(3),
            )
        )
        session.flush()
        historical = repo.active_at(T0 + timedelta(1))
        current = repo.active_at(T0 + timedelta(4))
        assert historical is not None and historical.router_version == "router:v1"
        assert historical.nodes[0].expert_version_id == "expert:v1"
        assert current is not None and current.router_version == "router:v2"
        assert current.nodes[0].expert_version_id == "expert:v2"
    engine.dispose()
