from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvolutionPolicy:
    minimum_cases: int = 5
    minimum_domain_improvement: float = 0.03
    grounded_noninferiority_margin: float = 0.01
    reviewer_regression_tolerance: float = 0.02
    cost_increase_tolerance: float = 0.20
    maximum_challengers_per_parent: int = 10
    maximum_final_holdout_accesses: int = 1
    automatic_promotion_enabled: bool = False


DEFAULT_EVOLUTION_POLICY = EvolutionPolicy()
