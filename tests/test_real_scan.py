"""Tests for real-scan handling: background-keyed segmentation, bed-through and
dark holes, cone leader, and residual-skew drift on long rolls."""

from __future__ import annotations

import numpy as np
import perfora
from perfora.sources.image_source import ImageSource
from perfora.utils.imaging import (
    background_color,
    deskew_angle_from_region,
    foreground_mask,
    largest_filled_region,
)

from tests.fixtures.synth import RollSpec, render_realistic


def _match(recovered: list, gt: list, tol_mm: float = 2.0) -> int:
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


def test_realistic_clean_roll_with_cone() -> None:
    spec = RollSpec(cone_leader_mm=25.0, n_lanes=20, noise=4.0)
    bgr, gt = render_realistic(spec)
    img = ImageSource(bgr, dpi=spec.dpi).to_roll_image()
    assert img.roll_mask is not None  # roll was isolated by background-keying

    doc = perfora.process(ImageSource(bgr, dpi=spec.dpi))
    assert abs(doc.lane_model.pitch_mm - spec.pitch_mm) / spec.pitch_mm < 0.01
    assert _match(doc.notes, gt.notes) == len(gt.notes)
    # the white cone corners must NOT become spurious holes/notes
    assert len(doc.notes) <= len(gt.notes) + 1


def test_realistic_dark_holes() -> None:
    # dark background -> perforations show dark; the "hole = background-coloured
    # inside the roll" rule must handle this too
    spec = RollSpec(
        cone_leader_mm=20.0,
        n_lanes=18,
        noise=4.0,
        background_bgr=(30, 30, 30),
        material_bgr=(180, 130, 90),
    )
    bgr, gt = render_realistic(spec)
    doc = perfora.process(ImageSource(bgr, dpi=spec.dpi))
    assert abs(doc.lane_model.pitch_mm - spec.pitch_mm) / spec.pitch_mm < 0.02
    assert _match(doc.notes, gt.notes) >= 0.98 * len(gt.notes)


def test_realistic_long_skewed_roll() -> None:
    # a long roll with skew: residual after the coarse deskew is mopped up by the
    # lane-stage skew refinement, so end-of-roll notes stay in the right lane
    nlan = 20
    # notes span the full body length (below the cone) so end-of-roll drift is
    # what is being tested
    notes = [(i % nlan, 40.0 + i * 6.0, 44.0 + i * 6.0) for i in range(38)]
    spec = RollSpec(
        cone_leader_mm=25.0,
        n_lanes=nlan,
        roll_length_mm=290.0,
        dpi=300.0,
        skew_deg=2.5,
        noise=4.0,
        notes=notes,
    )
    bgr, gt = render_realistic(spec)
    doc = perfora.process(ImageSource(bgr, dpi=spec.dpi))
    assert abs(doc.lane_model.pitch_mm - spec.pitch_mm) / spec.pitch_mm < 0.02
    assert _match(doc.notes, gt.notes) >= len(gt.notes) - 1


def test_segmentation_isolates_colored_roll_on_white() -> None:
    spec = RollSpec(cone_leader_mm=25.0, n_lanes=16)
    bgr, _gt = render_realistic(spec)
    bg = background_color(bgr)
    assert np.allclose(bg, [255, 255, 255], atol=5)  # white background detected
    region = largest_filled_region(foreground_mask(bgr, bg))
    # the roll occupies a sensible chunk of the frame and is the single blob
    assert 0.3 < region.mean() < 0.95


def test_deskew_angle_recovers_known_skew() -> None:
    spec = RollSpec(cone_leader_mm=25.0, n_lanes=16, skew_deg=2.0)
    bgr, _gt = render_realistic(spec)
    region = largest_filled_region(foreground_mask(bgr, background_color(bgr)))
    angle = deskew_angle_from_region(region)
    assert abs(angle - 2.0) < 0.5  # measured skew is close to the applied 2 deg
