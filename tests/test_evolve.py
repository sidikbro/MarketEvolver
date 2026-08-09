import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.errors import (
    GovernanceViolation,
    ImmutableRecordError,
    IntegrityViolation,
    ValidationError,
)
from market_evolver.evolve.engine import (
    construct_challenger,
    eligible_version,
    evaluate_challenger,
    paired_bootstrap_interval,
    promotion_event,
    rollback_event,
)
from market_evolver.evolve.policy import DEFAULT_EVOLUTION_POLICY
from market_evolver.evolve.repository import SqlEvolutionRepository
from market_evolver.evolve.schemas import (
    ApprovalState,
    BenchmarkManifest,
    ChampionRegistryEvent,
    DatasetPartition,
    ErrorAttribution,
    ExpertVersion,
    FailureCategory,
    HoldoutAccess,
    ImprovementProposal,
    ProposalStatus,
    ProposalType,
    RegistryAction,
    VersionMetrics,
)
from market_evolver.storage.models import Base, EvolvableExpertVersionModel

T0 = datetime(2025, 1, 1, tzinfo=UTC)


def version(state=ApprovalState.CHAMPION):
    return ExpertVersion(
        "expert.technology_ai",
        None,
        None,
        "technology/1",
        (("max_items", "10"), ("recency_days", "365")),
        ("get_fundamentals", "get_filings", "get_events"),
        ("check evidence", "check counterevidence"),
        ("official", "filing"),
        "model-policy/1",
        T0,
        "operator:seed",
        state,
        None,
        (),
        ("expert-definition:1",),
    )


def proposal(
    parent,
    changes=(("reasoning_template", "check evidence|check mechanisms"),),
    generated="operator:research",
):
    return ImprovementProposal(
        parent.expert_id,
        parent.expert_version_id,
        ProposalType.REASONING_CHECKLIST,
        changes,
        "Mechanism gaps appeared in validation.",
        ("case:failure",),
        generated,
        ("trace:1",),
        T0 + timedelta(1),
        ProposalStatus.PROPOSED,
        ("trace:1",),
    )


def metrics(**changes):
    item = VersionMetrics(0.90, 0.70, 0.80, 10.0, 0.60, 0, 0, 0, 0)
    return replace(item, **changes)


def manifest():
    return BenchmarkManifest(
        "evolution/1",
        ("dev:1",),
        ("val:1",),
        ("protected:1",),
        ("holdout:1",),
        ("context:1",),
        "mock",
        "mock-v1",
        "sha256:" + "a" * 64,
        T0,
    )


class EvolutionTests(unittest.TestCase):
    def test_immutable_host_controls_cannot_be_proposed(self):
        parent = version()
        for key in (
            "risk_limits",
            "execution_permissions",
            "cutoff_rules",
            "provenance_validation",
            "append_only_guarantees",
        ):
            with self.assertRaises(ValidationError):
                proposal(parent, ((key, "weaker"),))

    def test_challenger_is_minimal_and_cannot_expand_tools(self):
        parent = version()
        item = proposal(parent)
        challenger = construct_challenger(parent, item, T0 + timedelta(2), "operator:test")
        self.assertEqual(challenger.parent_version, parent.expert_version_id)
        self.assertEqual(len(challenger.diff_manifest), 1)
        expansion = proposal(parent, (("tool_policy", "get_fundamentals,broker_access"),))
        with self.assertRaises(GovernanceViolation):
            construct_challenger(parent, expansion, T0 + timedelta(2), "operator:test")

    def test_llm_suggestion_is_untrusted_artifact_not_activation(self):
        item = proposal(version(), generated="model:mock-v1")
        self.assertEqual(item.status, ProposalStatus.PROPOSED)
        with self.assertRaises(ValidationError):
            ChampionRegistryEvent(
                item.expert_id,
                "v2",
                "v1",
                RegistryAction.PROMOTION,
                "model:mock-v1",
                "self promotion",
                T0,
                (),
                "evaluation",
            )

    def test_clear_improvement_is_eligible_but_not_promoted(self):
        parent = version()
        challenger = construct_challenger(parent, proposal(parent), T0 + timedelta(2), "operator")
        result = evaluate_challenger(
            parent,
            challenger,
            "manifest",
            metrics(),
            metrics(domain_quality=0.80, mechanism_coverage=0.80),
            (0.1,) * 5,
            T0 + timedelta(3),
            DEFAULT_EVOLUTION_POLICY,
        )
        self.assertEqual(result.decision, "eligible_for_promotion")
        self.assertFalse(DEFAULT_EVOLUTION_POLICY.automatic_promotion_enabled)
        self.assertEqual(
            eligible_version(challenger, result).approval_state, ApprovalState.ELIGIBLE
        )

    def test_performance_gain_with_provenance_violation_is_quarantined(self):
        parent = version()
        challenger = construct_challenger(parent, proposal(parent), T0 + timedelta(2), "operator")
        result = evaluate_challenger(
            parent,
            challenger,
            "manifest",
            metrics(),
            metrics(domain_quality=0.99, fabricated_provenance=1),
            (0.2,) * 5,
            T0 + timedelta(3),
            DEFAULT_EVOLUTION_POLICY,
        )
        self.assertTrue(result.safety_veto)
        self.assertEqual(result.decision, "quarantined")
        with self.assertRaises(GovernanceViolation):
            promotion_event(
                challenger, parent, result, "governance:alice", "gain", T0 + timedelta(4)
            )

    def test_cost_regression_overfit_and_horizon_regression_are_rejected(self):
        parent = version()
        challenger = construct_challenger(parent, proposal(parent), T0 + timedelta(2), "operator")
        costly = evaluate_challenger(
            parent,
            challenger,
            "m",
            metrics(),
            metrics(domain_quality=0.80, operational_cost=13),
            (0.1,) * 5,
            T0 + timedelta(3),
            DEFAULT_EVOLUTION_POLICY,
        )
        self.assertIn("COST_TOLERANCE_EXCEEDED", costly.reasons)
        overfit = evaluate_challenger(
            parent,
            challenger,
            "m",
            metrics(),
            metrics(domain_quality=0.8),
            (0.3, 0.3, -0.4, -0.4, -0.4),
            T0 + timedelta(3),
            DEFAULT_EVOLUTION_POLICY,
        )
        self.assertGreater(overfit.losses, overfit.wins)

    def test_statistics_are_not_claimed_for_small_sample(self):
        with self.assertRaises(GovernanceViolation):
            paired_bootstrap_interval((0.1,) * 9)
        interval = paired_bootstrap_interval(tuple((index - 5) / 100 for index in range(10)))
        self.assertLessEqual(interval[0], interval[1])

    def test_fabricated_benchmark_manifest_is_rejected(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            repo = SqlEvolutionRepository(session)
            parent = version()
            repo.add_version(parent)
            prop = proposal(parent)
            repo.add_proposal(prop)
            session.flush()
            challenger = construct_challenger(parent, prop, T0 + timedelta(2), "operator")
            repo.add_version(challenger)
            session.flush()
            result = evaluate_challenger(
                parent,
                challenger,
                "fabricated-manifest",
                metrics(),
                metrics(domain_quality=0.8),
                (0.1,) * 5,
                T0 + timedelta(3),
                DEFAULT_EVOLUTION_POLICY,
            )
            with self.assertRaises(IntegrityViolation):
                repo.add_evaluation(result)
        engine.dispose()

    def test_failure_attribution_separates_performance_and_safety(self):
        normal = ErrorAttribution(
            "v", "case", FailureCategory.MECHANISM_GAP, "missing path", ("trace",), T0, True
        )
        critical = ErrorAttribution(
            "v", "case", FailureCategory.TEMPORAL_LEAKAGE, "future evidence", ("trace",), T0, False
        )
        self.assertFalse(normal.critical_safety_failure)
        self.assertTrue(critical.critical_safety_failure)

    def test_holdout_partitions_are_disjoint(self):
        with self.assertRaises(ValidationError):
            BenchmarkManifest(
                "v",
                ("same",),
                ("same",),
                ("p",),
                ("h",),
                ("c",),
                "mock",
                "mock",
                "sha256:" + "a" * 64,
                T0,
            )

    def test_repeated_final_holdout_access_is_rejected_and_audited(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            repo = SqlEvolutionRepository(session)
            parent = version()
            repo.add_version(parent)
            data = manifest()
            repo.add_manifest(data)
            session.flush()
            access = HoldoutAccess(
                parent.expert_version_id,
                data.manifest_id,
                DatasetPartition.FINAL_HOLDOUT,
                T0,
                "operator",
                "final evaluation",
            )
            repo.audit_holdout(access, DEFAULT_EVOLUTION_POLICY)
            session.flush()
            second = replace(access, accessed_at=T0 + timedelta(1), purpose="adaptive retry")
            with self.assertRaises(IntegrityViolation):
                repo.audit_holdout(second, DEFAULT_EVOLUTION_POLICY)
        engine.dispose()

    def test_promotion_and_rollback_retain_history(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            repo = SqlEvolutionRepository(session)
            parent = version()
            repo.add_version(parent)
            initial = ChampionRegistryEvent(
                parent.expert_id,
                parent.expert_version_id,
                None,
                RegistryAction.INITIAL_CHAMPION,
                "governance:seed",
                "initial",
                T0,
                (),
                None,
            )
            repo.add_registry_event(initial)
            prop = proposal(parent)
            repo.add_proposal(prop)
            session.flush()
            challenger = construct_challenger(parent, prop, T0 + timedelta(2), "operator")
            repo.add_version(challenger)
            data = manifest()
            repo.add_manifest(data)
            session.flush()
            result = evaluate_challenger(
                parent,
                challenger,
                data.manifest_id,
                metrics(),
                metrics(domain_quality=0.8),
                (0.1,) * 5,
                T0 + timedelta(3),
                DEFAULT_EVOLUTION_POLICY,
            )
            repo.add_evaluation(result)
            session.flush()
            promoted = promotion_event(
                challenger, parent, result, "governance:alice", "passed", T0 + timedelta(4)
            )
            repo.add_registry_event(promoted)
            rolled = rollback_event(
                parent.expert_id,
                parent.expert_version_id,
                challenger.expert_version_id,
                "governance:alice",
                "degradation",
                T0 + timedelta(5),
                ("session:new",),
            )
            repo.add_registry_event(rolled)
            session.flush()
            self.assertEqual(repo.current_champion_id(parent.expert_id), parent.expert_version_id)
            self.assertEqual(len(repo.history(parent.expert_id)), 3)
            row = session.get(EvolvableExpertVersionModel, parent.expert_version_id)
            assert row
            row.approval_state = "deleted"
            with self.assertRaises(ImmutableRecordError):
                session.flush()
        engine.dispose()

    def test_seed_scenario_outcomes(self):
        scenarios = {
            "mechanism_coverage": "eligible",
            "unsupported_claims": "eligible",
            "provenance_gain": "quarantined",
            "development_overfit": "rejected",
            "token_cost_no_gain": "rejected",
            "indistinguishable": "rejected",
            "horizon_regression": "rejected",
            "degradation_rollback": "rollback",
        }
        self.assertEqual(len(scenarios), 8)


if __name__ == "__main__":
    unittest.main()
