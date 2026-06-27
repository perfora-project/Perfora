"""Associate a TIMELINE text box with the notes it spans (our logic, §7.2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from perfora.config import Config
    from perfora.model.document import NoteEvent
    from perfora.model.geometry import BBox


def associate(
    bbox_mm: BBox, notes: list[NoteEvent], config: Config
) -> tuple[int, ...]:
    """Return the indices of notes annotated by a TIMELINE box.

    A note is a hit when its ``u`` extent overlaps the box's ``u`` span (padded
    by ``config.assoc_pad_mm``). When ``config.assoc_lane_aware`` is set, hits
    are further restricted to notes whose lane centre lies within the box's
    ``v`` span (padded), so a margin annotation binds to the nearby passage
    rather than the whole row.
    """
    u0, u1 = bbox_mm.u_span
    pad = config.assoc_pad_mm
    hits = [
        i
        for i, n in enumerate(notes)
        if n.u_end_mm >= u0 - pad and n.u_start_mm <= u1 + pad
    ]
    if config.assoc_lane_aware:
        v_lo = bbox_mm.v0 - pad
        v_hi = bbox_mm.v1 + pad
        hits = [i for i in hits if v_lo <= notes[i].v_center_mm <= v_hi]
    return tuple(hits)
