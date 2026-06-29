"""Regression: oversized scans are downscaled before warping (no remap crash).

OpenCV's ``warpPerspective`` asserts every image dimension is < 32767. Real
high-resolution roll scans (e.g. a 720 MB JP2) exceed that and used to crash in
``four_point_warp``. ImageSource now caps the working resolution at
``Config.max_image_px`` and folds the downscale factor into the calibration so
millimetre geometry is unchanged.
"""

from __future__ import annotations

import perfora
from perfora.config import Config
from perfora.sources.image_source import ImageSource

from tests.fixtures.synth import RollSpec, render


def test_oversized_scan_is_downscaled_and_mm_preserved() -> None:
    spec = RollSpec(dpi=600.0)  # a larger render (~3500 x 2330 px)
    bgr, _gt = render(spec)
    # cap well below the native size to force the downscale path
    cfg = Config(max_image_px=1400)

    img = ImageSource(bgr, dpi=spec.dpi, config=cfg).to_roll_image()
    assert max(img.gray.shape[:2]) <= cfg.max_image_px

    # calibration is adjusted: physical roll width is preserved despite shrink
    width_mm = img.gray.shape[1] * img.calibration.mm_per_px_v
    assert abs(width_mm - spec.roll_width_mm) / spec.roll_width_mm < 0.05

    # and the full decode still measures the true pitch / lane count
    doc = perfora.process(ImageSource(bgr, dpi=spec.dpi, config=cfg), config=cfg)
    assert abs(doc.lane_model.pitch_mm - spec.pitch_mm) / spec.pitch_mm < 0.01
    assert doc.lane_model.n_lanes == spec.n_lanes


def test_small_image_not_downscaled() -> None:
    spec = RollSpec()
    bgr, _gt = render(spec)
    big_cap = Config(max_image_px=100000)
    img = ImageSource(bgr, dpi=spec.dpi, config=big_cap).to_roll_image()
    # unchanged calibration (dpi path) when no downscale happens
    assert abs(img.calibration.dpi - spec.dpi) < 1e-6
