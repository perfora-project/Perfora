"""Pure OpenCV helpers for page detection and perspective correction.

These functions are stateless primitives used by :class:`ImageSource`
(``perfora.sources.image_source``) to deskew and crop a flat scan.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray
from scipy import ndimage

__all__ = [
    "background_color",
    "deskew_angle_from_region",
    "find_page_quad",
    "foreground_mask",
    "four_point_warp",
    "largest_filled_region",
    "order_corners",
]


def background_color(bgr: NDArray[Any], frac: float = 0.02) -> NDArray[np.float64]:
    """Estimate the background colour from a border ring (robust median, BGR).

    The scan border is almost always background, and the background is the one
    reliably-uniform thing in a roll scan — so we key on it rather than on the
    roll's (possibly non-uniform) colour.
    """
    h, w = bgr.shape[:2]
    r = max(2, int(frac * min(h, w)))
    img = bgr if bgr.ndim == 3 else cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    ring = np.concatenate(
        [
            img[:r].reshape(-1, 3),
            img[-r:].reshape(-1, 3),
            img[:, :r].reshape(-1, 3),
            img[:, -r:].reshape(-1, 3),
        ]
    )
    return np.asarray(np.median(ring, axis=0), dtype=np.float64)


def foreground_mask(
    bgr: NDArray[Any], bg: NDArray[np.float64], min_dist: float = 18.0
) -> NDArray[np.bool_]:
    """Boolean mask of pixels that differ from the background colour ``bg``.

    The threshold is Otsu on the colour-distance image, floored at ``min_dist``
    so a near-uniform image does not produce a noise mask.
    """
    img = bgr if bgr.ndim == 3 else cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    dist = np.linalg.norm(img.astype(np.float32) - bg, axis=2)
    otsu, _ = cv2.threshold(
        dist.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    thr = max(min_dist, float(otsu))
    return np.asarray(dist > thr, dtype=np.bool_)


def largest_filled_region(mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """Largest connected component of ``mask``, interior holes filled.

    Filling means a perforation (a background-coloured island) is part of the
    returned roll *region*, while still being absent from the foreground mask —
    so ``region & ~foreground`` recovers the perforations.
    """
    opened = ndimage.binary_opening(mask, iterations=1)
    labels, n = ndimage.label(opened)
    if n == 0:
        return np.zeros_like(mask, dtype=np.bool_)
    sizes = ndimage.sum(np.ones_like(labels), labels, index=range(1, n + 1))
    biggest = 1 + int(np.argmax(sizes))
    region = labels == biggest
    return np.asarray(ndimage.binary_fill_holes(region), dtype=np.bool_)


def deskew_angle_from_region(
    region: NDArray[np.bool_], body_frac: float = 0.92
) -> float:
    """Estimate the skew angle (degrees) from a roll region's straight sides.

    Fits the left and right boundary columns against the row index over the
    *full-width body* rows only (those at least ``body_frac`` of the maximum
    width), so a narrowing leader's slanted edges do not bias the estimate, and
    averages the two slopes. Returns the measured skew; rotate by its negative
    to make the sides vertical.
    """
    widths = region.sum(axis=1)
    if widths.max() == 0:
        return 0.0
    body_rows = np.where(widths >= body_frac * widths.max())[0]
    if body_rows.size < 16:
        return 0.0
    lefts = np.argmax(region[body_rows], axis=1).astype(np.float64)
    rights = (
        region.shape[1] - 1 - np.argmax(region[body_rows, ::-1], axis=1)
    ).astype(np.float64)
    rows = body_rows.astype(np.float64)
    slope_left = float(np.polyfit(rows, lefts, 1)[0])
    slope_right = float(np.polyfit(rows, rights, 1)[0])
    slope = 0.5 * (slope_left + slope_right)
    return float(np.degrees(np.arctan(slope)))


def order_corners(pts: NDArray[Any]) -> NDArray[np.float32]:
    """Order 4 corner points as TL, TR, BR, BL using the sum/diff trick.

    Rules
    -----
    * **TL** — minimum ``x + y``
    * **BR** — maximum ``x + y``
    * **TR** — minimum ``y - x``  (low row, high column → top-right)
    * **BL** — maximum ``y - x``  (high row, low column → bottom-left)

    Parameters
    ----------
    pts : NDArray
        Array-like of shape ``(4, 2)`` with ``(x, y)`` corner coordinates
        in any order.  Converted to ``float32`` internally.

    Returns
    -------
    NDArray[np.float32]
        Ordered ``(4, 2)`` array in the sequence TL, TR, BR, BL.
    """
    p = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = p.sum(axis=1)          # x + y per point
    diff = p[:, 1] - p[:, 0]  # y - x per point
    tl = p[int(np.argmin(s))]
    br = p[int(np.argmax(s))]
    tr = p[int(np.argmin(diff))]
    bl = p[int(np.argmax(diff))]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def find_page_quad(
    gray: NDArray[Any],
    *,
    blur_sigma: float,
    canny_low: float,
    canny_high: float,
    eps_frac: float,
    min_area_frac: float,
) -> NDArray[np.float32] | None:
    """Detect the roll page boundary as an ordered quadrilateral.

    Pipeline
    --------
    1. Gaussian blur to suppress noise.
    2. Canny edge detection.
    3. Morphological close (5×5 rect) to bridge small gaps in the border.
    4. External contours sorted by area, largest first.
    5. ``approxPolyDP`` on each contour; the first 4-corner result whose
       area exceeds ``min_area_frac × H × W`` is returned.

    Parameters
    ----------
    gray : NDArray
        Single-channel ``(H, W)`` uint8 image.
    blur_sigma : float
        Standard deviation for :func:`cv2.GaussianBlur`; kernel size is
        computed automatically when ``ksize=(0, 0)``.
    canny_low : float
        Lower hysteresis threshold for :func:`cv2.Canny`.
    canny_high : float
        Upper hysteresis threshold for :func:`cv2.Canny`.
    eps_frac : float
        Polygon-approximation epsilon as a fraction of the contour arc
        length (passed to :func:`cv2.approxPolyDP`).
    min_area_frac : float
        Minimum contour area as a fraction of the total image area
        ``H × W``.

    Returns
    -------
    NDArray[np.float32] or None
        Ordered ``(4, 2)`` float32 corners in TL, TR, BR, BL order, or
        ``None`` when no qualifying quadrilateral is found.
    """
    h, w = int(gray.shape[0]), int(gray.shape[1])
    blurred = cv2.GaussianBlur(gray, (0, 0), blur_sigma)
    edges = cv2.Canny(blurred, canny_low, canny_high)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(
        closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    sorted_contours = sorted(contours, key=cv2.contourArea, reverse=True)
    min_area = min_area_frac * h * w
    for c in sorted_contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, eps_frac * float(peri), True)
        if len(approx) == 4 and float(cv2.contourArea(c)) > min_area:
            pts: NDArray[np.float32] = np.asarray(
                approx, dtype=np.float32
            ).reshape(4, 2)
            return order_corners(pts)
    return None


def four_point_warp(
    image: NDArray[Any], quad: NDArray[np.float32]
) -> NDArray[Any]:
    """Perspective-warp ``image`` so that ``quad`` maps to a tight rectangle.

    The destination rectangle size is estimated from the corner distances:

    * ``width  = max(‖TR − TL‖, ‖BR − BL‖)``
    * ``height = max(‖BL − TL‖, ‖BR − TR‖)``

    Parameters
    ----------
    image : NDArray
        Input image (any number of channels, any dtype).
    quad : NDArray[np.float32]
        ``(4, 2)`` corners in **TL, TR, BR, BL** order (as returned by
        :func:`order_corners`).

    Returns
    -------
    NDArray
        Warped image with the same number of channels and dtype as
        ``image``.
    """
    tl = quad[0].astype(np.float32)
    tr = quad[1].astype(np.float32)
    br = quad[2].astype(np.float32)
    bl = quad[3].astype(np.float32)

    w_top = float(np.linalg.norm(tr - tl))
    w_bot = float(np.linalg.norm(br - bl))
    h_left = float(np.linalg.norm(bl - tl))
    h_right = float(np.linalg.norm(br - tr))

    out_w = max(1, int(round(max(w_top, w_bot))))
    out_h = max(1, int(round(max(h_left, h_right))))

    src_pts = quad.astype(np.float32)
    dst_pts = np.array(
        [[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]], dtype=np.float32
    )
    mat = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped: NDArray[Any] = cv2.warpPerspective(image, mat, (out_w, out_h))
    return warped
