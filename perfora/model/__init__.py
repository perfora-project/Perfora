"""The internal perfora data model (millimetre-based, index-addressed).

See :mod:`perfora.model.geometry`, :mod:`perfora.model.calibration`, and
:mod:`perfora.model.document` for the definitions and the ``u``/``v`` axis
convention.
"""

from __future__ import annotations

from perfora.model.calibration import Calibration
from perfora.model.document import (
    LaneModel,
    NoteEvent,
    Provenance,
    ReviewItem,
    ReviewReason,
    RollDocument,
    TextKind,
    TextRegion,
    TextScope,
)
from perfora.model.geometry import Axis, BBox

__all__ = [
    "Axis",
    "BBox",
    "Calibration",
    "LaneModel",
    "NoteEvent",
    "Provenance",
    "ReviewItem",
    "ReviewReason",
    "RollDocument",
    "TextKind",
    "TextRegion",
    "TextScope",
]
