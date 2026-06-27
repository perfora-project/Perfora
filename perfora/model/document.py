"""The internal perfora data model: lanes, notes, text, review items, document.

All spatial quantities are in **millimetres** (names ending in ``_px`` would be
pixels, but none appear in this module). Mapping mm -> time/MIDI is *derived*
(see :meth:`NoteEvent.duration_seconds`), never stored.

The document is index-addressed: ``RollDocument.notes`` and
``RollDocument.texts`` are plain lists whose **position is the stable id**
referenced by :attr:`ReviewItem.ref_id` and
:attr:`TextRegion.associated_note_ids`.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from perfora.model.calibration import Calibration
from perfora.model.geometry import BBox

if TYPE_CHECKING:
    import pandas


# --------------------------------------------------------------------------- #
# Lane model (output of the custom lane-finder)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class LaneModel:
    """Measured lane geometry. No roll-standard constant is ever assumed here.

    Parameters
    ----------
    pitch_mm : float
        Measured spacing between adjacent lane centres, in mm.
    v0_mm : float
        ``v`` position of lane index 0, in mm.
    n_lanes : int
        Number of lanes spanning the play area.
    confidence : float
        How clean/periodic the model is, in ``[0, 1]``.
    method : str
        Which estimator produced it: ``"autocorr"``, ``"fft"`` or ``"comb-fit"``.
    """

    pitch_mm: float
    v0_mm: float
    n_lanes: int
    confidence: float
    method: str

    def v_center(self, lane: int) -> float:
        """Nominal ``v`` centre of ``lane``, in mm (``v0_mm + lane * pitch_mm``)."""
        return self.v0_mm + lane * self.pitch_mm

    def nearest_lane(self, v_mm: float) -> tuple[int, float]:
        """Return ``(lane, residual_mm)`` for a measured ``v`` position.

        ``residual_mm`` is signed: ``v_mm - v_center(lane)``. A residual near
        half the pitch means the position sits ambiguously between two lanes.
        """
        lane = round((v_mm - self.v0_mm) / self.pitch_mm)
        return lane, v_mm - self.v_center(lane)


# --------------------------------------------------------------------------- #
# Notes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class NoteEvent:
    """A single sustained perforation run along ``u`` within one lane.

    Parameters
    ----------
    lane : int
        Lane index from the :class:`LaneModel`.
    v_center_mm : float
        Measured cross-axis centre of the run, in mm.
    u_start_mm, u_end_mm : float
        Leading and trailing edges of the perforation along ``u``, in mm.
    confidence : float
        In ``[0, 1]``.
    pitch : int or None, optional
        MIDI note number. Intentionally **not** produced by the core path; a
        separate optional lane->pitch mapping fills it once a standard is known.
    """

    lane: int
    v_center_mm: float
    u_start_mm: float
    u_end_mm: float
    confidence: float
    pitch: int | None = None

    @property
    def length_mm(self) -> float:
        """Length of the note along ``u``, in mm."""
        return self.u_end_mm - self.u_start_mm

    def duration_seconds(self, feed_rate_mm_per_s: float) -> float:
        """Derived timing. Not stored; computed on demand.

        Parameters
        ----------
        feed_rate_mm_per_s : float
            How fast the roll travels through the player, in mm/s.
        """
        return self.length_mm / feed_rate_mm_per_s


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
class TextScope(enum.Enum):
    """Where a text region belongs relative to the music."""

    GLOBAL_HEADER = "global_header"  # leading margin block (title area, etc.)
    GLOBAL_FOOTER = "global_footer"  # trailing margin block
    GLOBAL_MARGIN = "global_margin"  # side margins outside the play area
    TIMELINE = "timeline"  # inside the play area, tied to a u-range


class TextKind(enum.Enum):
    """Printed vs handwritten text (drives recognizer routing)."""

    PRINTED = "printed"
    HANDWRITTEN = "handwritten"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TextRegion:
    """A recognized (or merely detected) text region on the roll.

    Parameters
    ----------
    text : str
        Recognized string (empty when only detected).
    bbox_mm : BBox
        Location in mm.
    scope : TextScope
        Classified scope (see :func:`perfora.text.scope`).
    kind : TextKind
        Printed/handwritten/unknown.
    confidence : float
        Recognition confidence in ``[0, 1]``.
    recognized_by : str
        Backend id, e.g. ``"tesseract"`` or ``"trocr"`` (``""`` if detect-only).
    needs_review : bool
        ``True`` when confidence is below threshold *or* the region was detected
        but not recognized.
    associated_note_ids : tuple[int, ...], optional
        For ``TIMELINE`` scope, indices into :attr:`RollDocument.notes`.
    category : str or None, optional
        Shallow guess: title/composer/arranger/dynamic/annotation.
    """

    text: str
    bbox_mm: BBox
    scope: TextScope
    kind: TextKind
    confidence: float
    recognized_by: str
    needs_review: bool
    associated_note_ids: tuple[int, ...] = ()
    category: str | None = None


# --------------------------------------------------------------------------- #
# Review queue
# --------------------------------------------------------------------------- #
class ReviewReason(enum.Enum):
    """Why an item was queued for human review."""

    LOW_OCR_CONFIDENCE = "low_ocr_confidence"
    DETECTED_NOT_RECOGNIZED = "detected_not_recognized"  # box found, none read it
    AMBIGUOUS_LANE = "ambiguous_lane"  # hole between two lane centres
    SHORT_OR_NOISY_NOTE = "short_or_noisy_note"
    UNCERTAIN_SCOPE = "uncertain_scope"


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """A low-confidence result for a future UI to resolve.

    Parameters
    ----------
    reason : ReviewReason
        Why it needs review.
    ref_kind : str
        ``"text"`` or ``"note"`` — which list ``ref_id`` indexes.
    ref_id : int
        Index into ``RollDocument.texts`` or ``RollDocument.notes``.
    confidence : float
        The confidence that triggered the item, in ``[0, 1]``.
    message : str
        Human-readable explanation.
    suggestions : tuple[str, ...], optional
        Alternatives (e.g. other OCR readings).
    """

    reason: ReviewReason
    ref_kind: str
    ref_id: int
    confidence: float
    message: str
    suggestions: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Provenance and the document root
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Provenance:
    """How a document was produced.

    Parameters
    ----------
    source_type : str
        ``"image"`` or ``"video"``.
    source_name : str
        Identifier of the input (e.g. a file name).
    perfora_version : str
        Version of perfora that produced the document.
    created_utc : str
        ISO-8601 timestamp.
    params : dict
        The effective :class:`~perfora.config.Config` values used.
    """

    source_type: str
    source_name: str
    perfora_version: str
    created_utc: str
    params: dict[str, float | int | str | bool]


@dataclass(slots=True)
class RollDocument:
    """The root of the internal model: everything decoded from one roll.

    ``notes`` and ``texts`` are index-addressed (position == stable id). The
    optional ``debug`` mapping carries non-serialized intermediate layers (masks,
    density profiles) and is excluded from equality and from any format.
    """

    provenance: Provenance
    calibration: Calibration
    lane_model: LaneModel
    notes: list[NoteEvent]
    texts: list[TextRegion]
    review_queue: list[ReviewItem]
    standard_guess: str | None = None
    debug: dict[str, object] = field(default_factory=dict, compare=False)

    def to_dataframe(self) -> pandas.DataFrame:
        """Return the notes as a tidy :class:`pandas.DataFrame`.

        Columns: ``lane, v_center_mm, u_start_mm, u_end_mm, length_mm,
        confidence, pitch``. pandas is imported lazily so the hot path need not
        touch it.
        """
        import pandas as pd

        return pd.DataFrame(
            {
                "lane": [n.lane for n in self.notes],
                "v_center_mm": [n.v_center_mm for n in self.notes],
                "u_start_mm": [n.u_start_mm for n in self.notes],
                "u_end_mm": [n.u_end_mm for n in self.notes],
                "length_mm": [n.length_mm for n in self.notes],
                "confidence": [n.confidence for n in self.notes],
                "pitch": [n.pitch for n in self.notes],
            }
        )
