"""Regenerate the bundled sample roll (``perfora/resources/sample_roll.png``).

The sample is a *synthetic* roll rendered by the test fixture generator, so it
ships with exact ground truth and no provenance questions — it is not a scan of
a real, possibly copyrighted roll. It exists so a new user can run the whole
pipeline (``perfora sample`` → ``perfora -i ...``) before owning a scan.

Run from the repository root::

    uv run python scripts/make_sample_roll.py

Deterministic: the same spec always renders the same PNG, so re-running it
produces no diff unless the generator itself changed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fixtures.synth import RollSpec, render_realistic  # noqa: E402

# Ground truth of the shipped sample. Keep these numbers in sync with the
# `examples`/README walkthrough and with `perfora/resources/__init__.py`.
DPI = 300.0
PITCH_MM = 3.0
N_LANES = 25
ROLL_LENGTH_MM = 170.0


def sample_notes() -> list[tuple[int, float, float]]:
    """A musically plausible pattern: a rising scale, then two sustained chords.

    Returns
    -------
    list of (int, float, float)
        ``(lane, u_start_mm, u_end_mm)`` triples, millimetres along the roll.
    """
    notes: list[tuple[int, float, float]] = []
    # Rising staircase — one short note per lane, walking across the roll.
    u = 30.0
    for lane in range(N_LANES):
        notes.append((lane, u, u + 6.0))
        u += 3.2
    # Two sustained chords further down the roll (long notes, several lanes).
    for lane in (2, 6, 9, 13):
        notes.append((lane, 128.0, 150.0))
    for lane in (4, 8, 11, 16, 20):
        notes.append((lane, 152.0, 166.0))
    return notes


def main() -> int:
    spec = RollSpec(
        pitch_mm=PITCH_MM,
        n_lanes=N_LANES,
        roll_length_mm=ROLL_LENGTH_MM,
        margin_mm=6.0,
        dpi=DPI,
        notes=sample_notes(),
        hole_width_frac=0.55,
        # A narrowing leader at the top, like a real roll's tab end.
        cone_leader_mm=22.0,
        cone_top_frac=0.30,
        material_bgr=(70, 90, 200),  # warm reddish paper (BGR)
        background_bgr=(250, 250, 250),  # plain light scanner bed
        # No sensor noise: it would make the PNG ~50x larger for no teaching
        # value. The skew below is what makes this a non-trivial input.
        noise=0.0,
        skew_deg=0.6,  # a touch of scan skew, so deskewing is exercised
        pad_frac=0.06,
        seed=7,
    )
    bgr, truth = render_realistic(spec)

    out = ROOT / "perfora" / "resources" / "sample_roll.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), bgr, [cv2.IMWRITE_PNG_COMPRESSION, 9])

    kb = out.stat().st_size / 1024.0
    print(
        f"wrote {out.relative_to(ROOT)}  "
        f"{bgr.shape[1]}x{bgr.shape[0]}px  {kb:.0f} KiB"
    )
    print(
        f"ground truth: {len(truth.notes)} notes, {N_LANES} lanes, "
        f"pitch {PITCH_MM} mm, {DPI:.0f} dpi"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
