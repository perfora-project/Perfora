"""The text engine: detect -> recognize -> px->mm -> scope -> associate (§6).

Pairs one detector with zero or more recognizers and routes each detected crop
to a recognizer that handles its kind. Boxes with no available recognizer are
still emitted as detection-only :class:`TextRegion`s (``needs_review=True``), so
detection alone is useful to a UI even with no OCR extras installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from perfora.model.document import TextKind, TextRegion, TextScope
from perfora.model.geometry import BBox
from perfora.review.queue import dedupe, scope_review_item, text_review_item
from perfora.text.associate import associate
from perfora.text.scope import classify_scope

if TYPE_CHECKING:
    from perfora.config import Config
    from perfora.model.document import LaneModel, NoteEvent, ReviewItem
    from perfora.sources.base import RollImage
    from perfora.text.base import TextDetector, TextRecognizer

__all__ = ["TextEngine"]


class TextEngine:
    """Pairs a detector with recognizers and produces text regions + reviews."""

    def __init__(
        self, detector: TextDetector, recognizers: list[TextRecognizer]
    ) -> None:
        self.detector = detector
        self.recognizers = recognizers

    def _pick(self, kind_hint: TextKind) -> TextRecognizer | None:
        if not self.recognizers:
            return None
        for r in self.recognizers:
            if r.handles == kind_hint:
                return r
        for r in self.recognizers:
            if r.handles == TextKind.UNKNOWN:
                return r
        return self.recognizers[0]

    def run(
        self,
        image: RollImage,
        lane_model: LaneModel,
        notes: list[NoteEvent],
        config: Config,
    ) -> tuple[list[TextRegion], list[ReviewItem]]:
        """Detect, recognize, scope and associate text; return regions + reviews."""
        mm_u = image.calibration.mm_per_px_u
        mm_v = image.calibration.mm_per_px_v
        h_img, w_img = image.gray.shape[:2]
        roll_len_mm = h_img * mm_u

        texts: list[TextRegion] = []
        reviews: list[ReviewItem] = []
        for box in self.detector.detect(image):
            x, y, w, h = box.bbox_px
            x0 = max(0, int(x))
            y0 = max(0, int(y))
            x1 = min(w_img, int(x + w))
            y1 = min(h_img, int(y + h))
            if x1 <= x0 or y1 <= y0:
                continue

            recognizer = self._pick(box.kind_hint)
            if recognizer is not None:
                crop = image.gray[y0:y1, x0:x1]
                result = recognizer.recognize(crop)
                text, conf, rid = result.text, result.confidence, recognizer.id
            else:
                text, conf, rid = "", 0.0, ""

            bbox_mm = BBox(
                u0=y0 * mm_u, v0=x0 * mm_v, u1=y1 * mm_u, v1=x1 * mm_v
            )
            scope, uncertain = classify_scope(
                bbox_mm, lane_model, roll_len_mm, config
            )
            associated = (
                associate(bbox_mm, notes, config)
                if scope == TextScope.TIMELINE
                else ()
            )
            needs_review = rid == "" or conf < config.ocr_conf_min
            region = TextRegion(
                text=text,
                bbox_mm=bbox_mm,
                scope=scope,
                kind=box.kind_hint,
                confidence=conf,
                recognized_by=rid,
                needs_review=needs_review,
                associated_note_ids=associated,
            )
            idx = len(texts)
            texts.append(region)

            item = text_review_item(idx, region, config)
            if item is not None:
                reviews.append(item)
            if uncertain:
                reviews.append(scope_review_item(idx, region))

        return texts, dedupe(reviews)
