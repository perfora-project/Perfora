"""Flat-scan image source: deskew, crop, orient, and calibrate.

A raw scan is turned into a canonical :class:`~perfora.sources.base.RollImage`
by:

1. Loading the file (or accepting an ndarray).
2. Detecting the roll page boundary as a quadrilateral.
3. Perspective-correcting to a tight rectangle.
4. Rotating so that rows run along **u** (the long/travel axis).
5. Attaching a :class:`~perfora.model.calibration.Calibration`.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from perfora.config import Config
from perfora.errors import PerforaError
from perfora.model.calibration import Calibration
from perfora.model.document import Provenance
from perfora.sources.base import RollImage
from perfora.utils.imaging import (
    background_color,
    deskew_angle_from_region,
    foreground_mask,
    four_point_warp,
    largest_filled_region,
    order_corners,
)

__all__ = ["ImageSource"]


def _segment_deskew_crop(
    color: NDArray[Any], gray: NDArray[Any], cfg: Config
) -> tuple[NDArray[Any], NDArray[Any], NDArray[Any]] | None:
    """Isolate the roll by background-keying, deskew it, and crop to it.

    Returns ``(color, gray, roll_mask)`` cropped to the roll, or ``None`` when
    there is no clear roll-vs-background separation (e.g. the roll fills the
    whole frame) so the caller can fall back to the page-quad path.
    """
    bg = background_color(color)
    region = largest_filled_region(foreground_mask(color, bg))
    area_frac = float(region.mean())
    if area_frac < cfg.min_roll_area_frac or area_frac > 0.999:
        return None

    # deskew_angle_from_region measures the skew; rotate by its negative to undo
    angle = deskew_angle_from_region(region)
    if abs(angle) > 0.02:
        h, w = gray.shape[:2]
        rot = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), -angle, 1.0)
        bg_val = tuple(float(c) for c in bg)
        color = cv2.warpAffine(
            color, rot, (w, h), flags=cv2.INTER_LINEAR, borderValue=bg_val
        )
        gray = cv2.warpAffine(
            gray, rot, (w, h), flags=cv2.INTER_LINEAR, borderValue=float(np.mean(bg))
        )
        region = (
            cv2.warpAffine(
                region.astype(np.uint8), rot, (w, h), flags=cv2.INTER_NEAREST
            )
            > 0
        )

    ys, xs = np.where(region)
    if ys.size == 0:
        return None
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    return (
        color[y0:y1, x0:x1],
        gray[y0:y1, x0:x1],
        np.ascontiguousarray(region[y0:y1, x0:x1]),
    )


class ImageSource:
    """Produce a canonical :class:`RollImage` from a flat roll scan.

    Parameters
    ----------
    src : str, os.PathLike, or NDArray
        Path to an image file, or a BGR (or grayscale) numpy array.
    dpi : float or None, optional
        Scan resolution in dots per inch.  When given,
        ``mm_per_px = 25.4 / dpi`` for both axes.
    physical_width_mm : float or None, optional
        Known physical roll width in mm.  Used only when ``dpi`` is absent;
        the detected pixel width of the oriented image yields
        ``mm_per_px_v``.
    page_corners_px : list of (float, float) or None, optional
        Four ``(x, y)`` pixel corners of the roll page, in any order.
        When supplied the automatic page-detection step is skipped.
    orientation : str or None, optional
        ``None`` or ``"auto"`` — auto-rotate 90° clockwise when the image
        is wider than tall so that rows become the long axis;
        ``"as_is"`` — no rotation;
        ``"rot90"`` — always rotate 90° clockwise.
    config : Config or None, optional
        Pipeline configuration.  Defaults to ``Config()``.
    """

    _src: str | os.PathLike[str] | NDArray[Any]
    _dpi: float | None
    _physical_width_mm: float | None
    _page_corners_px: list[tuple[float, float]] | None
    _orientation: str | None
    _config: Config

    def __init__(
        self,
        src: str | os.PathLike[str] | NDArray[Any],
        *,
        dpi: float | None = None,
        physical_width_mm: float | None = None,
        page_corners_px: list[tuple[float, float]] | None = None,
        orientation: str | None = None,
        config: Config | None = None,
    ) -> None:
        self._src = src
        self._dpi = dpi
        self._physical_width_mm = physical_width_mm
        self._page_corners_px = page_corners_px
        self._orientation = orientation
        self._config = config if config is not None else Config()

    # ------------------------------------------------------------------ #
    # Public interface (satisfies the Source protocol)
    # ------------------------------------------------------------------ #

    def to_roll_image(self) -> RollImage:
        """Deskew, crop, orient, calibrate and return a :class:`RollImage`.

        Returns
        -------
        RollImage
            Normalised canonical image ready for the pipeline.

        Raises
        ------
        PerforaError
            If a file path is given but the image cannot be read.
        """
        import perfora  # lazy to avoid any load-order circularity

        cfg = self._config

        # ---------------------------------------------------------------- #
        # 1.  Load → ensure BGR color + derive gray
        # ---------------------------------------------------------------- #
        color: NDArray[Any]
        source_name: str

        if isinstance(self._src, np.ndarray):
            arr: NDArray[Any] = self._src.copy()
            color = (
                cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR) if arr.ndim == 2 else arr
            )
            source_name = "ndarray"
        else:
            path_str = str(self._src)
            raw: NDArray[Any] | None = cv2.imread(path_str)
            if raw is None:
                raise PerforaError(f"Cannot read image: {path_str!r}")
            color = raw
            source_name = Path(path_str).name

        gray: NDArray[Any] = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)

        # ---------------------------------------------------------------- #
        # 1b. Downscale oversized scans before warping.
        #     OpenCV's warpPerspective/remap asserts every dimension < 32767,
        #     and very large scans are memory-heavy. We shrink so the longest
        #     side <= config.max_image_px and fold the factor into the
        #     calibration so millimetre geometry is preserved.
        # ---------------------------------------------------------------- #
        scale = 1.0
        longest = max(gray.shape[0], gray.shape[1])
        limit = max(1, int(cfg.max_image_px))
        if longest > limit:
            scale = limit / longest
            new_w = max(1, int(round(gray.shape[1] * scale)))
            new_h = max(1, int(round(gray.shape[0] * scale)))
            color = cv2.resize(color, (new_w, new_h), interpolation=cv2.INTER_AREA)
            gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # ---------------------------------------------------------------- #
        # 2-3. Isolate the roll. Default: background-keyed segmentation +
        #      edge deskew + crop (handles non-rectangular rolls, e.g. a
        #      narrowing leader, and carries a roll mask). Fallback: page-quad
        #      perspective warp when corners are supplied or no clear
        #      roll-vs-background separation exists.
        # ---------------------------------------------------------------- #
        work_color: NDArray[Any]
        work_gray: NDArray[Any]
        work_mask: NDArray[Any] | None = None

        if self._page_corners_px is not None:
            pts = np.array(self._page_corners_px, dtype=np.float32) * scale
            quad = order_corners(pts)
            work_color = four_point_warp(color, quad)
            work_gray = four_point_warp(gray, quad)
        else:
            seg = _segment_deskew_crop(color, gray, cfg)
            if seg is not None:
                work_color, work_gray, work_mask = seg
            else:
                quad = self._fallback_quad(gray, cfg)
                work_color = four_point_warp(color, quad)
                work_gray = four_point_warp(gray, quad)

        # ---------------------------------------------------------------- #
        # 4.  Orient so that rows = u (travel) = long axis
        # ---------------------------------------------------------------- #
        warp_h: int = int(work_gray.shape[0])
        warp_w: int = int(work_gray.shape[1])
        orient = self._orientation

        if orient is None or orient == "auto":
            should_rotate = warp_w > warp_h
        elif orient == "rot90":
            should_rotate = True
        else:  # "as_is"
            should_rotate = False

        if should_rotate:
            final_color: NDArray[Any] = cv2.rotate(
                work_color, cv2.ROTATE_90_CLOCKWISE
            )
            final_gray: NDArray[Any] = cv2.rotate(
                work_gray, cv2.ROTATE_90_CLOCKWISE
            )
            final_mask: NDArray[Any] | None = (
                cv2.rotate(
                    work_mask.astype(np.uint8), cv2.ROTATE_90_CLOCKWISE
                ).astype(bool)
                if work_mask is not None
                else None
            )
        else:
            final_color = work_color
            final_gray = work_gray
            final_mask = work_mask

        # ---------------------------------------------------------------- #
        # 5.  Calibration  (uses FINAL oriented width = shape[1] in px)
        # ---------------------------------------------------------------- #
        final_w_px: int = int(final_gray.shape[1])
        cal: Calibration

        if self._dpi is not None:
            # After downscaling by ``scale``, one working pixel spans
            # ``1/scale`` original pixels, so mm/px grows accordingly; the
            # effective DPI drops to ``dpi * scale``.
            mm_per_px = (25.4 / self._dpi) / scale
            cal = Calibration(
                mm_per_px_u=mm_per_px,
                mm_per_px_v=mm_per_px,
                dpi=self._dpi * scale,
                source="dpi",
            )
        elif self._physical_width_mm is not None:
            mm_per_px_v = self._physical_width_mm / final_w_px
            cal = Calibration(
                mm_per_px_u=mm_per_px_v,
                mm_per_px_v=mm_per_px_v,
                dpi=None,
                source="physical_width",
            )
        else:
            cal = Calibration(
                mm_per_px_u=1.0,
                mm_per_px_v=1.0,
                dpi=None,
                source="assumed",
            )

        # ---------------------------------------------------------------- #
        # 6.  Provenance
        # ---------------------------------------------------------------- #
        prov = Provenance(
            source_type="image",
            source_name=source_name,
            perfora_version=perfora.__version__,
            created_utc=datetime.now(UTC).isoformat(),
            params={},
        )

        return RollImage(
            gray=final_gray,
            calibration=cal,
            provenance=prov,
            color=final_color,
            roll_mask=final_mask,
        )

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fallback_quad(
        gray: NDArray[Any], cfg: Config
    ) -> NDArray[np.float32]:
        """Return a quad from the largest external contour, or the full image.

        Called when :func:`find_page_quad` finds no qualifying
        quadrilateral.  Re-runs Canny (without morphological close) to
        find the largest contour and fits a minimum-area bounding rectangle
        to it via :func:`cv2.minAreaRect`.  Falls back to the full image
        corners when no contour exists at all.

        Parameters
        ----------
        gray : NDArray
            Single-channel uint8 image.
        cfg : Config
            Pipeline config used for the edge-detection parameters.

        Returns
        -------
        NDArray[np.float32]
            Ordered ``(4, 2)`` float32 corners in TL, TR, BR, BL order.
        """
        img_h: int = int(gray.shape[0])
        img_w: int = int(gray.shape[1])

        blurred = cv2.GaussianBlur(gray, (0, 0), cfg.deskew_blur_sigma)
        edges = cv2.Canny(blurred, cfg.canny_low, cfg.canny_high)
        contours, _ = cv2.findContours(
            edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        if len(contours) > 0:
            largest = max(contours, key=cv2.contourArea)
            box: NDArray[Any] = cv2.boxPoints(cv2.minAreaRect(largest))
            return order_corners(np.asarray(box, dtype=np.float32))

        # Absolute last resort: use the full image frame
        return np.array(
            [[0, 0], [img_w, 0], [img_w, img_h], [0, img_h]],
            dtype=np.float32,
        )
