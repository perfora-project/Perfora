"""Pixel <-> millimetre calibration for the canonical :class:`RollImage`.

A :class:`Calibration` is established by the *source* (see ``perfora.sources``):

* if the scan DPI is known, ``mm_per_px = 25.4 / dpi`` for both axes;
* else, if the operator supplies the roll's physical width, the detected roll
  width in pixels yields ``mm_per_px_v`` and ``mm_per_px_u`` is assumed equal
  (square pixels);
* else both default to ``1.0`` with ``source="assumed"`` — geometry is then in
  "roll units" but everything still round-trips.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Calibration:
    """Maps pixels to millimetres for the canonical :class:`RollImage`.

    Parameters
    ----------
    mm_per_px_u : float
        Millimetres per pixel along the travel axis.
    mm_per_px_v : float
        Millimetres per pixel along the cross axis.
    dpi : float or None, optional
        Set when the calibration was derived from a known scan resolution.
    source : str, optional
        How the calibration was established: ``"dpi"``, ``"physical_width"``,
        ``"assumed"`` (or ``"unknown"`` before a source sets it).
    """

    mm_per_px_u: float
    mm_per_px_v: float
    dpi: float | None = None
    source: str = "unknown"

    def px_to_mm(self, u_px: float, v_px: float) -> tuple[float, float]:
        """Convert a ``(u_px, v_px)`` pixel coordinate to ``(u_mm, v_mm)``."""
        return (u_px * self.mm_per_px_u, v_px * self.mm_per_px_v)

    def mm_to_px(self, u_mm: float, v_mm: float) -> tuple[float, float]:
        """Convert a ``(u_mm, v_mm)`` coordinate to ``(u_px, v_px)`` pixels."""
        return (u_mm / self.mm_per_px_u, v_mm / self.mm_per_px_v)
