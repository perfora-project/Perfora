"""The ``Hole`` intermediate (and, from Phase 1, the hole-extraction stage).

``Hole`` is an internal intermediate produced by hole extraction and consumed by
the lane-finder and note assembler. It lives entirely in pixel space and never
appears in :class:`~perfora.model.document.RollDocument`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Hole:
    """A single connected perforation region, in pixel coordinates.

    Parameters
    ----------
    bbox_px : tuple[int, int, int, int]
        Bounding box as ``(u_min, v_min, u_max, v_max)`` in pixels, where ``u``
        is the row (travel) axis and ``v`` is the column (width) axis.
    centroid_px : tuple[float, float]
        Region centroid as ``(u_px, v_px)``.
    area_px : float
        Region area in pixels (used with the calibration to get mm²).
    """

    bbox_px: tuple[int, int, int, int]
    centroid_px: tuple[float, float]
    area_px: float
