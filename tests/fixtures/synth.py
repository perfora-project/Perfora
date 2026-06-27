"""Synthetic player-piano roll generator with ground truth.

Renders a roll image from a :class:`RollSpec` and returns both the BGR image and
the ground-truth :class:`~perfora.model.document.RollDocument`. This is the
backbone of deterministic testing for the lane-finder and note assembler — unit
tests recover the spec from the rendered image and compare to the ground truth.

Conventions (matching ``ALGORITHMS.md``)
----------------------------------------
* ``u`` = travel/length axis = image **rows** (vertical, the long axis).
* ``v`` = cross/width axis = image **columns** (horizontal, where lanes live).
* All spec quantities are millimetres; pixels are derived via ``dpi``.

The roll always carries hole-free side margins so the binarization auto-mode and
the page-quad deskew both have something clean to work with.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray
from perfora.model.calibration import Calibration
from perfora.model.document import (
    LaneModel,
    NoteEvent,
    Provenance,
    RollDocument,
)

# Per-regime (background, paper, hole) gray levels. Background only matters for
# page detection (it is cropped away); within the roll the holes are a brightness
# minority so the auto binarizer can pick the polarity.
_REGIMES = {
    "bright_holes": {"bg": 200, "paper": 90, "hole": 255},
    "dark_holes": {"bg": 60, "paper": 210, "hole": 30},
}


@dataclass
class RollSpec:
    """Ground-truth description of a synthetic roll.

    Notes default to an auto-generated, varied set spanning many lanes when
    ``notes`` is ``None``.
    """

    pitch_mm: float = 3.0
    n_lanes: int = 20
    roll_length_mm: float = 120.0
    margin_mm: float = 6.0
    dpi: float = 300.0
    notes: list[tuple[int, float, float]] | None = None  # (lane, u0_mm, u1_mm)
    skew_deg: float = 0.0
    noise: float = 0.0  # gaussian noise std in gray levels
    illumination: float = 0.0  # 0..1 linear brightness gradient strength
    regime: str = "bright_holes"  # or "dark_holes"
    hole_width_frac: float = 0.5  # slot width as a fraction of pitch
    chain: bool = False  # render notes as chains of round holes (for bridging)
    chain_hole_mm: float = 1.4
    chain_gap_mm: float = 0.8
    pad_frac: float = 0.12  # background border, as a fraction of the larger side
    seed: int = 0

    @property
    def v0_mm(self) -> float:
        """``v`` centre of lane 0, measured from the roll's left edge."""
        return self.margin_mm

    @property
    def roll_width_mm(self) -> float:
        """Full roll width: margins plus the lane span."""
        return 2.0 * self.margin_mm + (self.n_lanes - 1) * self.pitch_mm

    def lane_v_center_mm(self, lane: int) -> float:
        return self.v0_mm + lane * self.pitch_mm


def default_notes(spec: RollSpec) -> list[tuple[int, float, float]]:
    """A deterministic, varied note set covering most lanes."""
    notes: list[tuple[int, float, float]] = []
    usable = spec.roll_length_mm - 10.0
    for lane in range(spec.n_lanes):
        # stagger start and vary length so endpoints are distinguishable
        u0 = 5.0 + (lane % 5) * 4.0
        length = 8.0 + (lane % 4) * 6.0
        u1 = min(u0 + length, usable)
        notes.append((lane, u0, u1))
    return notes


def render(spec: RollSpec) -> tuple[NDArray[np.uint8], RollDocument]:
    """Render ``spec`` to ``(bgr_image, ground_truth_document)``."""
    rng = np.random.default_rng(spec.seed)
    ppmm = spec.dpi / 25.4
    colors = _REGIMES[spec.regime]

    roll_h = int(round(spec.roll_length_mm * ppmm))  # rows = u
    roll_w = int(round(spec.roll_width_mm * ppmm))  # cols = v
    patch = np.full((roll_h, roll_w), colors["paper"], dtype=np.float64)

    notes = spec.notes if spec.notes is not None else default_notes(spec)
    for lane, u0_mm, u1_mm in notes:
        _draw_note(patch, spec, lane, u0_mm, u1_mm, ppmm, float(colors["hole"]))

    if spec.illumination > 0:
        patch *= _illumination_gradient(roll_h, roll_w, spec.illumination)
    if spec.noise > 0:
        patch += rng.normal(0.0, spec.noise, patch.shape)
    patch = np.clip(patch, 0, 255)

    image = _embed_and_skew(patch.astype(np.uint8), spec, colors["bg"])
    bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

    doc = _ground_truth(spec, notes)
    return bgr.astype(np.uint8), doc


def _draw_note(
    patch: NDArray[np.float64],
    spec: RollSpec,
    lane: int,
    u0_mm: float,
    u1_mm: float,
    ppmm: float,
    hole_val: float,
) -> None:
    vc = int(round(spec.lane_v_center_mm(lane) * ppmm))
    u0 = int(round(u0_mm * ppmm))
    u1 = int(round(u1_mm * ppmm))
    if spec.chain:
        r = max(1, int(round(spec.chain_hole_mm * ppmm / 2.0)))
        step = max(1, int(round((spec.chain_hole_mm + spec.chain_gap_mm) * ppmm)))
        for row in range(u0 + r, u1 - r + 1, step):
            cv2.circle(patch, (vc, row), r, hole_val, -1)
    else:
        half_w = max(1, int(round(spec.pitch_mm * spec.hole_width_frac * ppmm / 2.0)))
        patch[u0:u1, vc - half_w : vc + half_w + 1] = hole_val


def _illumination_gradient(h: int, w: int, strength: float) -> NDArray[np.float64]:
    ramp = np.linspace(1.0 - strength, 1.0 + strength, w)
    return np.broadcast_to(ramp, (h, w)).copy()


def _embed_and_skew(
    patch: NDArray[np.uint8], spec: RollSpec, bg: int
) -> NDArray[np.uint8]:
    h, w = patch.shape
    pad = int(round(spec.pad_frac * max(h, w))) + 10
    canvas = np.full((h + 2 * pad, w + 2 * pad), bg, dtype=np.uint8)
    canvas[pad : pad + h, pad : pad + w] = patch
    if spec.skew_deg != 0.0:
        ch, cw = canvas.shape
        center = (cw / 2.0, ch / 2.0)
        rot = cv2.getRotationMatrix2D(center, spec.skew_deg, 1.0)
        canvas = cv2.warpAffine(
            canvas, rot, (cw, ch), flags=cv2.INTER_LINEAR, borderValue=float(bg)
        )
    return canvas


def _ground_truth(
    spec: RollSpec, notes: list[tuple[int, float, float]]
) -> RollDocument:
    mm_per_px = 25.4 / spec.dpi
    cal = Calibration(
        mm_per_px_u=mm_per_px, mm_per_px_v=mm_per_px, dpi=spec.dpi, source="dpi"
    )
    lane_model = LaneModel(
        pitch_mm=spec.pitch_mm,
        v0_mm=spec.v0_mm,
        n_lanes=spec.n_lanes,
        confidence=1.0,
        method="synthetic",
    )
    note_events = [
        NoteEvent(
            lane=lane,
            v_center_mm=spec.lane_v_center_mm(lane),
            u_start_mm=u0,
            u_end_mm=u1,
            confidence=1.0,
        )
        for lane, u0, u1 in notes
    ]
    prov = Provenance(
        source_type="image",
        source_name="synthetic",
        perfora_version="0.1.0",
        created_utc="2026-06-27T00:00:00Z",
        params={},
    )
    return RollDocument(
        provenance=prov,
        calibration=cal,
        lane_model=lane_model,
        notes=note_events,
        texts=[],
        review_queue=[],
    )
