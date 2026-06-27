"""Exception hierarchy for the perfora library."""

from __future__ import annotations

__all__ = [
    "PerforaError",
    "CalibrationError",
    "LaneDetectionError",
    "MissingBackendError",
    "FormatError",
    "VideoReconstructionError",
]


class PerforaError(Exception):
    """Base class for all perfora exceptions."""


class CalibrationError(PerforaError):
    """Raised when calibration could not be established."""


class LaneDetectionError(PerforaError):
    """Raised when lane periodicity is entirely undetectable (no lanes found).

    This is only raised when the detector finds *no* lanes at all.  Routine
    low-confidence lane assignments are handled via the review queue instead.
    """


class MissingBackendError(PerforaError):
    """Raised when an optional OCR backend is selected but its extra is absent."""

    backend: str
    extra: str

    def __init__(self, backend: str, extra: str) -> None:
        self.backend = backend
        self.extra = extra
        message = (
            f"Backend {backend!r} is unavailable. "
            f"Install it with: pip install perfora[{extra}]"
        )
        super().__init__(message)


class FormatError(PerforaError):
    """Raised when an I/O format id is unknown or a file cannot be parsed."""


class VideoReconstructionError(PerforaError):
    """Raised when slit-scan correlation collapses for a sustained stretch."""
