"""Phase 3 DoD tests: slit-scan video reconstruction on synthetic clips."""

from __future__ import annotations

import perfora
from perfora.config import Config
from perfora.sources.image_source import ImageSource
from perfora.sources.video_source import VideoSource, reconstruct

from tests.fixtures.synth import RollSpec, synth_video


def _light() -> RollSpec:
    # smaller/faster than the default so phaseCorrelate over frames stays quick
    return RollSpec(dpi=150.0, roll_length_mm=80.0, n_lanes=12)


def _match(recovered: list, gt: list, tol_mm: float = 1.5) -> int:
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


def test_video_reconstruction_matches_flat() -> None:
    spec = _light()
    frames, flat_bgr, gt = synth_video(spec, base_speed_px=1.0)
    doc_flat = perfora.process(ImageSource(flat_bgr, dpi=spec.dpi))
    doc_vid = perfora.process(VideoSource(frames, dpi=spec.dpi))

    # same lane geometry
    assert doc_vid.lane_model.n_lanes == doc_flat.lane_model.n_lanes
    pitch_err = abs(doc_vid.lane_model.pitch_mm - doc_flat.lane_model.pitch_mm)
    assert pitch_err / doc_flat.lane_model.pitch_mm < 0.02
    # all GT notes recovered from the reconstructed strip, no ghosting blow-up
    assert _match(doc_vid.notes, gt.notes) == len(gt.notes)
    assert len(doc_vid.notes) <= len(gt.notes) + 2


def test_variable_speed_no_u_distortion() -> None:
    spec = _light()
    frames, _flat, gt = synth_video(
        spec, base_speed_px=1.2, speed_jitter=0.6, seed=3
    )
    doc = perfora.process(VideoSource(frames, dpi=spec.dpi))
    # variable feed speed must not distort the u scale: pitch stays correct and
    # note u-extents still match ground truth
    assert abs(doc.lane_model.pitch_mm - spec.pitch_mm) / spec.pitch_mm < 0.02
    assert _match(doc.notes, gt.notes) >= 0.98 * len(gt.notes)


def test_lateral_wobble_corrected() -> None:
    spec = _light()
    frames, _flat, gt = synth_video(spec, base_speed_px=1.0, wobble_px=3.0)
    doc = perfora.process(VideoSource(frames, dpi=spec.dpi))
    assert abs(doc.lane_model.pitch_mm - spec.pitch_mm) / spec.pitch_mm < 0.03
    assert _match(doc.notes, gt.notes) >= 0.98 * len(gt.notes)


class _CancelAfter:
    """Progress reporter that requests cancellation after ``k`` frames."""

    def __init__(self, k: int) -> None:
        self.k = k
        self.done = 0

    def on_stage_start(self, stage: str, total: int | None = None) -> None:
        return None

    def on_progress(self, stage: str, done: int, total: int) -> None:
        self.done = done

    def on_stage_end(self, stage: str, result: object) -> None:
        return None

    def cancelled(self) -> bool:
        return self.done >= self.k


def test_video_cancellation() -> None:
    spec = _light()
    frames, _flat, _gt = synth_video(spec, base_speed_px=1.0)
    full = reconstruct(frames, roi=None, travel="auto", config=Config())
    partial = reconstruct(
        frames,
        roi=None,
        travel="auto",
        config=Config(),
        progress=_CancelAfter(50),
    )
    # cancellation stops reconstruction cleanly and early
    assert partial.shape[0] < full.shape[0]
    assert partial.shape[1] == full.shape[1]
