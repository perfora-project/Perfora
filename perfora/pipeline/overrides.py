"""User corrections that stages honour — the place a UI "comes in".

Every stage reads the :class:`Overrides` fields that concern it *before*
computing: :class:`~perfora.sources.image_source.ImageSource` uses
``page_corners_px`` instead of auto-detecting corners; lane finding treats
``lane_pitch_mm`` as fixed (or a strong prior); note assembly applies
``note_edits``; the text stage applies ``text_edits``. Overrides live in the
context, so they serialize with the session and round-trip (see
:meth:`to_dict` / :meth:`from_dict`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class NoteEdit:
    """A tagged correction to the assembled notes.

    Parameters
    ----------
    op : str
        ``"add"``, ``"remove"`` or ``"move"``.
    ref_id : int or None
        Index into ``RollDocument.notes`` for ``"remove"``/``"move"``.
    lane : int or None
        Target lane for ``"add"`` (or a new lane for ``"move"``).
    u_start_mm, u_end_mm : float or None
        New endpoints along ``u`` for ``"add"``/``"move"``.
    """

    op: str
    ref_id: int | None = None
    lane: int | None = None
    u_start_mm: float | None = None
    u_end_mm: float | None = None


@dataclass(slots=True)
class TextEdit:
    """A tagged correction to a detected/recognized text region.

    Parameters
    ----------
    op : str
        ``"set_text"``, ``"set_scope"``, ``"set_kind"``, ``"add"`` or
        ``"remove"``.
    ref_id : int or None
        Index into ``RollDocument.texts`` for edits to an existing region.
    text : str or None
        New string for ``"set_text"``/``"add"``.
    scope : str or None
        New :class:`~perfora.model.document.TextScope` *value* for
        ``"set_scope"``/``"add"``.
    kind : str or None
        New :class:`~perfora.model.document.TextKind` *value* for
        ``"set_kind"``/``"add"``.
    bbox_mm : tuple[float, float, float, float] or None
        ``(u0, v0, u1, v1)`` for an ``"add"`` of a missed box.
    """

    op: str
    ref_id: int | None = None
    text: str | None = None
    scope: str | None = None
    kind: str | None = None
    bbox_mm: tuple[float, float, float, float] | None = None


@dataclass(slots=True)
class Overrides:
    """All the user-supplied corrections a session may carry."""

    # geometry / source
    page_corners_px: list[tuple[float, float]] | None = None
    orientation: str | None = None  # "auto" | "as_is" | "rot90" | ...
    binarization_mode: str | None = None  # "bright_holes"|"dark_holes"|"adaptive"
    # lanes — skip or seed auto-detection
    lane_pitch_mm: float | None = None
    lane_v0_mm: float | None = None
    n_lanes: int | None = None
    # video
    roi_px: tuple[int, int, int, int] | None = None
    travel: str | None = None  # "auto" | "up" | "down" | ...
    # content edits (applied after the relevant stage)
    note_edits: list[NoteEdit] = field(default_factory=list)
    text_edits: list[TextEdit] = field(default_factory=list)
    resolved_reviews: set[tuple[str, int]] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of these overrides."""
        return {
            "page_corners_px": (
                None
                if self.page_corners_px is None
                else [list(p) for p in self.page_corners_px]
            ),
            "orientation": self.orientation,
            "binarization_mode": self.binarization_mode,
            "lane_pitch_mm": self.lane_pitch_mm,
            "lane_v0_mm": self.lane_v0_mm,
            "n_lanes": self.n_lanes,
            "roi_px": None if self.roi_px is None else list(self.roi_px),
            "travel": self.travel,
            "note_edits": [asdict(e) for e in self.note_edits],
            "text_edits": [asdict(e) for e in self.text_edits],
            "resolved_reviews": [list(t) for t in sorted(self.resolved_reviews)],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Overrides:
        """Reconstruct :class:`Overrides` from :meth:`to_dict` output."""
        corners = d.get("page_corners_px")
        roi = d.get("roi_px")
        note_edits = [NoteEdit(**e) for e in d.get("note_edits", [])]
        text_edits: list[TextEdit] = []
        for e in d.get("text_edits", []):
            bb = e.get("bbox_mm")
            text_edits.append(
                TextEdit(
                    op=e["op"],
                    ref_id=e.get("ref_id"),
                    text=e.get("text"),
                    scope=e.get("scope"),
                    kind=e.get("kind"),
                    bbox_mm=(
                        None
                        if bb is None
                        else (float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]))
                    ),
                )
            )
        return cls(
            page_corners_px=(
                None
                if corners is None
                else [(float(p[0]), float(p[1])) for p in corners]
            ),
            orientation=d.get("orientation"),
            binarization_mode=d.get("binarization_mode"),
            lane_pitch_mm=d.get("lane_pitch_mm"),
            lane_v0_mm=d.get("lane_v0_mm"),
            n_lanes=d.get("n_lanes"),
            roi_px=(
                None
                if roi is None
                else (int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3]))
            ),
            travel=d.get("travel"),
            note_edits=note_edits,
            text_edits=text_edits,
            resolved_reviews={
                (str(t[0]), int(t[1])) for t in d.get("resolved_reviews", [])
            },
        )
