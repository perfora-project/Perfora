"""Text detection / recognition interfaces (an interface, per CLAUDE.md #4).

Detection and recognition are split because the strong offline handwriting model
(TrOCR) is recognition-only and expects a cropped line; detectors find the
boxes. Backends implement these protocols and are selected at runtime; the core
never imports a backend's heavy dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from perfora.model.document import TextKind

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from perfora.sources.base import RollImage


@dataclass(frozen=True, slots=True)
class DetBox:
    """A detected text box in the :class:`RollImage`, in pixels.

    Parameters
    ----------
    bbox_px : tuple[int, int, int, int]
        ``(x, y, w, h)`` where ``x`` is the column (``v``) and ``y`` the row
        (``u``).
    kind_hint : TextKind
        Detector's guess of printed vs handwritten (routes recognition).
    """

    bbox_px: tuple[int, int, int, int]
    kind_hint: TextKind = TextKind.UNKNOWN


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    """The output of recognizing one cropped text line."""

    text: str
    confidence: float


@runtime_checkable
class TextDetector(Protocol):
    """Finds candidate text boxes in a :class:`RollImage`."""

    id: str

    def detect(self, image: RollImage) -> list[DetBox]:
        """Return detected boxes (pixel coordinates)."""
        ...


@runtime_checkable
class TextRecognizer(Protocol):
    """Recognizes the text in a cropped image region."""

    id: str
    handles: TextKind  # PRINTED | HANDWRITTEN | UNKNOWN (any)

    def recognize(self, crop: NDArray[Any]) -> RecognitionResult:
        """Return the recognized string and confidence for ``crop``."""
        ...
