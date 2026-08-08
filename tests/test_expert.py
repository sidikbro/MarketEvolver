import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.errors import GovernanceViolation, ImmutableRecordError, ValidationError
from market_evolver.expert.evaluation import (
    BENCHMARK_CASES,
    ApprovalPolicy,
    compare,
    disagreement,
    should_suspend,
    transition,
)
from market_evolver.expert.repository import SqlExpertRepository
from market_evolver.expert.routing import panel_route, route
from market_evolver.expert.schemas import (
    AssessmentItem,
    AuditDecision,
    ExpertAssessment,
    ExpertResearchSession,
    ExpertScorecard,
    ExpertStatus,
    Horizon,
    SessionStatus,
)
from market_evolver.expert.seed import EXPERTS_BY_ID, FIXED_EXPERTS
from market_evolver.expert.tools import ResearchToolRegistry, ToolResult
from market_evolver.storage.models import Base, ExpertDefinitionModel

T0 = datetime(2025, 1, 1, tzinfo=UTC)


def approved(expert_id="expert.technology_ai"):
    return replace(EXPERTS_BY_ID[expert_id], status=ExpertStatus.APPROVED)


def assessment(
    session_id="session:1",
    text="Revenue growth is evidenced.",
    confidence=0.8,
    evidence=("evidence:1",),
):
    return ExpertAssessment(
        session_id,
        (AssessmentItem(text, evidence),),
        (),
        (AssessmentItem("Margins are measurable.", evidence),),
        (),
        (("cloud_capex",),),
        ("customer concentration unknown",),
        Horizon.MEDIUM_TERM,
        confidence,
        evidence,
        ("expectation state unknown",),
        T0,
    )


def scorecard(expert, **changes):
    item = ExpertScorecard(
        expert.definition_id,
        T0,
        4,
        0.95,
        0.05,
        0.8,
        0.7,
        0.8,
        0.8,
        0,
        100,
        500,
        "0",
        0,
        0,
        0,
        0,
        0,
        0.1,
    )
    return replace(item, **changes)


class ExpertFrameworkTests(unittest.TestCase):
    def test_six_fixed_reviewed_experts_and_checklists(self):
        self.assertEqual(len(FIXED_EXPERTS), 6)
        self.assertEqual(
            {item.domain for item in FIXED_EXPERTS},
            {
                "general",
                "technology_ai",
                "israel_real_estate",
                "banking_macro",
                "defense_geopolitics",
                "energy",
            },
        )
        self.assertTrue(all("paper_order" in item.forbidden_capabilities for item in FIXED_EXPERTS))

    def test_forbidden_tool_and_host_grant_are_distinct(self):
        expert = approved()
        registry = ResearchToolRegistry()
        audit = registry.authorize(
            expert,
            "session",
            "get_geopolitical_events",
            requested_at=T0,
            cutoff=T0,
            entity_id="company:nice",
            entity_type="company",
            source_class="official",
        )
        self.assertEqual(audit.decision, AuditDecision.DENIED)
        self.assertEqual(audit.reason_code, "FORBIDDEN_TOOL")
        allowed = registry.authorize(
            expert,
            "session",
            "get_fundamentals",
            requested_at=T0,
            cutoff=T0,
            entity_id="company:nice",
            entity_type="company",
            source_class="official",
        )
        self.assertEqual(allowed.decision, AuditDecision.ALLOWED)
        with self.assertRaises(GovernanceViolation):
            registry.call(allowed)

    def test_future_cross_domain_and_raw_social_are_denied(self):
        expert = approved()
        registry = ResearchToolRegistry()
        future = registry.authorize(
            expert,
            "s",
            "get_events",
            requested_at=T0,
            cutoff=T0 + timedelta(1),
            entity_id="x",
            entity_type="company",
            source_class="official",
        )
        self.assertEqual(future.reason_code, "FUTURE_CUTOFF")
        cross = registry.authorize(
            expert,
            "s",
            "get_events",
            requested_at=T0,
            cutoff=T0,
            entity_id="oil",
            entity_type="commodity",
            source_class="official",
        )
        self.assertEqual(cross.reason_code, "CROSS_DOMAIN_ENTITY")
        social = registry.authorize(
            expert,
            "s",
            "get_events",
            requested_at=T0,
            cutoff=T0,
            entity_id="x",
            entity_type="company",
            source_class="raw_social",
        )
        self.assertEqual(social.reason_code, "FORBIDDEN_SOURCE_CLASS")

    def test_tool_result_enforces_cutoff(self):
        with self.assertRaises(GovernanceViolation):
            ToolResult("get_events", T0, ({"first_observed_at": T0 + timedelta(1)},), ("e:1",))

    def test_direct_order_and_recommendation_injection(self):
        for text in ("BUY this company", "create a PaperOrder", "recommend allocation"):
            with self.assertRaises(ValidationError):
                AssessmentItem(text, ("e:1",))

    def test_assessment_requires_attributable_evidence(self):
        with self.assertRaises(ValidationError):
            ExpertAssessment(
                "s",
                (AssessmentItem("Grounded", ("fabricated",)),),
                (),
                (),
                (),
                (),
                (),
                Horizon.SHORT_TERM,
                0.5,
                ("e:real",),
                (),
                T0,
            )

    def test_session_rejects_unauthorized_tool_and_future_cutoff(self):
        expert = approved()
        with self.assertRaises(ValidationError):
            ExpertResearchSession(
                expert.definition_id,
                "hypothesis_generation",
                "nice",
                "company",
                expert.domain,
                Horizon.SHORT_TERM,
                T0,
                "manifest",
                ("get_events",),
                ("get_fundamentals",),
                "mock",
                "mock-v1",
                expert.prompt_version,
                T0,
                None,
                SessionStatus.RUNNING,
            )

    def test_routing_and_suspended_exclusion(self):
        experts = tuple(replace(item, status=ExpertStatus.APPROVED) for item in FIXED_EXPERTS)
        decision = route("nice", T0, experts, tags=("technology",), geography="IL")
        self.assertEqual(decision.selected_expert_ids, ("expert.technology_ai",))
        suspended = tuple(
            replace(item, status=ExpertStatus.SUSPENDED)
            if item.expert_id == "expert.technology_ai"
            else item
            for item in experts
        )
        fallback = route("nice", T0, suspended, tags=("technology",), geography="IL")
        self.assertEqual(fallback.selected_expert_ids, ("expert.general",))

    def test_panel_preserves_disagreement(self):
        experts = tuple(replace(item, status=ExpertStatus.APPROVED) for item in FIXED_EXPERTS)
        panel = panel_route("boi-rate", T0, experts, tags=("rates", "real_estate"), geography="IL")
        self.assertIn("expert.general", panel.selected_expert_ids)
        first = assessment(text="Rates constrain demand.", confidence=0.8)
        second = assessment("session:2", "Demand remains supported.", 0.4)
        result = disagreement((first, second))
        self.assertGreater(result.confidence_divergence, 0)
        self.assertEqual(len(result.conflicting_claims), 2)

    def test_specialist_generalist_comparison_uses_same_evidence(self):
        specialist = assessment()
        generalist = assessment("general:1", confidence=0.7)
        result = compare("case", specialist, generalist, 0.8, 0.7)
        self.assertTrue(result.same_evidence)
        self.assertEqual(result.outcome, "specialist_adds_value")

    def test_approval_and_automatic_routing_suspension_policy(self):
        expert = replace(EXPERTS_BY_ID["expert.energy"], status=ExpertStatus.EVALUATION)
        approved_version = transition(
            expert, ExpertStatus.APPROVED, T0 + timedelta(1), scorecard(expert)
        )
        self.assertEqual(approved_version.status, ExpertStatus.APPROVED)
        with self.assertRaises(ValueError):
            transition(
                expert,
                ExpertStatus.APPROVED,
                T0 + timedelta(1),
                scorecard(expert, benchmark_cases=1),
            )
        self.assertTrue(should_suspend(scorecard(expert, fabricated_provenance=1)))
        self.assertEqual(ApprovalPolicy().maximum_safety_violations, 0)

    def test_repository_round_trip_append_only_and_fabrication_gate(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            repo = SqlExpertRepository(session)
            expert = approved()
            self.assertTrue(repo.add_definition(expert))
            session.flush()
            self.assertEqual(repo.latest(expert.expert_id), expert)
            row = session.get(ExpertDefinitionModel, expert.definition_id)
            assert row is not None
            row.status = "suspended"
            with self.assertRaises(ImmutableRecordError):
                session.flush()
            session.rollback()
        engine.dispose()

    def test_benchmark_has_specialist_generalist_adversarial_cases(self):
        outcomes = {item[2] for item in BENCHMARK_CASES}
        self.assertEqual(len(BENCHMARK_CASES), 6)
        self.assertTrue(
            {
                "specialist_adds_value",
                "no_added_value",
                "generalist_better",
                "experts_disagree",
                "safe_denial",
                "caveat_recorded",
            }
            <= outcomes
        )


if __name__ == "__main__":
    unittest.main()
