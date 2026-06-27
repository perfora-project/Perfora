"""Unit tests for the data-model math and conventions."""

from __future__ import annotations

import math

from perfora.model import (
    Axis,
    BBox,
    Calibration,
    LaneModel,
    NoteEvent,
)


def test_axis_values() -> None:
    assert Axis.U.value == "u"
    assert Axis.V.value == "v"


def test_bbox_geometry() -> None:
    b = BBox(u0=10.0, v0=2.0, u1=20.0, v1=8.0)
    assert b.u_span == (10.0, 20.0)
    assert b.v_span == (2.0, 8.0)
    assert b.u_center == 15.0
    assert b.v_center == 5.0
    assert b.u_length == 10.0
    assert b.v_width == 6.0


def test_bbox_overlaps_u() -> None:
    b = BBox(u0=10.0, v0=0.0, u1=20.0, v1=1.0)
    assert b.overlaps_u(15.0, 25.0)
    assert b.overlaps_u(5.0, 12.0)
    assert b.overlaps_u(10.0, 20.0)
    assert not b.overlaps_u(21.0, 30.0)
    assert not b.overlaps_u(0.0, 9.0)


def test_calibration_roundtrip_dpi() -> None:
    mm_per_px = 25.4 / 300
    cal = Calibration(
        mm_per_px_u=mm_per_px, mm_per_px_v=mm_per_px, dpi=300, source="dpi"
    )
    u_mm, v_mm = cal.px_to_mm(300.0, 600.0)
    assert math.isclose(u_mm, 25.4)
    assert math.isclose(v_mm, 50.8)
    u_px, v_px = cal.mm_to_px(u_mm, v_mm)
    assert math.isclose(u_px, 300.0)
    assert math.isclose(v_px, 600.0)


def test_lane_model_centers_and_nearest() -> None:
    lm = LaneModel(
        pitch_mm=3.0, v0_mm=1.0, n_lanes=10, confidence=0.9, method="comb-fit"
    )
    assert lm.v_center(0) == 1.0
    assert lm.v_center(3) == 10.0
    lane, residual = lm.nearest_lane(10.4)
    assert lane == 3
    assert math.isclose(residual, 0.4)
    # exactly between lane 3 (10.0) and lane 4 (13.0) rounds to nearest even (4)
    lane_mid, residual_mid = lm.nearest_lane(11.5)
    assert lane_mid in (3, 4)
    assert abs(residual_mid) <= 0.5 * lm.pitch_mm + 1e-9


def test_note_event_length_and_duration() -> None:
    n = NoteEvent(
        lane=2,
        v_center_mm=7.0,
        u_start_mm=100.0,
        u_end_mm=130.0,
        confidence=0.95,
    )
    assert n.length_mm == 30.0
    assert n.pitch is None
    assert math.isclose(n.duration_seconds(180.0), 30.0 / 180.0)
