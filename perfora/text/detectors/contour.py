"""ContourDetector: morphology-based text region finder (no extra deps).

Uses only OpenCV and NumPy, which are core dependencies of perfora.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import cv2

from perfora.model.document import TextKind
from perfora.text.base import DetBox

if TYPE_CHECKING:
    from perfora.sources.base import RollImage


class ContourDetector:
    """Find candidate text regions via morphological operations and contours.

    No optional extras required — relies only on OpenCV and NumPy.

    Parameters
    ----------
    min_area_px : int
        Minimum contour area in pixels to keep a detection (drops tiny specks).
    max_area_frac : float
        Maximum box area as a fraction of the full image; boxes larger than
        this are likely the whole image or a large background region.
    close_kernel : tuple[int, int]
        ``(width, height)`` of the rectangular structuring element used for
        the horizontal morphological close that merges characters into word /
        line blobs.  Wider kernel merges more characters; taller kernel makes
        the detector more tolerant of multi-row smearing.
    min_aspect : float
        Minimum width/height ratio.  Text lines are much wider than they are
        tall, so values below this are rejected.
    """

    id = "contour"

    def __init__(
        self,
        min_area_px: int = 50,
        max_area_frac: float = 0.90,
        close_kernel: tuple[int, int] = (20, 3),
        min_aspect: float = 1.5,
    ) -> None:
        self._min_area_px = min_area_px
        self._max_area_frac = max_area_frac
        self._close_kernel = close_kernel
        self._min_aspect = min_aspect

    def detect(self, image: RollImage) -> list[DetBox]:
        """Find text-like regions in *image.gray* using morphology + contours.

        Parameters
        ----------
        image : RollImage
            The canonical roll image; ``image.gray`` is a 2-D ``uint8`` array
            with rows along ``u`` and columns along ``v``.

        Returns
        -------
        list[DetBox]
            One :class:`~perfora.text.base.DetBox` per detected region, with
            ``kind_hint=TextKind.UNKNOWN``.  Coordinates are
            ``(x, y, w, h)`` where ``x`` is the column (``v``-axis) and ``y``
            is the row (``u``-axis).
        """
        gray: Any = image.gray
        h_img, w_img = gray.shape[:2]
        max_area = h_img * w_img * self._max_area_frac

        # --- threshold -------------------------------------------------------
        # Adaptive threshold handles variable lighting better than Otsu on
        # roll images (dark perforations may confuse a global threshold).
        binary: Any = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY_INV,
            blockSize=15,
            C=8,
        )

        # --- horizontal close ------------------------------------------------
        # Merge adjacent characters (and words on the same line) into blobs.
        kw, kh = self._close_kernel
        kernel: Any = cv2.getStructuringElement(
            cv2.MORPH_RECT, (kw, kh)
        )
        closed: Any = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        # --- find contours ---------------------------------------------------
        contours, _ = cv2.findContours(
            closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        boxes: list[DetBox] = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            if area < self._min_area_px:
                continue
            if area > max_area:
                continue
            if h == 0:
                continue
            aspect = w / h
            if aspect < self._min_aspect:
                continue
            boxes.append(
                DetBox(
                    bbox_px=(int(x), int(y), int(w), int(h)),
                    kind_hint=TextKind.UNKNOWN,
                )
            )

        return boxes
