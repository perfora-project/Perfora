"""Tests for the text engine, scope, association and review builders."""

from __future__ import annotations

from typing import Any

import numpy as np
from perfora.config import Config
from perfora.model.calibration import Calibration
from perfora.model.document import (
    LaneModel,
    NoteEvent,
    Provenance,
    ReviewItem,
    ReviewReason,
    TextKind,
    TextScope,
)
from perfora.model.geometry import BBox
from perfora.review.queue import dedupe, text_review_item
from perfora.sources.base import RollImage
from perfora.text.associate import associate
from perfora.text.base import DetBox, RecognitionResult
from perfora.text.engine import TextEngine
from perfora.text.scope import classify_scope

LANE_MODEL = LaneModel(
    pitch_mm=3.0, v0_mm=6.0, n_lanes=20, confidence=1.0, method="synthetic"
)  # v_min=6, v_max=63


class FakeDetector:
    id = "fake-det"

    def __init__(self, boxes: list[DetBox]) -> None:
        self.boxes = boxes

    def detect(self, image: RollImage) -> list[DetBox]:
        return self.boxes


class FakeRecognizer:
    def __init__(
        self, text: str, conf: float, handles: TextKind = TextKind.UNKNOWN
    ) -> None:
        self.id = "fake-rec"
        self.text = text
        self.confidence = conf
        self.handles = handles

    def recognize(self, crop: Any) -> RecognitionResult:
        return RecognitionResult(self.text, self.confidence)


def _roll_image(h: int = 1200, w: int = 700, mm: float = 0.1) -> RollImage:
    gray = np.full((h, w), 128, dtype=np.uint8)
    cal = Calibration(mm_per_px_u=mm, mm_per_px_v=mm, dpi=254, source="dpi")
    prov = Provenance("image", "t", "0.1.0", "2026-06-27T00:00:00Z", {})
    return RollImage(gray=gray, calibration=cal, provenance=prov)


# --------------------------------------------------------------------------- #
# scope
# --------------------------------------------------------------------------- #
def test_scope_classification() -> None:
    cfg = Config()
    roll_len = 120.0
    # outside play v-band -> margin
    margin = BBox(u0=40, v0=0, u1=44, v1=3)
    assert classify_scope(margin, LANE_MODEL, roll_len, cfg)[0] is (
        TextScope.GLOBAL_MARGIN
    )
    # in play v, early u -> header
    header = BBox(u0=2, v0=20, u1=10, v1=40)
    assert classify_scope(header, LANE_MODEL, roll_len, cfg)[0] is (
        TextScope.GLOBAL_HEADER
    )
    # in play v, late u -> footer
    footer = BBox(u0=110, v0=20, u1=118, v1=40)
    assert classify_scope(footer, LANE_MODEL, roll_len, cfg)[0] is (
        TextScope.GLOBAL_FOOTER
    )
    # in play v, middle u -> timeline
    timeline = BBox(u0=50, v0=20, u1=58, v1=40)
    assert classify_scope(timeline, LANE_MODEL, roll_len, cfg)[0] is (
        TextScope.TIMELINE
    )


# --------------------------------------------------------------------------- #
# association
# --------------------------------------------------------------------------- #
def test_timeline_association_u_overlap() -> None:
    cfg = Config()
    def _n(u0: float, u1: float) -> NoteEvent:
        return NoteEvent(
            lane=8, v_center_mm=30.0, u_start_mm=u0, u_end_mm=u1, confidence=1.0
        )

    notes = [_n(10.0, 18.0), _n(22.0, 30.0), _n(35.0, 45.0)]
    box = BBox(u0=21.0, v0=28.0, u1=40.0, v1=32.0)
    hits = associate(box, notes, cfg)
    assert hits == (1, 2)


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #
def test_text_stage_detection_only_no_backends() -> None:
    img = _roll_image()
    det = FakeDetector([DetBox(bbox_px=(200, 500, 80, 20))])
    engine = TextEngine(det, recognizers=[])
    texts, reviews = engine.run(img, LANE_MODEL, [], Config())
    assert len(texts) == 1
    r = texts[0]
    assert r.text == "" and r.recognized_by == "" and r.needs_review
    assert any(x.reason is ReviewReason.DETECTED_NOT_RECOGNIZED for x in reviews)


def test_engine_recognizes_and_flags_low_confidence() -> None:
    img = _roll_image()
    det = FakeDetector([DetBox(bbox_px=(200, 500, 80, 20))])
    good = TextEngine(det, [FakeRecognizer("FORTE", 0.9)])
    texts, reviews = good.run(img, LANE_MODEL, [], Config())
    assert texts[0].text == "FORTE" and not texts[0].needs_review
    assert reviews == []

    weak = TextEngine(det, [FakeRecognizer("frte", 0.2)])
    texts2, reviews2 = weak.run(img, LANE_MODEL, [], Config())
    assert texts2[0].needs_review
    assert any(x.reason is ReviewReason.LOW_OCR_CONFIDENCE for x in reviews2)


def test_review_queue_dedupe_and_thresholds() -> None:
    cfg = Config()
    from perfora.model.document import TextRegion

    bb = BBox(0, 0, 1, 1)
    tl = TextScope.TIMELINE
    clean = TextRegion("OK", bb, tl, TextKind.PRINTED, 0.9, "x", False)
    low = TextRegion("o", bb, tl, TextKind.PRINTED, 0.1, "x", True)
    undetected = TextRegion("", bb, tl, TextKind.UNKNOWN, 0.0, "", True)
    assert text_review_item(0, clean, cfg) is None
    assert text_review_item(1, low, cfg).reason is ReviewReason.LOW_OCR_CONFIDENCE
    assert (
        text_review_item(2, undetected, cfg).reason
        is ReviewReason.DETECTED_NOT_RECOGNIZED
    )
    dup = ReviewItem(ReviewReason.LOW_OCR_CONFIDENCE, "text", 1, 0.1, "m")
    assert len(dedupe([dup, dup, dup])) == 1
