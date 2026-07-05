"""Progress reporting and cooperative cancellation.

Long stages — video reconstruction (per frame) and OCR (per box) — report
progress and poll :meth:`ProgressReporter.cancelled` so a UI can show a bar and
stop a run cleanly. Short stages may ignore the reporter entirely.
"""

from __future__ import annotations

import sys
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


# Human-readable action for each built-in stage, shown on its start line. Falls
# back to the raw stage name for any stage not listed (the pipeline is pluggable).
_STAGE_ACTIONS: dict[str, str] = {
    "preprocess": "binarizing image and isolating perforations",
    "holes": "detecting perforations",
    "lanes": "measuring the lane grid",
    "notes": "assembling notes from holes",
    "text": "detecting and recognizing text",
}


class TerminalProgressReporter:
    """Print stage progress to stderr.

    Parameters
    ----------
    verbosity : int
        1 → stage start/end lines (with each stage's summary of what it found);
        2 → also per-unit progress updates for long stages.
    """

    def __init__(self, verbosity: int = 1) -> None:
        self._verbosity = verbosity
        self._in_progress = False  # track whether an in-line progress line is open

    def on_stage_start(self, stage: str, total: int | None = None) -> None:
        """Write a stage-start line naming what the stage is about to do."""
        action = _STAGE_ACTIONS.get(stage, "starting")
        parts = f"[perfora] {stage}: {action}"
        if total is not None:
            parts += f" ({total} units)"
        sys.stderr.write(parts + "\n")
        sys.stderr.flush()
        self._in_progress = False

    def on_progress(self, stage: str, done: int, total: int) -> None:
        """Write an in-place progress indicator when verbosity >= 2."""
        if self._verbosity < 2:
            return
        pct = int(done / max(total, 1) * 100)
        sys.stderr.write(f"\r[perfora] {stage}: {done}/{total} ({pct}%)")
        sys.stderr.flush()
        self._in_progress = True

    def on_stage_end(self, stage: str, result: StageResult) -> None:
        """Write a stage-end line, including what the stage found (its summary)."""
        if self._in_progress:
            sys.stderr.write("\n")
            self._in_progress = False
        line = f"[perfora] {stage}: done"
        facts = result.preview.summary if result.preview is not None else {}
        if facts:
            line += " — " + ", ".join(f"{k}={v}" for k, v in facts.items())
        n = len(result.new_reviews)
        if n:
            line += f" ({n} review item(s))"
        sys.stderr.write(line + "\n")
        sys.stderr.flush()

    def cancelled(self) -> bool:
        """Never cancels; interactive cancellation requires a UI."""
        return False
