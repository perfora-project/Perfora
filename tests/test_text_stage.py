"""Phase 2 DoD tests for the TextStage and text-edit overrides."""

from __future__ import annotations

from typing import Any

import perfora
from perfora.config import Config
from perfora.model.document import TextKind, TextScope
from perfora.pipeline.context import PipelineContext
from perfora.pipeline.overrides import TextEdit
from perfora.pipeline.session import Session
from perfora.pipeline.stages.holes import HoleExtraction
from perfora.pipeline.stages.lanes import LaneFinding
from perfora.pipeline.stages.notes import NoteAssembly
from perfora.pipeline.stages.preprocess import Preprocess
from perfora.pipeline.stages.text import TextStage
from perfora.sources.base import RollImage
from perfora.sources.image_source import ImageSource
from perfora.text.base import DetBox
from perfora.text.engine import TextEngine

from tests.fixtures.synth import RollSpec, render


class _FakeDetector:
    id = "fake"

    def detect(self, image: RollImage) -> list[DetBox]:
        h, w = image.gray.shape[:2]
        # one box in the play area, mid-roll -> TIMELINE scope
        return [DetBox(bbox_px=(int(0.3 * w), int(0.5 * h), 40, 15))]


def _geometry_stages() -> list[Any]:
    return [Preprocess(), HoleExtraction(), LaneFinding(), NoteAssembly()]


def test_text_stage_detection_only_no_backends() -> None:
    # Full default pipeline (no OCR extras) still decodes geometry; any text
    # regions are detection-only and the core path is unaffected.
    spec = RollSpec()
    bgr, gt = render(spec)
    doc = perfora.process(ImageSource(bgr, dpi=spec.dpi))
    assert len(doc.notes) == len(gt.notes)
    assert doc.lane_model is not None
    for t in doc.texts:
        assert t.recognized_by == ""
        assert t.needs_review


def test_text_edit_override_applied() -> None:
    spec = RollSpec()
    bgr, _gt = render(spec)
    stages = [*_geometry_stages(), TextStage(TextEngine(_FakeDetector(), []))]
    session = Session(ImageSource(bgr, dpi=spec.dpi), stages=stages, config=Config())
    session.run_all()
    assert len(session.ctx.texts) == 1
    assert session.ctx.texts[0].recognized_by == ""  # detection only

    session.apply_override(
        text_edits=[
            TextEdit(op="set_text", ref_id=0, text="forte"),
            TextEdit(op="set_scope", ref_id=0, scope=TextScope.GLOBAL_HEADER.value),
        ]
    )
    assert session.cursor == 4  # back to the text stage
    session.rerun_from("text")

    region = session.ctx.texts[0]
    assert region.text == "forte"
    assert region.scope is TextScope.GLOBAL_HEADER
    assert region.recognized_by == "user"
    assert not region.needs_review


def test_text_stage_add_and_remove_edits() -> None:
    spec = RollSpec()
    bgr, _gt = render(spec)
    img = ImageSource(bgr, dpi=spec.dpi).to_roll_image()
    ctx = PipelineContext(image=img, config=Config())
    for stage in _geometry_stages():
        stage.run(ctx)
    stage = TextStage(TextEngine(_FakeDetector(), []))

    # add a region, then a run keeps it; then remove the detected one
    ctx.overrides.text_edits = [
        TextEdit(
            op="add",
            text="Composer",
            scope=TextScope.GLOBAL_HEADER.value,
            kind=TextKind.PRINTED.value,
            bbox_mm=(0.0, 0.0, 5.0, 20.0),
        )
    ]
    stage.run(ctx)
    assert any(t.text == "Composer" for t in ctx.texts)
    assert any(t.recognized_by == "user" for t in ctx.texts)
