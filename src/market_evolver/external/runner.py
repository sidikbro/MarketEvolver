from __future__ import annotations

import subprocess
from pathlib import Path

from market_evolver.errors import GovernanceViolation
from market_evolver.external.inspection import inspect_repository, verify_runnable


def run_external(
    benchmark_id: str,
    project_root: Path,
    command: tuple[str, ...],
    *,
    operator_approved: bool = False,
    timeout_seconds: int = 3600,
) -> subprocess.CompletedProcess[str]:
    """Run a pinned clean sibling without shell expansion or repository mutation."""
    if not operator_approved:
        raise GovernanceViolation(
            "external benchmark execution requires explicit operator approval"
        )
    if not command:
        raise GovernanceViolation("external benchmark command is required")
    manifest = inspect_repository(benchmark_id, project_root)
    verify_runnable(manifest)
    from market_evolver.external.registry import EXTERNAL_BENCHMARKS

    local_path = EXTERNAL_BENCHMARKS.get(benchmark_id).local_path
    if local_path is None:
        raise GovernanceViolation("external benchmark has no local checkout")
    return subprocess.run(
        command,
        cwd=(project_root / local_path).resolve(),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
