"""Direction-neutral causal mechanism registry."""

from __future__ import annotations

from dataclasses import dataclass

from market_evolver.errors import ValidationError


@dataclass(frozen=True, slots=True)
class CausalMechanism:
    mechanism_id: str
    name: str
    description: str


class MechanismRegistry:
    def __init__(self, mechanisms: tuple[CausalMechanism, ...]) -> None:
        self._mechanisms = {item.mechanism_id: item for item in mechanisms}
        if len(self._mechanisms) != len(mechanisms):
            raise ValidationError("mechanism registry has duplicate identifiers")
        for item in mechanisms:
            lowered = f"{item.name} {item.description}".lower()
            if "buy" in lowered or "sell" in lowered:
                raise ValidationError("mechanisms cannot encode investment directions")

    def get(self, mechanism_id: str) -> CausalMechanism:
        try:
            return self._mechanisms[mechanism_id]
        except KeyError as exc:
            raise ValidationError(f"unknown mechanism: {mechanism_id}") from exc

    def list(self) -> tuple[CausalMechanism, ...]:
        return tuple(sorted(self._mechanisms.values(), key=lambda item: item.mechanism_id))


DEFAULT_MECHANISM_REGISTRY = MechanismRegistry(
    (
        CausalMechanism(
            "currency_translation",
            "Currency translation",
            "Conversion of foreign-currency amounts into a reporting currency.",
        ),
        CausalMechanism(
            "import_cost",
            "Import cost",
            "Exchange-rate or input-price transmission into imported costs.",
        ),
        CausalMechanism(
            "export_competitiveness",
            "Export competitiveness",
            "Relative-price changes affecting exporters in international markets.",
        ),
        CausalMechanism(
            "financing_cost",
            "Financing cost",
            "Changes in the cost of obtaining or servicing funding.",
        ),
        CausalMechanism(
            "credit_demand",
            "Credit demand",
            "Changes in household or business demand for borrowing.",
        ),
        CausalMechanism(
            "interest_margin",
            "Interest margin",
            "Changes in the spread between funding and lending returns.",
        ),
        CausalMechanism(
            "risk_premium",
            "Risk premium",
            "Changes in compensation required for bearing uncertainty.",
        ),
        CausalMechanism(
            "consumer_demand",
            "Consumer demand",
            "Changes in household willingness or ability to purchase goods and services.",
        ),
    )
)
