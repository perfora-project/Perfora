"""Progress reporting and cooperative cancellation.

Long stages — video reconstruction (per frame) and OCR (per box) — report
progress and poll :meth:`ProgressReporter.cancelled` so a UI can show a bar and
stop a run cleanly. Short stages may ignore the reporter entirely.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from perfora.pipeline.session import StageResult


@runtime_checkable
class ProgressReporter(Protocol):
    """Receives progress callbacks and answers cancellation queries."""

    def on_stage_start(self, stage: str, total: int | None = None) -> None:
        """Called once when ``stage`` begins. ``total`` is the unit count if known."""
        ...

    def on_progress(self, stage: str, done: int, total: int) -> None:
        """Called repeatedly within a long stage as units complete."""
        ...

    def on_stage_end(self, stage: str, result: StageResult) -> None:
        """Called once when ``stage`` finishes, with its :class:`StageResult`."""
        ...

    def cancelled(self) -> bool:
        """Return ``True`` to request a cooperative stop; long stages poll this."""
        ...


class NullProgressReporter:
    """A reporter that does nothing and never cancels (the default)."""

    def on_stage_start(self, stage: str, total: int | None = None) -> None:
        return None

    def on_progress(self, stage: str, done: int, total: int) -> None:
        return None

    def on_stage_end(self, stage: str, result: StageResult) -> None:
        return None

    def cancelled(self) -> bool:
        return False
