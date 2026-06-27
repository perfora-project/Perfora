"""Phase 0 DoD tests for the Session scaffolding, with no-op-ish dummy stages."""

from __future__ import annotations

from typing import Any

import numpy as np
from perfora.config import Config
from perfora.errors import PerforaError
from perfora.model.calibration import Calibration
from perfora.model.document import (
    LaneModel,
    NoteEvent,
    Provenance,
    ReviewItem,
    ReviewReason,
)
from perfora.pipeline.context import PipelineContext
from perfora.pipeline.preview import Overlay, StagePreview
from perfora.pipeline.session import Session
from perfora.pipeline.stages.base import InteractionField
from perfora.sources.base import RollImage


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeSource:
    """A Source that returns a tiny, fully-formed RollImage."""

    def __init__(self, name: str = "synthetic") -> None:
        self.name = name

    def to_roll_image(self) -> RollImage:
        gray = np.zeros((8, 6), dtype=np.uint8)
        cal = Calibration(mm_per_px_u=1.0, mm_per_px_v=1.0, source="assumed")
        prov = Provenance(
            source_type="image",
            source_name=self.name,
            perfora_version="0.1.0",
            created_utc="2026-06-27T00:00:00Z",
            params={},
        )
        return RollImage(gray=gray, calibration=cal, provenance=prov)


class LanesStage:
    name = "lanes"
    consumes = ("lane_pitch_mm",)
    produces = ("lane_model",)

    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts

    def run(self, ctx: PipelineContext) -> None:
        self.counts["lanes"] += 1
        pitch = ctx.overrides.lane_pitch_mm or 3.0
        ctx.lane_model = LaneModel(
            pitch_mm=pitch, v0_mm=0.0, n_lanes=5, confidence=1.0, method="comb-fit"
        )

    def preview(self, ctx: PipelineContext) -> StagePreview | None:
        pitch = ctx.lane_model.pitch_mm if ctx.lane_model else 0.0
        return StagePreview(
            base="gray",
            overlays=(Overlay(kind="lanes", data=[1, 2, 3]),),
            summary={"pitch_mm": pitch},
        )

    def interaction_points(self, ctx: PipelineContext) -> list[InteractionField]:
        current = ctx.lane_model.pitch_mm if ctx.lane_model else None
        return [
            InteractionField(
                key="lane_pitch_mm",
                type="float",
                label="Lane pitch (mm)",
                current=current,
                options=None,
                constraints={"min": 0.5, "max": 20.0},
            )
        ]


class NotesStage:
    name = "notes"
    consumes = ("note_edits",)
    produces = ("notes",)

    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts

    def run(self, ctx: PipelineContext) -> None:
        self.counts["notes"] += 1
        assert ctx.lane_model is not None
        pitch = ctx.lane_model.pitch_mm
        n_notes = 1 + len(ctx.overrides.note_edits)
        ctx.notes = [
            NoteEvent(
                lane=i,
                v_center_mm=float(i) * pitch,
                u_start_mm=0.0,
                u_end_mm=pitch,
                confidence=1.0,
            )
            for i in range(n_notes)
        ]

    def preview(self, ctx: PipelineContext) -> StagePreview | None:
        return StagePreview(base="gray", summary={"n_notes": len(ctx.notes)})

    def interaction_points(self, ctx: PipelineContext) -> list[InteractionField]:
        return []


class TextStage:
    name = "text"
    consumes = ("text_edits",)
    produces = ("texts",)

    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts

    def run(self, ctx: PipelineContext) -> None:
        self.counts["text"] += 1
        ctx.texts = []
        ctx.review.append(
            ReviewItem(
                reason=ReviewReason.UNCERTAIN_SCOPE,
                ref_kind="text",
                ref_id=0,
                confidence=0.4,
                message="placeholder review",
            )
        )

    def preview(self, ctx: PipelineContext) -> StagePreview | None:
        return None

    def interaction_points(self, ctx: PipelineContext) -> list[InteractionField]:
        return []


def make_session(**kwargs: Any) -> tuple[Session, dict[str, int]]:
    counts = {"lanes": 0, "notes": 0, "text": 0}
    stages = [LanesStage(counts), NotesStage(counts), TextStage(counts)]
    session = Session(FakeSource(), stages=stages, **kwargs)
    return session, counts


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_session_step_and_invalidate() -> None:
    session, counts = make_session()

    r0 = session.step()
    assert r0.stage == "lanes"
    assert session.cursor == 1
    session.step()
    session.step()
    assert session.cursor == 3
    assert counts == {"lanes": 1, "notes": 1, "text": 1}
    # the text stage queued one review item
    assert len(session.ctx.review) == 1

    # editing the lane pitch invalidates from "lanes" (it consumes lane_pitch_mm)
    session.apply_override(lane_pitch_mm=5.0)
    assert session.cursor == 0
    assert session.ctx.lane_model is None
    assert session.ctx.notes == []
    assert session.ctx.texts == []
    assert session.ctx.review == []  # downstream review items dropped

    session.run_all()
    assert session.ctx.lane_model is not None
    assert session.ctx.lane_model.pitch_mm == 5.0
    # all three re-ran exactly once more
    assert counts == {"lanes": 2, "notes": 2, "text": 2}


def test_rerun_from_recomputes_only_affected() -> None:
    session, counts = make_session()
    session.run_all()
    assert counts == {"lanes": 1, "notes": 1, "text": 1}

    # a note edit invalidates from "notes"; lanes must NOT recompute
    from perfora.pipeline.overrides import NoteEdit

    session.apply_override(note_edits=[NoteEdit(op="add", lane=9)])
    assert session.cursor == 1  # back to "notes"
    assert session.ctx.lane_model is not None  # lanes preserved

    session.rerun_from("notes")
    assert counts == {"lanes": 1, "notes": 2, "text": 2}
    assert len(session.ctx.notes) == 2  # base note + one added edit


def test_apply_override_unknown_key_raises() -> None:
    session, _ = make_session()
    try:
        session.apply_override(not_a_field=1)
    except PerforaError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected PerforaError for unknown override key")


def test_step_past_end_raises() -> None:
    session, _ = make_session()
    session.run_all()
    try:
        session.step()
    except PerforaError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected PerforaError stepping past the end")


def test_config_recorded_in_provenance() -> None:
    config = Config(min_note_len_mm=2.5)
    session, _ = make_session(config=config)
    doc = session.run_all()
    assert doc.provenance.params == config.to_params()
    assert doc.provenance.params["min_note_len_mm"] == 2.5
    assert doc.provenance.source_name == "synthetic"


def test_session_snapshot_restore() -> None:
    session, _ = make_session()
    session.run_to("notes")
    session.apply_override(lane_pitch_mm=7.0)
    session.run_all()
    snap = session.snapshot()
    assert snap["cursor"] == 3

    counts2 = {"lanes": 0, "notes": 0, "text": 0}
    fresh = [LanesStage(counts2), NotesStage(counts2), TextStage(counts2)]
    restored = Session.restore(snap, FakeSource(), stages=fresh)

    assert restored.cursor == session.cursor
    assert restored.ctx.lane_model is not None
    assert restored.ctx.lane_model.pitch_mm == 7.0
    assert len(restored.ctx.notes) == len(session.ctx.notes)
    # restore re-ran the full pipeline deterministically to the saved cursor
    assert counts2 == {"lanes": 1, "notes": 1, "text": 1}


def test_preview_and_interaction_points() -> None:
    session, _ = make_session()
    session.step()  # lanes
    prev = session.preview("lanes")
    assert prev is not None
    assert prev.summary["pitch_mm"] == 3.0
    fields = session.interaction_points("lanes")
    assert fields[0]["key"] == "lane_pitch_mm"
    # rasterize the preview without error
    raster = prev.rasterize(session.ctx.image)
    assert raster.shape == (8, 6, 3)
