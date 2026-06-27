"""Classify a text region's scope by where it sits (our logic, §7.1).

The play area is the ``v``-band spanned by the lane model; margins lie outside
it; header/footer are the leading/trailing ``u``-bands. Boxes near a band
boundary are reported as uncertain so a review item can be raised.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from perfora.model.document import TextScope

if TYPE_CHECKING:
    from perfora.config import Config
    from perfora.model.document import LaneModel
    from perfora.model.geometry import BBox


def classify_scope(
    bbox_mm: BBox,
    lane_model: LaneModel,
    roll_len_mm: float,
    config: Config,
) -> tuple[TextScope, bool]:
    """Return ``(scope, uncertain)`` for a text box.

    ``uncertain`` is ``True`` when the box sits within
    ``config.scope_edge_mm`` of the play-area ``v`` band or of the
    header/footer ``u`` thresholds (a boundary case worth review).
    """
    m = config.play_margin_mm
    v_min = lane_model.v_center(0)
    v_max = lane_model.v_center(max(0, lane_model.n_lanes - 1))
    vc = bbox_mm.v_center

    lo, hi = v_min - m, v_max + m
    in_play_v = lo <= vc <= hi
    edge = config.scope_edge_mm
    near_v_edge = abs(vc - lo) < edge or abs(vc - hi) < edge

    header_u = config.header_frac * roll_len_mm
    footer_u = (1.0 - config.footer_frac) * roll_len_mm

    if not in_play_v:
        return (TextScope.GLOBAL_MARGIN, near_v_edge)
    if bbox_mm.u1 < header_u:
        return (TextScope.GLOBAL_HEADER, abs(bbox_mm.u1 - header_u) < edge)
    if bbox_mm.u0 > footer_u:
        return (TextScope.GLOBAL_FOOTER, abs(bbox_mm.u0 - footer_u) < edge)
    near_u_edge = (
        abs(bbox_mm.u1 - header_u) < edge or abs(bbox_mm.u0 - footer_u) < edge
    )
    return (TextScope.TIMELINE, near_v_edge or near_u_edge)
