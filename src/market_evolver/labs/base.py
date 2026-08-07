"""Interfaces implemented by future News, Social, Trends, Government, and Geo labs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from market_evolver.config import RuntimePermissions
from market_evolver.schemas import Evidence, Source


@dataclass(frozen=True, slots=True)
class LabContext:
    knowledge_cutoff: datetime
    permissions: RuntimePermissions


class ResearchLab(Protocol):
    """A research-only lab. It produces evidence, never execution requests."""

    @property
    def name(self) -> str: ...

    def research(self, sources: Sequence[Source], context: LabContext) -> Sequence[Evidence]: ...
