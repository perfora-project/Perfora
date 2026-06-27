"""Geometry primitives and the perfora axis convention.

Two named axes are used everywhere in the model:

``u``
    The travel / length axis — the direction the roll moves through the player.
    Notes extend along ``u``.
``v``
    The cross axis — across the roll's width, where pitch / lane lives. Lane
    index increases with ``v``.

All coordinates in this module are floats in **millimetres**. Pixel-space lives
only inside image-processing code; anything that leaves a stage is mm.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Axis(enum.Enum):
    """The two roll axes. See module docstring for the convention."""

    U = "u"  # travel / length axis (notes extend along u)
    V = "v"  # cross axis / width (pitch / lane lives along v)


@dataclass(frozen=True, slots=True)
class BBox:
    """Axis-aligned box in millimetres on the ``(u, v)`` plane.

    Parameters
    ----------
    u0, u1 : float
        Lower/upper bounds along the travel axis, in mm. ``u0 <= u1`` is
        expected but not enforced.
    v0, v1 : float
        Lower/upper bounds along the cross axis, in mm.
    """

    u0: float
    v0: float
    u1: float
    v1: float

    @property
    def u_span(self) -> tuple[float, float]:
        """``(u0, u1)`` — the extent along the travel axis, in mm."""
        return (self.u0, self.u1)

    @property
    def v_span(self) -> tuple[float, float]:
        """``(v0, v1)`` — the extent along the cross axis, in mm."""
        return (self.v0, self.v1)

    @property
    def u_center(self) -> float:
        """Midpoint along the travel axis, in mm."""
        return 0.5 * (self.u0 + self.u1)

    @property
    def v_center(self) -> float:
        """Midpoint along the cross axis, in mm."""
        return 0.5 * (self.v0 + self.v1)

    @property
    def u_length(self) -> float:
        """Size along the travel axis, in mm."""
        return self.u1 - self.u0

    @property
    def v_width(self) -> float:
        """Size along the cross axis, in mm."""
        return self.v1 - self.v0

    def overlaps_u(self, u0: float, u1: float) -> bool:
        """Whether this box overlaps the ``[u0, u1]`` interval along ``u``."""
        return self.u0 <= u1 and u0 <= self.u1
