"""EasyOCR-based text detector backend (requires the ``[easyocr]`` extra).

Import of ``easyocr`` happens inside :meth:`EasyOCRDetector.__init__` so that
merely importing this module does not pull in the heavy ML dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from perfora.errors import MissingBackendError
from perfora.model.document import TextKind
from perfora.text.base import DetBox

if TYPE_CHECKING:
    from perfora.sources.base import RollImage


class EasyOCRDetector:
    """Detect text regions with EasyOCR's CRAFT detector.

    Parameters
    ----------
    langs : list[str], optional
        Language codes passed to ``easyocr.Reader``.  Defaults to
        ``["en"]``.

    Raises
    ------
    perfora.errors.MissingBackendError
        If the ``easyocr`` package is not installed.
    """

    id = "easyocr"

    def __init__(self, langs: list[str] | None = None) -> None:
        try:
            import easyocr
        except ImportError as exc:
            raise MissingBackendError("easyocr", "easyocr") from exc

        self._langs = langs or ["en"]
        self._reader: Any = easyocr.Reader(self._langs, gpu=False)

    def detect(self, image: RollImage) -> list[DetBox]:
        """Run EasyOCR detection and return one :class:`DetBox` per region.

        Parameters
        ----------
        image : RollImage
            The canonical roll image.  The colour channel is used when
            available; falls back to ``image.gray`` otherwise.

        Returns
        -------
        list[DetBox]
            Boxes in ``(x, y, w, h)`` pixel coordinates,
            ``kind_hint=TextKind.UNKNOWN``.
        """
        img: Any = image.color if image.color is not None else image.gray
        # readtext returns list of (bbox, text, prob); we only need bbox here.
        results: list[Any] = self._reader.readtext(img)

        boxes: list[DetBox] = []
        for bbox_pts, _text, _prob in results:
            # bbox_pts is [[x0,y0],[x1,y1],[x2,y2],[x3,y3]] (quad)
            pts = bbox_pts
            xs = [int(p[0]) for p in pts]
            ys = [int(p[1]) for p in pts]
            x = min(xs)
            y = min(ys)
            w = max(xs) - x
            h = max(ys) - y
            boxes.append(
                DetBox(
                    bbox_px=(x, y, w, h),
                    kind_hint=TextKind.UNKNOWN,
                )
            )
        return boxes
