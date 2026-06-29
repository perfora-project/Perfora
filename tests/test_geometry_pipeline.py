"""Phase 1 DoD tests: the geometry core on synthetic ground truth."""

from __future__ import annotations

import perfora
from perfora.config import Config
from perfora.pipeline.session import Session
from perfora.sources.image_source import ImageSource

from tests.fixtures.synth import RollSpec, render


def _match_notes(recovered: list, gt: list, tol_mm: float = 1.0) -> int:
    """Count recovered notes matching a GT note (exact lane, u within tol)."""
    matched = 0
    for g in gt:
        for n in recovered:
            if (
                n.lane == g.lane
                and abs(n.u_start_mm - g.u_start_mm) < tol_mm
                and abs(n.u_end_mm - g.u_end_mm) < tol_mm
            ):
                matched += 1
                break
    return matched


def test_end_to_end_synth_image() -> None:
    spec = RollSpec()
    bgr, gt = render(spec)
    doc = perfora.process(ImageSource(bgr, dpi=spec.dpi))

    # pitch within 1%
    err = abs(doc.lane_model.pitch_mm - spec.pitch_mm) / spec.pitch_mm
    assert err < 0.01, f"pitch error {err:.3%}"
    # all GT notes matched, and no spurious notes
    assert _match_notes(doc.notes, gt.notes) == len(gt.notes)
    assert len(doc.notes) == len(gt.notes)


def test_lane_assignment_clean() -> None:
    spec = RollSpec()
    bgr, gt = render(spec)
    doc = perfora.process(ImageSource(bgr, dpi=spec.dpi))
    assert doc.lane_model.n_lanes == spec.n_lanes
    # every recovered note's lane matches a GT note at the same u-range
    assert _match_notes(doc.notes, gt.notes) == len(gt.notes)


def test_lane_assignment_skewed() -> None:
    spec = RollSpec(skew_deg=3.0, noise=4.0)
    bgr, gt = render(spec)
    doc = perfora.process(ImageSource(bgr, dpi=spec.dpi))
    err = abs(doc.lane_model.pitch_mm - spec.pitch_mm) / spec.pitch_mm
    assert err < 0.02, f"pitch error {err:.3%}"
    matched = _match_notes(doc.notes, gt.notes)
    assert matched >= 0.98 * len(gt.notes), f"only {matched}/{len(gt.notes)}"


def test_note_assembly_bridging() -> None:
    # chain-perforated rolls merge their tight runs into one note WHEN a
    # bridge gap is configured for them (the default is conservative)
    spec = RollSpec(chain=True, n_lanes=8)
    bgr, gt = render(spec)
    cfg = Config(bridge_gap_mm=1.5)
    doc = perfora.process(ImageSource(bgr, dpi=spec.dpi, config=cfg), config=cfg)
    assert len(doc.notes) == len(gt.notes)  # one note per lane, not fragments
    assert _match_notes(doc.notes, gt.notes, tol_mm=2.5) == len(gt.notes)


def test_distinct_notes_not_over_merged() -> None:
    # with the conservative default, two perforations in a lane separated by a
    # clear gap stay as two notes (other lanes give the pitch its periodicity)
    notes = [(lane, 10.0, 20.0) for lane in range(8)]
    notes.append((3, 24.0, 34.0))  # second note in lane 3, 4 mm after the first
    spec = RollSpec(n_lanes=8, notes=notes)
    bgr, _gt = render(spec)
    doc = perfora.process(ImageSource(bgr, dpi=spec.dpi))
    lane3 = [n for n in doc.notes if n.lane == 3]
    assert len(lane3) == 2


def test_calibration_dpi_vs_physical_width() -> None:
    spec = RollSpec()
    bgr, _gt = render(spec)

    by_dpi = ImageSource(bgr, dpi=spec.dpi).to_roll_image()
    assert by_dpi.calibration.source == "dpi"

    by_width = ImageSource(
        bgr, physical_width_mm=spec.roll_width_mm
    ).to_roll_image()
    assert by_width.calibration.source == "physical_width"
    # both calibrations imply nearly the same physical roll width
    w_dpi = by_dpi.gray.shape[1] * by_dpi.calibration.mm_per_px_v
    w_width = by_width.gray.shape[1] * by_width.calibration.mm_per_px_v
    assert abs(w_width - spec.roll_width_mm) < 0.5
    assert abs(w_dpi - w_width) / spec.roll_width_mm < 0.05


def test_override_pitch_changes_assignment() -> None:
    spec = RollSpec()
    bgr, _gt = render(spec)
    session = Session(ImageSource(bgr, dpi=spec.dpi), config=Config())
    session.run_all()
    base_pitch = session.ctx.lane_model.pitch_mm
    base_n_lanes = session.ctx.lane_model.n_lanes
    assert abs(base_pitch - spec.pitch_mm) / spec.pitch_mm < 0.01

    # force double the pitch: assignment must change deterministically
    forced = 2.0 * spec.pitch_mm
    session.apply_override(lane_pitch_mm=forced)
    # downstream invalidated: lane model + notes reset, mask/holes preserved
    assert session.ctx.lane_model is None
    assert session.ctx.notes == []
    assert session.ctx.mask is not None
    assert session.ctx.holes

    session.rerun_from("lanes")
    assert abs(session.ctx.lane_model.pitch_mm - forced) < 1e-6
    assert session.ctx.lane_model.method == "override"
    assert session.ctx.lane_model.n_lanes < base_n_lanes


def test_rerun_from_lanes_scope() -> None:
    spec = RollSpec()
    bgr, _gt = render(spec)
    session = Session(ImageSource(bgr, dpi=spec.dpi), config=Config())
    session.run_all()
    mask_before = session.ctx.mask
    holes_before = session.ctx.holes

    session.invalidate_from("lanes")
    # lanes is stage index 2 (preprocess, holes, lanes, notes)
    assert session.cursor == 2
    assert session.ctx.lane_model is None
    assert session.ctx.notes == []
    # preprocess/holes results untouched (same objects)
    assert session.ctx.mask is mask_before
    assert session.ctx.holes is holes_before

    session.rerun_from("lanes")
    assert session.ctx.lane_model is not None
    assert len(session.ctx.notes) > 0


def test_stage_previews_rasterize() -> None:
    spec = RollSpec()
    bgr, _gt = render(spec)
    session = Session(ImageSource(bgr, dpi=spec.dpi), config=Config())
    session.run_all()
    for stage in ("preprocess", "holes", "lanes", "notes"):
        prev = session.preview(stage)
        assert prev is not None
        raster = prev.rasterize(session.ctx.image)
        assert raster.ndim == 3 and raster.shape[2] == 3
