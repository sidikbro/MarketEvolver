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
from market_evolver.expert.schemas import ExpertStatus
from market_evolver.expert.seed import EXPERTS_BY_ID
from market_evolver.storage.models import Base, ExpertTopologyVersionModel
from market_evolver.topology.engine import (
    activation_event,
    build_challenger,
    detect_gaps,
    evaluate_topology,
    propose_split,
    rollback_event,
    validate_capability_inheritance,
)
from market_evolver.topology.policy import DEFAULT_TOPOLOGY_POLICY
from market_evolver.topology.repository import SqlTopologyRepository
from market_evolver.topology.schemas import (
    GapCategory,
    ProposedExpert,
    RelationshipType,
    TopologyAction,
    TopologyEdge,
    TopologyHoldoutAccess,
    TopologyMetrics,
    TopologyNode,
    TopologyProposal,
    TopologyProposalStatus,
    TopologyProposalType,
    TopologyRegistryEvent,
    TopologyState,
    TopologyVersion,
)

T0 = datetime(2025, 1, 1, tzinfo=UTC)


def parent():
    return replace(EXPERTS_BY_ID["expert.technology_ai"], status=ExpertStatus.APPROVED)


def child(expert_id="expert.semiconductor", tools=("get_fundamentals", "get_filings")):
    return ProposedExpert(
        expert_id,
        "Semiconductor Expert",
        "semiconductors",
        (parent().expert_id,),
        tools,
        ("official", "filing"),
        ("semiconductor_cycle",),
        ("short_term", "medium_term"),
        ("check cycle", "check capex"),
        (("sector", "semiconductors"),),
        ("case:semi:1", "case:semi:2"),
    )


def root():
    general = EXPERTS_BY_ID["expert.general"]
    tech = parent()
    return TopologyVersion(
        None,
        None,
        (
            TopologyNode(general.expert_id, general.definition_id, general.domain, T0),
            TopologyNode(tech.expert_id, tech.definition_id, tech.domain, T0),
        ),
        (TopologyEdge(tech.expert_id, general.expert_id, RelationshipType.FALLBACK, (), 1),),
        (),
        "router:1",
        T0,
        "governance:seed",
        TopologyState.ACTIVE,
        "benchmark:root",
        "passed",
        ("fixed-experts:v0.18",),
    )


def gaps():
    return detect_gaps(
        parent().expert_id,
        parent().domain,
        T0 + timedelta(1),
        {
            GapCategory.LOW_MECHANISM_COVERAGE: (5, 3, ("scorecard:1",)),
            GapCategory.REVIEWER_REJECTION: (2, 3, ("review:1",)),
        },
    )


def proposal(created="operator:review"):
    return propose_split(parent(), gaps(), (child(),), T0 + timedelta(2), created)


def checks(**changes):
    values = {
        key: True
        for key in (
            "provenance",
            "temporal",
            "capability",
            "adversarial",
            "generalist",
            "domain",
            "holdout",
            "cost_latency",
        )
    }
    values.update(changes)
    return tuple(values.items())


def metrics(**changes):
    item = TopologyMetrics(0.8, 0.9, 0.8, 0, 0.85, 0.1, 10, 100, 2, 1, 1, 0.1)
    return replace(item, **changes)


class TopologyTests(unittest.TestCase):
    def test_deterministic_gaps_are_review_signals(self):
        result = gaps()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].category, GapCategory.LOW_MECHANISM_COVERAGE)

    def test_split_inherits_only_parent_capabilities(self):
        validate_capability_inheritance(child(), (parent(),))
        with self.assertRaises(GovernanceViolation):
            validate_capability_inheritance(
                child(tools=("get_fundamentals", "get_geopolitical_events")), (parent(),)
            )

    def test_runtime_capability_and_safety_mutation_are_rejected(self):
        with self.assertRaises(ValidationError):
            child(tools=("runtime_order",))
        with self.assertRaises(ValidationError):
            TopologyProposal(
                TopologyProposalType.CHANGE_ROUTING,
                ("e",),
                (parent().expert_id,),
                (),
                (("risk_policy", "weaker"),),
                "change",
                "benefit",
                ("failure",),
                ("case",),
                "operator",
                T0,
                TopologyProposalStatus.PROPOSED,
                ("e",),
            )

    def test_model_feedback_remains_untrusted_proposal(self):
        item = proposal("model:mock-topology")
        self.assertEqual(item.status, TopologyProposalStatus.PROPOSED)
        with self.assertRaises(ValidationError):
            replace(item, status=TopologyProposalStatus.APPROVED)

    def test_challenger_build_and_router_integrity(self):
        item = proposal()
        challenger = build_challenger(
            root(), item, {child().expert_id: "expert-version:semi"}, T0 + timedelta(3), "operator"
        )
        self.assertEqual(len(challenger.nodes), 3)
        self.assertTrue(
            any(edge.relationship is RelationshipType.PARENT_CHILD for edge in challenger.edges)
        )
        with self.assertRaises(ValidationError):
            replace(
                challenger,
                edges=(
                    TopologyEdge("missing", parent().expert_id, RelationshipType.ROUTES_TO, (), 1),
                ),
            )

    def test_certification_and_safety_veto_override_quality(self):
        item = proposal()
        champion = root()
        challenger = build_challenger(
            champion, item, {child().expert_id: "v:semi"}, T0 + timedelta(3), "operator"
        )
        result = evaluate_topology(
            item,
            champion,
            challenger,
            "manifest",
            metrics(),
            metrics(benchmark_quality=0.99, safety_violations=1),
            (("case", "correct"),),
            checks(),
            T0 + timedelta(4),
            DEFAULT_TOPOLOGY_POLICY,
        )
        self.assertEqual(result.decision, "quarantined")
        with self.assertRaises(GovernanceViolation):
            activation_event(
                challenger, champion, result, "governance:alice", "quality", T0 + timedelta(5)
            )

    def test_cost_and_routing_quality_prevent_verbose_topology_win(self):
        item = proposal()
        champion = root()
        challenger = build_challenger(
            champion, item, {child().expert_id: "v:semi"}, T0 + timedelta(3), "operator"
        )
        result = evaluate_topology(
            item,
            champion,
            challenger,
            "manifest",
            metrics(),
            metrics(
                benchmark_quality=0.9, routing_accuracy=0.7, provider_cost=14, average_panel_size=6
            ),
            (("ambiguous", "missed"),),
            checks(),
            T0 + timedelta(4),
            DEFAULT_TOPOLOGY_POLICY,
        )
        self.assertEqual(result.decision, "rejected")
        self.assertTrue(
            {"ROUTING_ACCURACY", "COST_INCREASE", "PANEL_TOO_LARGE"} <= set(result.reasons)
        )

    def test_self_activation_is_rejected(self):
        with self.assertRaises(ValidationError):
            TopologyRegistryEvent(
                "v2", "v1", TopologyAction.ACTIVATION, "expert:semi", "self activate", T0
            )

    def test_point_in_time_replay_and_rollback_integrity(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            repo = SqlTopologyRepository(session)
            champion = root()
            repo.add_version(champion)
            initial = TopologyRegistryEvent(
                champion.topology_version_id,
                None,
                TopologyAction.INITIAL_ACTIVATION,
                "governance:seed",
                "initial",
                T0,
            )
            repo.add_registry_event(initial)
            item = proposal()
            repo.add_proposal(item)
            session.flush()
            challenger = build_challenger(
                champion, item, {child().expert_id: "v:semi"}, T0 + timedelta(3), "operator"
            )
            repo.add_version(challenger)
            session.flush()
            good = evaluate_topology(
                item,
                champion,
                challenger,
                "manifest",
                metrics(),
                metrics(benchmark_quality=0.85),
                (("case", "correct"),),
                checks(),
                T0 + timedelta(4),
                DEFAULT_TOPOLOGY_POLICY,
            )
            repo.add_evaluation(good)
            session.flush()
            active = activation_event(
                challenger, champion, good, "governance:alice", "certified", T0 + timedelta(5)
            )
            repo.add_registry_event(active)
            rolled = rollback_event(
                champion.topology_version_id,
                challenger.topology_version_id,
                "governance:alice",
                "degradation",
                T0 + timedelta(6),
            )
            repo.add_registry_event(rolled)
            session.flush()
            self.assertEqual(repo.active_at(T0 + timedelta(4)), champion)
            self.assertEqual(repo.active_at(T0 + timedelta(days=7)), champion)
            self.assertEqual(len(repo.history()), 3)
            row = session.get(ExpertTopologyVersionModel, challenger.topology_version_id)
            assert row
            row.state = "deleted"
            with self.assertRaises(ImmutableRecordError):
                session.flush()
        engine.dispose()

    def test_future_topology_does_not_leak_backward(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            repo = SqlTopologyRepository(session)
            champion = root()
            repo.add_version(champion)
            repo.add_registry_event(
                TopologyRegistryEvent(
                    champion.topology_version_id,
                    None,
                    TopologyAction.INITIAL_ACTIVATION,
                    "governance",
                    "initial",
                    T0 + timedelta(2),
                )
            )
            session.flush()
            self.assertIsNone(repo.active_at(T0 + timedelta(1)))
        engine.dispose()

    def test_final_holdout_reuse_and_fabricated_evaluation_are_rejected(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            repo = SqlTopologyRepository(session)
            champion = root()
            repo.add_version(champion)
            session.flush()
            access = TopologyHoldoutAccess(
                champion.topology_version_id, "manifest", T0, "operator", "final"
            )
            repo.audit_holdout(access, DEFAULT_TOPOLOGY_POLICY)
            session.flush()
            with self.assertRaises(IntegrityViolation):
                repo.audit_holdout(
                    replace(access, accessed_at=T0 + timedelta(1)), DEFAULT_TOPOLOGY_POLICY
                )
            item = proposal()
            challenger = build_challenger(
                champion, item, {child().expert_id: "v:semi"}, T0 + timedelta(3), "operator"
            )
            fake = evaluate_topology(
                item,
                champion,
                challenger,
                "fabricated",
                metrics(),
                metrics(),
                (("case", "correct"),),
                checks(),
                T0 + timedelta(4),
                DEFAULT_TOPOLOGY_POLICY,
            )
            with self.assertRaises(IntegrityViolation):
                repo.add_evaluation(fake)
        engine.dispose()

    def test_routing_trace_is_append_only_and_attributable(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            repo = SqlTopologyRepository(session)
            champion = root()
            repo.add_version(champion)
            session.flush()
            first = repo.add_routing_trace(
                champion.topology_version_id,
                T0,
                "company:nice",
                (parent().expert_id,),
                (parent().expert_id,),
                ("case:route",),
            )
            second = repo.add_routing_trace(
                champion.topology_version_id,
                T0,
                "company:nice",
                (parent().expert_id,),
                (parent().expert_id,),
                ("case:route",),
            )
            self.assertEqual(first, second)
        engine.dispose()

    def test_seed_topology_scenarios(self):
        scenarios = {
            "technology_split": "certified",
            "split_no_value": "rejected",
            "safe_merge": "certified",
            "merge_coverage_loss": "rejected",
            "forbidden_capability": "quarantined",
            "cheap_bad_router": "rejected",
            "panel_contradiction_gain": "certified",
            "panel_cost_no_value": "rejected",
            "degradation": "rollback",
        }
        self.assertEqual(len(scenarios), 9)


if __name__ == "__main__":
    unittest.main()
