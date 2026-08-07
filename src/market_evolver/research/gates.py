"""Temporal, provenance, and historical-name isolation gates."""

from __future__ import annotations

from dataclasses import dataclass

from market_evolver.errors import IntegrityViolation
from market_evolver.research.schemas import ProviderCall, ResearchContext


def validate_context(context: ResearchContext) -> None:
    if any(item.first_observed_at > context.cutoff for item in context.items):
        raise IntegrityViolation("temporal leakage detected before provider invocation")


def validate_provider_output(context: ResearchContext, call: ProviderCall) -> None:
    allowed = frozenset(
        evidence_id
        for item in context.items
        for evidence_id in (
            *((item.provenance_id,) if item.kind == "evidence" else ()),
            *item.evidence_ids,
        )
    )
    for claim in call.structured_result:
        referenced = set(claim.supporting_evidence_ids) | set(claim.contradicting_evidence_ids)
        if not referenced or not referenced <= allowed:
            raise IntegrityViolation("model claim contains absent or fabricated provenance")


@dataclass(frozen=True, slots=True)
class AnonymizedContext:
    context: ResearchContext
    mapping: tuple[tuple[str, str], ...]


def anonymize_context(
    context: ResearchContext, identifying_values: tuple[str, ...] = ()
) -> AnonymizedContext:
    inferred = tuple(
        item.text.split(";", 1)[0]
        for item in context.items
        if item.kind == "company" and ";" in item.text
    )
    tokens = tuple(dict.fromkeys((context.subject_id, *identifying_values, *inferred)))
    aliases = ("COMPANY_A", "COMPANY_B", "COMPANY_C")
    mapping = tuple(
        (value, aliases[index] if index < len(aliases) else f"ENTITY_{index + 1:03d}")
        for index, value in enumerate(tokens)
        if value
    )
    aliases_by_value = dict(mapping)
    items = tuple(
        type(item)(
            kind=item.kind,
            provenance_id=item.provenance_id,
            first_observed_at=item.first_observed_at,
            text=_replace(item.text, aliases_by_value),
            evidence_ids=item.evidence_ids,
        )
        for item in context.items
    )
    return AnonymizedContext(
        ResearchContext(
            context.cutoff,
            aliases_by_value.get(context.subject_id, "COMPANY_A"),
            items,
            True,
        ),
        mapping,
    )


def _replace(text: str, mapping: dict[str, str]) -> str:
    for source, alias in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(source, alias)
    return text
