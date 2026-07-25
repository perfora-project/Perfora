"""Background-keyed roll segmentation probe (throwaway diagnostic).

Validates, on a *real* scan, the idea of isolating the roll by keying on the
uniform background instead of looking for a rectangular page, and of reading the
perforations as background-coloured islands inside the roll.

Run:
    uv run python scripts/segment_probe.py /path/to/scan.jp2

Optional:
    --seg-max 6000   downscale longest side to this for the whole-roll view
    --band-frac 0.4  where (fraction of height) to take a FULL-RES hole patch
    --band-px 1800   height of that full-res patch

Writes, next to the input:
    <stem>_probe_region.png   whole roll, background dimmed (check the shape)
    <stem>_probe_holes.png    full-res band with detected holes in green
and prints diagnostics. Look at the two PNGs and paste the printout back.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from perfora.utils.signal import comb_fit, estimate_pitch
from scipy import ndimage


def _background_color(img: np.ndarray, frac: float = 0.02) -> np.ndarray:
    """Robust background colour from a border ring (median, BGR)."""
    h, w = img.shape[:2]
    r = max(2, int(frac * min(h, w)))
    ring = np.concatenate(
        [
            img[:r].reshape(-1, 3),
            img[-r:].reshape(-1, 3),
            img[:, :r].reshape(-1, 3),
            img[:, -r:].reshape(-1, 3),
        ]
    )
    return np.median(ring, axis=0)


def _foreground(img: np.ndarray, bg: np.ndarray) -> tuple[np.ndarray, float]:
    """Boolean foreground (far from background) + the distance threshold used."""
    dist = np.linalg.norm(img.astype(np.float32) - bg, axis=2)
    otsu, _ = cv2.threshold(
        dist.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    thr = max(20.0, float(otsu))
    return dist > thr, thr


def _largest_region(fg: np.ndarray) -> np.ndarray:
    """Largest opened foreground component, holes filled (the roll region)."""
    clean = ndimage.binary_opening(fg, iterations=2)
    lbl, n = ndimage.label(clean)
    if n == 0:
        return np.zeros_like(fg)
    sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
    roll = lbl == (1 + int(np.argmax(sizes)))
    return ndimage.binary_fill_holes(roll)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--seg-max", type=int, default=6000)
    ap.add_argument("--band-frac", type=float, default=0.4)
    ap.add_argument("--band-px", type=int, default=1800)
    args = ap.parse_args()

    full = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if full is None:
        print(f"cannot read {args.image!r} (try converting to .png/.tif?)")
        return 2
    big_h, big_w = full.shape[:2]
    print(f"loaded {big_w} x {big_h}")
    bg = _background_color(full)
    print(f"background colour (BGR): {bg.round(1)}")

    # ---- whole-roll segmentation (downscaled for the shape) ----------------
    scale = min(1.0, args.seg_max / max(big_h, big_w))
    small = (
        cv2.resize(
            full, (int(big_w * scale), int(big_h * scale)),
            interpolation=cv2.INTER_AREA,
        )
        if scale < 1.0
        else full
    )
    fg, thr = _foreground(small, bg)
    region = _largest_region(fg)
    print(f"foreground distance threshold: {thr:.1f}")
    ys, xs = np.where(region)
    if ys.size:
        print(
            f"roll bbox rows {ys.min()}..{ys.max()} cols {xs.min()}..{xs.max()} "
            f"({100 * region.mean():.1f}% of frame, scale={scale:.3f})"
        )
        widths = region.sum(axis=1)
        body = widths[widths > 0.5 * widths.max()]
        print(
            f"roll width: cone min ~{int(widths[widths>0].min())}px, "
            f"body ~{int(np.median(body))}px (downscaled)"
        )
    holes_small = region & ~fg
    hrows = np.where(holes_small.any(axis=1))[0]
    if hrows.size:
        print(
            f"bg-coloured islands inside roll span rows "
            f"{hrows.min()}..{hrows.max()} (start at "
            f"{100*hrows.min()/small.shape[0]:.1f}% of height)"
        )

    vis = small.copy()
    vis[~region] = (vis[~region] * 0.3).astype(np.uint8)
    out_region = Path(args.image).with_name(Path(args.image).stem + "_probe_region.png")
    cv2.imwrite(str(out_region), vis)

    # ---- full-resolution hole band ----------------------------------------
    y0 = int(big_h * args.band_frac)
    band = full[y0 : y0 + min(args.band_px, big_h - y0)]
    bfg, _ = _foreground(band, bg)
    bregion = _largest_region(bfg)
    holes = ndimage.binary_opening(bregion & ~bfg, iterations=1)
    hlbl, hn = ndimage.label(holes)
    widths = []
    if hn:
        objs = ndimage.find_objects(hlbl)
        widths = [int(s[1].stop - s[1].start) for s in objs if s is not None]
    print(
        f"full-res band rows {y0}..{y0+band.shape[0]}: "
        f"{hn} hole candidates, median hole width "
        f"{int(np.median(widths)) if widths else 0}px"
    )

    # quick pitch estimate from the band's column density (reuses perfora logic)
    col_density = holes.sum(axis=0).astype(np.float64)
    if col_density.sum() > 0:
        p0, conf, method = estimate_pitch(
            col_density, min_pitch_px=3, max_pitch_px=200,
            min_freq_bin=2, agree_tol=0.05,
        )
        if np.isfinite(p0):
            pitch, _v0 = comb_fit(col_density, p0)
            print(
                f"estimated lane pitch ~{pitch:.1f}px "
                f"(~{band.shape[1]/pitch:.0f} lanes across, conf {conf:.2f})"
            )

    hole_vis = band.copy()
    hole_vis[holes] = (0, 255, 0)
    out_holes = Path(args.image).with_name(Path(args.image).stem + "_probe_holes.png")
    cv2.imwrite(str(out_holes), hole_vis)
    print(f"wrote {out_region.name} and {out_holes.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
