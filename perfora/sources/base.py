"""The canonical image container and the ``Source`` protocol.

Every input — a flat scan or a video — is normalized to a single
:class:`RollImage` (deskewed, cropped, calibrated). Nothing downstream of the
source knows or cares where the data came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from numpy.typing import NDArray

from perfora.model.calibration import Calibration
from perfora.model.document import Provenance


@dataclass(slots=True)
class RollImage:
    """A normalized, calibrated single-channel image of one roll.

    Parameters
    ----------
    gray : NDArray
        Deskewed, cropped, single-channel image. Rows run along ``u`` (travel),
        columns along ``v`` (width).
    calibration : Calibration
        The px <-> mm relationship for this image.
    provenance : Provenance
        Where the image came from and the effective config used.
    color : NDArray or None, optional
        The original colour image, kept for OCR when available.
    """

    gray: NDArray[Any]
    calibration: Calibration
    provenance: Provenance
    color: NDArray[Any] | None = None
    # Foreground/roll mask (True = roll material region) in the oriented frame,
    # when the source isolated the roll by background-keying. Lets downstream
    # stages restrict hole detection to the roll and ignore the background.
    roll_mask: NDArray[Any] | None = None


@runtime_checkable
class Source(Protocol):
    """Anything that can produce a canonical :class:`RollImage`."""

    def to_roll_image(self) -> RollImage:
        """Produce the normalized, calibrated image for the pipeline."""
        ...
