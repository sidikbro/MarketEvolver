"""Immutable, content-addressed raw artifact storage."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from market_evolver.errors import IntegrityViolation


@dataclass(frozen=True, slots=True)
class Artifact:
    sha256: str
    size_bytes: int
    mime_type: str
    relative_path: str


class ArtifactStore(Protocol):
    """Backend contract for immutable raw bytes."""

    def put(
        self,
        content: bytes,
        *,
        mime_type: str,
        expected_sha256: str | None = None,
    ) -> Artifact: ...

    def read(self, artifact: Artifact) -> bytes: ...


class LocalArtifactStore:
    """Store bytes under SHA-256 paths, atomically and without replacement."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @staticmethod
    def digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _relative_path(self, digest: str) -> Path:
        return Path("sha256") / digest[:2] / digest[2:4] / digest

    def put(
        self,
        content: bytes,
        *,
        mime_type: str,
        expected_sha256: str | None = None,
    ) -> Artifact:
        digest = self.digest(content)
        if expected_sha256 is not None and digest != expected_sha256:
            raise IntegrityViolation("artifact content does not match expected SHA-256")
        relative = self._relative_path(digest)
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            self._verify_existing(destination, digest)
        else:
            temporary: Path | None = None
            try:
                descriptor, name = tempfile.mkstemp(prefix=".artifact-", dir=destination.parent)
                temporary = Path(name)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(temporary, destination)
                except FileExistsError:
                    self._verify_existing(destination, digest)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

        return Artifact(digest, len(content), mime_type, relative.as_posix())

    def read(self, artifact: Artifact) -> bytes:
        path = self.root / artifact.relative_path
        content = path.read_bytes()
        if len(content) != artifact.size_bytes or self.digest(content) != artifact.sha256:
            raise IntegrityViolation("stored artifact failed integrity verification")
        return content

    def _verify_existing(self, path: Path, expected_digest: str) -> None:
        if self.digest(path.read_bytes()) != expected_digest:
            raise IntegrityViolation("existing artifact has content/hash mismatch")
