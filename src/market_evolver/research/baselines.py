"""Deterministic comparison baselines for every constrained task family."""

from __future__ import annotations

from market_evolver.research.schemas import ResearchContext, ResearchTask


def baseline(task: ResearchTask, context: ResearchContext) -> tuple[dict[str, object], ...]:
    if task is ResearchTask.EVIDENCE_SUMMARIZATION:
        return tuple(
            {"provenance_id": item.provenance_id, "summary": item.text[:240]}
            for item in context.items
        )
    if task is ResearchTask.ENTITY_EXTRACTION:
        return ({"entity": context.subject_id, "method": "exact-subject"},)
    if task is ResearchTask.MECHANISM_EXTRACTION:
        return tuple(
            {"mechanism": item.text, "provenance_id": item.provenance_id}
            for item in context.items
            if item.kind == "mechanism"
        )
    if task is ResearchTask.EVENT_EXTRACTION:
        return tuple(
            {"event": item.text, "provenance_id": item.provenance_id}
            for item in context.items
            if item.kind == "event"
        )
    if task is ResearchTask.CONTRADICTION_IDENTIFICATION:
        return ()
    return ()
