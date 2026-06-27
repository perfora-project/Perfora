"""Tests for the Preprocess and HoleExtraction pipeline stages.

RollImages are constructed directly — no ImageSource dependency.
All synthetic images use a 200×60 uint8 array with:
  - paper value 90 (bright) or 200 (dark)
  - three 10×(≥30 px) slots with hole value 255 or 30
  - mm_per_px = 0.1 → area of each slot ≥ 2 mm²  (> min_hole_area_mm2 = 0.5)
"""

from __future__ import annotations

import numpy as np
import pytest
from perfora.config import Config
from perfora.errors import PerforaError
from perfora.model.calibration import Calibration
from perfora.model.document import Provenance
from perfora.pipeline.context import PipelineContext
from perfora.pipeline.stages.holes import HoleExtraction
from perfora.pipeline.stages.preprocess import Preprocess, binarize
from perfora.sources.base import RollImage

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_PROV = Provenance(
    source_type="image",
    source_name="test",
    perfora_version="0.1.0",
    created_utc="2026-06-27T00:00:00Z",
    params={},
)

_CAL_01 = Calibration(mm_per_px_u=0.1, mm_per_px_v=0.1, dpi=254, source="dpi")

# Three non-overlapping slots: (row_start, col_start, row_end, col_end)
# Each is 10 px wide × ≥30 px tall → area ≥ 300 px → ≥ 3 mm² at 0.1 mm/px.
_SLOTS = [
    (20, 5, 50, 15),    # 10 wide × 30 tall = 300 px
    (80, 25, 120, 35),  # 10 wide × 40 tall = 400 px
    (150, 45, 180, 55), # 10 wide × 30 tall = 300 px
]


def _bright_holes_gray() -> np.ndarray:
    """200×60 image: paper=90, holes=255."""
    gray = np.full((200, 60), 90, dtype=np.uint8)
    for r0, c0, r1, c1 in _SLOTS:
        gray[r0:r1, c0:c1] = 255
    return gray


def _dark_holes_gray() -> np.ndarray:
    """200×60 image: paper=200, holes=30."""
    gray = np.full((200, 60), 200, dtype=np.uint8)
    for r0, c0, r1, c1 in _SLOTS:
        gray[r0:r1, c0:c1] = 30
    return gray


def _make_ctx(gray: np.ndarray) -> PipelineContext:
    img = RollImage(gray=gray, calibration=_CAL_01, provenance=_PROV)
    return PipelineContext(image=img, config=Config())


# ---------------------------------------------------------------------------
# Test 1: binarize auto → bright minority → bright holes are True
# ---------------------------------------------------------------------------


def test_binarize_auto_bright_holes_minority() -> None:
    """auto mode with a bright-minority image picks bright_holes polarity."""
    gray = _bright_holes_gray()
    mask = binarize(gray, "auto", speckle_min_area_px=9, opening_kernel_px=3)

    assert mask.dtype == np.bool_
    assert mask.shape == gray.shape

    frac = float(mask.mean())
    # holes are minority: fraction should be well under 50 %
    assert 0.0 < frac < 0.5

    # Each slot should be predominantly True in the mask
    for r0, c0, r1, c1 in _SLOTS:
        slot_true = float(mask[r0:r1, c0:c1].mean())
        assert slot_true > 0.5, (
            f"Slot ({r0},{c0})-({r1},{c1}) not mostly True (mean={slot_true:.3f})"
        )


# ---------------------------------------------------------------------------
# Test 2: binarize auto → dark minority → dark holes are True
# ---------------------------------------------------------------------------


def test_binarize_auto_dark_holes_minority() -> None:
    """auto mode with a dark-minority image picks dark_holes polarity."""
    gray = _dark_holes_gray()
    mask = binarize(gray, "auto", speckle_min_area_px=9, opening_kernel_px=3)

    assert mask.dtype == np.bool_
    assert mask.shape == gray.shape

    frac = float(mask.mean())
    assert 0.0 < frac < 0.5

    for r0, c0, r1, c1 in _SLOTS:
        slot_true = float(mask[r0:r1, c0:c1].mean())
        assert slot_true > 0.5, (
            f"Slot ({r0},{c0})-({r1},{c1}) not mostly True (mean={slot_true:.3f})"
        )


# ---------------------------------------------------------------------------
# Test 3: Preprocess.run / preview / interaction_points
# ---------------------------------------------------------------------------


def test_preprocess_run_sets_mask_and_shape() -> None:
    """Preprocess.run sets ctx.mask to a bool array with the same HxW as gray."""
    gray = _bright_holes_gray()
    ctx = _make_ctx(gray)

    stage = Preprocess()
    assert stage.name == "preprocess"

    stage.run(ctx)

    assert ctx.mask is not None
    assert ctx.mask.dtype == np.bool_
    assert ctx.mask.shape == gray.shape


def test_preprocess_preview_fields() -> None:
    """Preprocess.preview returns a StagePreview with the expected summary."""
    gray = _bright_holes_gray()
    ctx = _make_ctx(gray)
    Preprocess().run(ctx)

    prev = Preprocess().preview(ctx)
    assert prev is not None
    assert prev.base == "mask"
    assert "hole_fraction" in prev.summary
    assert "mode" in prev.summary
    assert isinstance(prev.summary["hole_fraction"], float)
    assert isinstance(prev.summary["mode"], str)


def test_preprocess_interaction_points_four_modes() -> None:
    """interaction_points lists exactly the four valid binarization modes."""
    gray = _bright_holes_gray()
    ctx = _make_ctx(gray)

    points = Preprocess().interaction_points(ctx)
    assert len(points) == 1

    p = points[0]
    assert p["key"] == "binarization_mode"
    assert p["type"] == "enum"
    assert p["constraints"] is None
    assert p["options"] is not None
    assert set(p["options"]) == {"auto", "bright_holes", "dark_holes", "adaptive"}


# ---------------------------------------------------------------------------
# Test 4: HoleExtraction finds the three slots; 1-px speckle is rejected
# ---------------------------------------------------------------------------


def test_hole_extraction_finds_slots_and_rejects_speckle() -> None:
    """HoleExtraction finds ~3 large holes; a 1-px speckle is filtered out."""
    gray = _bright_holes_gray()
    # Add a single-pixel speckle that must be rejected (area too small).
    gray[100, 0] = 255

    ctx = _make_ctx(gray)
    Preprocess().run(ctx)
    HoleExtraction().run(ctx)

    n_found = len(ctx.holes)
    n_expected = len(_SLOTS)
    assert abs(n_found - n_expected) <= 1, (
        f"Expected ~{n_expected} holes, found {n_found}"
    )

    for h in ctx.holes:
        u_min, v_min, u_max, v_max = h.bbox_px
        u_c, v_c = h.centroid_px

        # centroid must lie inside the bounding box
        assert u_min <= u_c <= u_max, f"centroid u={u_c} outside bbox [{u_min},{u_max}]"
        assert v_min <= v_c <= v_max, f"centroid v={v_c} outside bbox [{v_min},{v_max}]"

        # area must be positive and within config bounds
        assert h.area_px > 0.0
        area_mm2 = h.area_px * _CAL_01.mm_per_px_u * _CAL_01.mm_per_px_v
        cfg = Config()
        assert area_mm2 >= cfg.min_hole_area_mm2, (
            f"area_mm2={area_mm2} below min {cfg.min_hole_area_mm2}"
        )
        assert area_mm2 <= cfg.max_hole_area_mm2, (
            f"area_mm2={area_mm2} above max {cfg.max_hole_area_mm2}"
        )


# ---------------------------------------------------------------------------
# Test 5: HoleExtraction raises PerforaError when mask is None
# ---------------------------------------------------------------------------


def test_hole_extraction_raises_without_mask() -> None:
    """HoleExtraction.run raises PerforaError when ctx.mask is None."""
    gray = _bright_holes_gray()
    ctx = _make_ctx(gray)
    assert ctx.mask is None  # Preprocess has not run

    with pytest.raises(PerforaError):
        HoleExtraction().run(ctx)


# ---------------------------------------------------------------------------
# Test 6: preview boxes overlay has exactly one box per hole
# ---------------------------------------------------------------------------


def test_hole_extraction_preview_boxes_match_holes() -> None:
    """HoleExtraction.preview contains one (x,y,w,h) box per detected hole."""
    gray = _bright_holes_gray()
    ctx = _make_ctx(gray)
    Preprocess().run(ctx)
    HoleExtraction().run(ctx)

    prev = HoleExtraction().preview(ctx)
    assert prev.base == "mask"
    assert len(prev.overlays) == 1

    overlay = prev.overlays[0]
    assert overlay.kind == "boxes"

    boxes = list(overlay.data)  # type: ignore[call-overload]
    assert len(boxes) == len(ctx.holes), (
        f"Expected {len(ctx.holes)} boxes, got {len(boxes)}"
    )

    # Verify each box maps to its hole with the correct (x=v_min, y=u_min, w, h)
    for i, (x, y, w, h) in enumerate(boxes):
        hole = ctx.holes[i]
        u_min, v_min, u_max, v_max = hole.bbox_px
        assert x == v_min, f"box[{i}] x={x} != v_min={v_min}"
        assert y == u_min, f"box[{i}] y={y} != u_min={u_min}"
        assert w == v_max - v_min, f"box[{i}] w={w} != {v_max - v_min}"
        assert h == u_max - u_min, f"box[{i}] h={h} != {u_max - u_min}"
