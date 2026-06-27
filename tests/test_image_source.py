"""Tests for ImageSource and the imaging helpers it relies on.

Synthetic rolls via :func:`tests.fixtures.synth.render` provide ground truth
so we can measure deskew quality without needing real scans.

All spatial tolerances are deliberately loose (8-10 %) because the
perspective warp quantises to whole pixels and the pad-border edges may
not align exactly with the detected quad.
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray
from perfora.sources.image_source import ImageSource
from perfora.utils.imaging import order_corners

from tests.fixtures.synth import (
    RollSpec,  # noqa: E402
    render,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _ppmm(spec: RollSpec) -> float:
    """Pixels per mm for *spec*."""
    return spec.dpi / 25.4


def _roll_pixel_dims(spec: RollSpec) -> tuple[int, int, int]:
    """Return ``(roll_h_px, roll_w_px, pad_px)`` matching the synth renderer."""
    ppmm = _ppmm(spec)
    roll_h = int(round(spec.roll_length_mm * ppmm))
    roll_w = int(round(spec.roll_width_mm * ppmm))
    pad = int(round(spec.pad_frac * max(roll_h, roll_w))) + 10
    return roll_h, roll_w, pad


# --------------------------------------------------------------------------- #
# 1. Clean roll: DPI calibration, orientation, recovered width
# --------------------------------------------------------------------------- #


def test_clean_roll_dpi_calibration_and_width() -> None:
    """Clean roll: orientation, DPI calibration, and recovered width within 8 %."""
    spec = RollSpec()
    bgr, _gt = render(spec)

    img = ImageSource(bgr, dpi=spec.dpi).to_roll_image()

    assert img.gray.ndim == 2, "gray must be single-channel"
    h, w = img.gray.shape
    assert h >= w, f"rows (u) must be >= cols (v) after orientation; got {h}x{w}"

    # DPI calibration
    assert img.calibration.dpi == pytest.approx(spec.dpi, rel=1e-6)
    expected_mm = 25.4 / spec.dpi
    assert img.calibration.mm_per_px_u == pytest.approx(expected_mm, rel=1e-6)
    assert img.calibration.mm_per_px_v == pytest.approx(expected_mm, rel=1e-6)
    assert img.calibration.source == "dpi"

    # Recovered roll width in mm
    recovered_mm = w * img.calibration.mm_per_px_v
    expected_width = spec.roll_width_mm
    rel_err = abs(recovered_mm - expected_width) / expected_width
    assert rel_err < 0.08, (
        f"Recovered width {recovered_mm:.1f} mm differs from expected "
        f"{expected_width:.1f} mm by {rel_err*100:.1f}% (limit 8%)"
    )


# --------------------------------------------------------------------------- #
# 2. Skewed roll: deskew succeeds and recovered width within 10 %
# --------------------------------------------------------------------------- #


def test_skewed_roll_deskew() -> None:
    """3° skew is corrected; orientation correct and width within 10 %."""
    spec = RollSpec(skew_deg=3.0)
    bgr, _gt = render(spec)

    img = ImageSource(bgr, dpi=spec.dpi).to_roll_image()

    h, w = img.gray.shape
    assert h >= w, f"rows (u) must be >= cols (v) after deskew; got {h}x{w}"

    recovered_mm = w * img.calibration.mm_per_px_v
    expected_width = spec.roll_width_mm
    rel_err = abs(recovered_mm - expected_width) / expected_width
    assert rel_err < 0.10, (
        f"Skewed: recovered width {recovered_mm:.1f} mm differs from "
        f"{expected_width:.1f} mm by {rel_err*100:.1f}% (limit 10%)"
    )


# --------------------------------------------------------------------------- #
# 3. physical_width_mm calibration path
# --------------------------------------------------------------------------- #


def test_physical_width_calibration() -> None:
    """physical_width_mm path sets calibration.source and mm_per_px_v correctly."""
    spec = RollSpec()
    bgr, _gt = render(spec)
    W = spec.roll_width_mm

    img = ImageSource(bgr, physical_width_mm=W).to_roll_image()

    assert img.calibration.source == "physical_width"
    assert img.calibration.dpi is None

    final_w_px = img.gray.shape[1]
    expected_mm_per_px = W / final_w_px
    assert img.calibration.mm_per_px_v == pytest.approx(expected_mm_per_px, rel=1e-9)
    assert img.calibration.mm_per_px_u == pytest.approx(expected_mm_per_px, rel=1e-9)


# --------------------------------------------------------------------------- #
# 4. No calibration → source == "assumed", mm_per_px == 1.0
# --------------------------------------------------------------------------- #


def test_no_calibration_assumed() -> None:
    """No DPI or width → calibration source is 'assumed' and mm_per_px == 1.0."""
    spec = RollSpec()
    bgr, _gt = render(spec)

    img = ImageSource(bgr).to_roll_image()

    assert img.calibration.source == "assumed"
    assert img.calibration.dpi is None
    assert img.calibration.mm_per_px_u == pytest.approx(1.0)
    assert img.calibration.mm_per_px_v == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# 5. page_corners_px override — skips detection, uses supplied corners
# --------------------------------------------------------------------------- #


def test_page_corners_px_override() -> None:
    """Explicit page_corners_px skips detection and uses supplied corners."""
    spec = RollSpec()
    bgr, _gt = render(spec)

    roll_h, roll_w, pad = _roll_pixel_dims(spec)

    # Corners of the roll region in (x=col, y=row) pixel coords, any order
    # We supply them shuffled to confirm order_corners is applied internally.
    corners: list[tuple[float, float]] = [
        (float(pad + roll_w), float(pad + roll_h)),  # BR first (shuffled)
        (float(pad), float(pad)),                    # TL
        (float(pad + roll_w), float(pad)),           # TR
        (float(pad), float(pad + roll_h)),           # BL
    ]

    img = ImageSource(bgr, dpi=spec.dpi, page_corners_px=corners).to_roll_image()

    h, w = img.gray.shape
    assert h >= w, f"rows (u) must be >= cols (v); got {h}x{w}"
    assert img.gray.ndim == 2

    # Width should match expected roll width (tight crop since we gave exact corners)
    recovered_mm = w * img.calibration.mm_per_px_v
    expected_width = spec.roll_width_mm
    rel_err = abs(recovered_mm - expected_width) / expected_width
    assert rel_err < 0.02, (
        f"With exact corners: recovered width {recovered_mm:.1f} mm vs "
        f"{expected_width:.1f} mm, err {rel_err*100:.2f}% (limit 2%)"
    )


# --------------------------------------------------------------------------- #
# 6. order_corners unit test — correct TL/TR/BR/BL ordering
# --------------------------------------------------------------------------- #


def test_order_corners_canonical_ordering() -> None:
    """order_corners returns TL, TR, BR, BL for shuffled input."""
    # Rectangle: TL=(0,0), TR=(100,0), BR=(100,200), BL=(0,200) in (x,y)
    pts: NDArray[np.float32] = np.array(
        [[100.0, 200.0], [0.0, 0.0], [100.0, 0.0], [0.0, 200.0]],
        dtype=np.float32,
    )
    ordered = order_corners(pts)

    np.testing.assert_allclose(ordered[0], [0.0, 0.0], atol=1e-6)    # TL
    np.testing.assert_allclose(ordered[1], [100.0, 0.0], atol=1e-6)  # TR
    np.testing.assert_allclose(ordered[2], [100.0, 200.0], atol=1e-6)  # BR
    np.testing.assert_allclose(ordered[3], [0.0, 200.0], atol=1e-6)  # BL


def test_order_corners_non_axis_aligned() -> None:
    """order_corners handles a slightly tilted rectangle (non-axis-aligned)."""
    # A diamond-ish rectangle: TL≈(5,0), TR≈(105,5), BR≈(100,205), BL≈(0,200)
    pts: NDArray[np.float32] = np.array(
        [[100.0, 205.0], [5.0, 0.0], [105.0, 5.0], [0.0, 200.0]],
        dtype=np.float32,
    )
    ordered = order_corners(pts)

    # TL has smallest x+y sum
    sums = ordered[:, 0] + ordered[:, 1]
    assert sums[0] == sums.min(), "ordered[0] must be TL (min sum)"
    # BR has largest x+y sum
    assert sums[2] == sums.max(), "ordered[2] must be BR (max sum)"
    # TR has smallest y-x diff
    diffs = ordered[:, 1] - ordered[:, 0]
    assert diffs[1] == diffs.min(), "ordered[1] must be TR (min y-x)"
    # BL has largest y-x diff
    assert diffs[3] == diffs.max(), "ordered[3] must be BL (max y-x)"
