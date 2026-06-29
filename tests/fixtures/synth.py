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
    # realistic (render_realistic) options: a coloured roll on a plain
    # background, with a narrowing leader and bed-through holes.
    cone_leader_mm: float = 0.0  # length of the narrowing top leader (0 = none)
    cone_top_frac: float = 0.12  # leader top width as a fraction of full width
    material_bgr: tuple[int, int, int] = (40, 40, 190)  # roll colour (reddish)
    background_bgr: tuple[int, int, int] = (255, 255, 255)  # scanner bed/background

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


def _roll_patch(
    spec: RollSpec,
    notes: list[tuple[int, float, float]],
    rng: np.random.Generator,
) -> NDArray[np.uint8]:
    """Build the bare roll content (paper + holes + noise), no background."""
    ppmm = spec.dpi / 25.4
    colors = _REGIMES[spec.regime]
    roll_h = int(round(spec.roll_length_mm * ppmm))  # rows = u
    roll_w = int(round(spec.roll_width_mm * ppmm))  # cols = v
    patch = np.full((roll_h, roll_w), colors["paper"], dtype=np.float64)
    for lane, u0_mm, u1_mm in notes:
        _draw_note(patch, spec, lane, u0_mm, u1_mm, ppmm, float(colors["hole"]))
    if spec.illumination > 0:
        patch *= _illumination_gradient(roll_h, roll_w, spec.illumination)
    if spec.noise > 0:
        patch += rng.normal(0.0, spec.noise, patch.shape)
    return np.clip(patch, 0, 255).astype(np.uint8)


def render(spec: RollSpec) -> tuple[NDArray[np.uint8], RollDocument]:
    """Render ``spec`` to ``(bgr_image, ground_truth_document)``."""
    rng = np.random.default_rng(spec.seed)
    colors = _REGIMES[spec.regime]
    notes = spec.notes if spec.notes is not None else default_notes(spec)
    patch = _roll_patch(spec, notes, rng)
    image = _embed_and_skew(patch, spec, colors["bg"])
    bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    doc = _ground_truth(spec, notes)
    return bgr.astype(np.uint8), doc


def synth_video(
    spec: RollSpec,
    *,
    window_frac: float = 0.25,
    base_speed_px: float = 1.0,
    speed_jitter: float = 0.0,
    wobble_px: float = 0.0,
    seed: int = 0,
) -> tuple[list[NDArray[np.uint8]], NDArray[np.uint8], RollDocument]:
    """Scroll a known roll past a virtual camera; return frames + flat + GT.

    The roll content scrolls vertically (``u``) through a fixed camera window;
    the centre row of the window is the slit a slit-scan reconstructor samples.

    Parameters
    ----------
    spec : RollSpec
        The roll to film.
    window_frac : float
        Camera window height as a fraction of the roll length.
    base_speed_px : float
        Nominal per-frame vertical advance in pixels.
    speed_jitter : float
        Uniform +/- jitter on the per-frame advance (fraction of base speed).
    wobble_px : float
        Amplitude of sinusoidal lateral (``v``) wobble, in pixels.
    seed : int
        RNG seed for jitter.

    Returns
    -------
    (frames, flat_bgr, ground_truth)
        ``frames`` is a list of BGR frames; ``flat_bgr`` is the equivalent flat
        scan (``render``); ``ground_truth`` is the shared GT document.
    """
    rng = np.random.default_rng(spec.seed)
    notes = spec.notes if spec.notes is not None else default_notes(spec)
    patch = _roll_patch(spec, notes, rng)
    bg = _REGIMES[spec.regime]["bg"]
    h, w = patch.shape

    wh = max(8, int(round(window_frac * h)))
    pad = wh  # paper pad so the slit can sweep the full content
    padded = np.full((h + 2 * pad, w), bg, dtype=np.uint8)
    padded[pad : pad + h] = patch

    jit = np.random.default_rng(seed)
    frames: list[NDArray[np.uint8]] = []
    # start with the slit (window centre) on roll row 0 and sweep to the last
    # roll row, so the reconstructed strip aligns with the flat scan in u.
    top = float(pad - wh / 2)
    max_top = float(pad + h - wh / 2)
    f = 0
    while top <= max_top:
        y = int(round(top))
        window = padded[y : y + wh].copy()
        if wobble_px > 0:
            shift = wobble_px * np.sin(2 * np.pi * f / 23.0)
            window = _shift_columns(window, shift, bg)
        frames.append(cv2.cvtColor(window, cv2.COLOR_GRAY2BGR))
        step = base_speed_px
        if speed_jitter > 0:
            step *= 1.0 + jit.uniform(-speed_jitter, speed_jitter)
        top += max(0.2, step)
        f += 1

    flat_bgr, doc = render(spec)
    return frames, flat_bgr, doc


def _shift_columns(
    img: NDArray[np.uint8], shift: float, fill: int
) -> NDArray[np.uint8]:
    """Translate an image horizontally by ``shift`` px (lateral wobble)."""
    h, w = img.shape
    m = np.array([[1.0, 0.0, shift], [0.0, 1.0, 0.0]], dtype=np.float64)
    return cv2.warpAffine(
        img, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=float(fill)
    )


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


def realistic_default_notes(spec: RollSpec) -> list[tuple[int, float, float]]:
    """Notes placed in the body (below the leader) for the realistic renderer."""
    notes: list[tuple[int, float, float]] = []
    floor = spec.cone_leader_mm + 5.0
    usable = spec.roll_length_mm - 5.0
    for lane in range(spec.n_lanes):
        u0 = floor + (lane % 5) * 4.0
        u1 = min(u0 + 8.0 + (lane % 4) * 6.0, usable)
        if u1 > u0:
            notes.append((lane, u0, u1))
    return notes


def render_realistic(spec: RollSpec) -> tuple[NDArray[np.uint8], RollDocument]:
    """Render a realistic colour roll: coloured material on a plain background,
    a narrowing top leader (``cone_leader_mm``), and **bed-through** holes (the
    perforations show the background colour). Returns ``(bgr, ground_truth)``.
    """
    rng = np.random.default_rng(spec.seed)
    ppmm = spec.dpi / 25.4
    roll_h = int(round(spec.roll_length_mm * ppmm))
    roll_w = int(round(spec.roll_width_mm * ppmm))
    pad = int(round(spec.pad_frac * max(roll_h, roll_w))) + 10
    big_h, big_w = roll_h + 2 * pad, roll_w + 2 * pad

    bg = np.array(spec.background_bgr, dtype=np.uint8)
    canvas = np.empty((big_h, big_w, 3), dtype=np.uint8)
    canvas[:] = bg

    # Roll outline: a cone (trapezoid) leader merged with the full-width body.
    cx = pad + roll_w / 2.0
    cone_rows = int(round(spec.cone_leader_mm * ppmm))
    top_half = max(2.0, spec.cone_top_frac * roll_w / 2.0)
    full_half = roll_w / 2.0
    cone_bottom = pad + cone_rows
    poly = np.array(
        [
            [cx - top_half, pad],
            [cx + top_half, pad],
            [cx + full_half, cone_bottom],
            [cx + full_half, pad + roll_h],
            [cx - full_half, pad + roll_h],
            [cx - full_half, cone_bottom],
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(canvas, [poly], tuple(int(c) for c in spec.material_bgr))

    # Bed-through perforations (background colour) for each note.
    notes = spec.notes if spec.notes is not None else realistic_default_notes(spec)
    for lane, u0_mm, u1_mm in notes:
        vc = int(round(pad + spec.lane_v_center_mm(lane) * ppmm))
        u0 = int(round(pad + u0_mm * ppmm))
        u1 = int(round(pad + u1_mm * ppmm))
        half_w = max(1, int(round(spec.pitch_mm * spec.hole_width_frac * ppmm / 2.0)))
        canvas[u0:u1, vc - half_w : vc + half_w + 1] = bg

    if spec.noise > 0:
        noisy = canvas.astype(np.float64) + rng.normal(0.0, spec.noise, canvas.shape)
        canvas = np.clip(noisy, 0, 255).astype(np.uint8)
    if spec.skew_deg != 0.0:
        rot = cv2.getRotationMatrix2D((big_w / 2.0, big_h / 2.0), spec.skew_deg, 1.0)
        canvas = cv2.warpAffine(
            canvas,
            rot,
            (big_w, big_h),
            flags=cv2.INTER_LINEAR,
            borderValue=tuple(int(c) for c in spec.background_bgr),
        )

    return canvas.astype(np.uint8), _ground_truth(spec, notes)
