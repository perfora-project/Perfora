"""Lane finding — the heart of perfora (original logic, no roll-standard assumed).

The lane pitch and offset are *measured* from the hole positions:

1. Project hole presence onto the cross axis ``v`` to get a density profile
   whose peaks are lane centres (§4.1).
2. Recover the pitch with autocorrelation + FFT, cross-checked, then refine
   ``(pitch, v0)`` to sub-pixel precision with a comb fit (§4.2-4.3,
   :mod:`perfora.utils.signal`).
3. Repeat in overlapping windows along ``u`` and take a robust consensus, so a
   roll that drifts along its length does not blur the estimate (§4.4); the
   spread across windows becomes the model confidence.

Lane *assignment* (which lane each hole belongs to) is derived directly from the
resulting :class:`~perfora.model.document.LaneModel`. Holes that fall between two
lane centres surface as note-level ``AMBIGUOUS_LANE`` reviews during note
assembly (review items must reference document notes/texts, and holes are not in
the document).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import gaussian_filter1d

from perfora.errors import LaneDetectionError
from perfora.model.document import LaneModel
from perfora.pipeline.preview import Overlay, StagePreview
from perfora.pipeline.stages.base import InteractionField
from perfora.utils.signal import comb_fit, estimate_pitch

if TYPE_CHECKING:
    from perfora.config import Config
    from perfora.pipeline.context import PipelineContext
    from perfora.pipeline.stages.holes import Hole

__all__ = ["LaneFinding", "v_density"]


def v_density(
    holes: list[Hole], n_cols: int, sigma_px: float
) -> NDArray[np.float64]:
    """Build the smoothed cross-axis density profile.

    Each hole contributes weight equal to its ``u`` extent (longer perforations
    give stronger lane peaks) at its centroid column.

    Parameters
    ----------
    holes : list[Hole]
        Extracted holes (pixel coordinates).
    n_cols : int
        Number of columns (``v`` extent) of the image.
    sigma_px : float
        Gaussian smoothing width in pixels.

    Returns
    -------
    NDArray
        1-D profile of length ``n_cols`` peaking at lane centres.
    """
    d = np.zeros(int(n_cols), dtype=np.float64)
    for h in holes:
        col = int(round(h.centroid_px[1]))
        if 0 <= col < n_cols:
            weight = float(h.bbox_px[2] - h.bbox_px[0])  # u extent in px
            d[col] += max(weight, 1.0)
    if sigma_px > 0:
        d = gaussian_filter1d(d, sigma=sigma_px)
    return np.asarray(d, dtype=np.float64)


def _density_from_cols(
    cols: NDArray[np.float64],
    weights: NDArray[np.float64],
    n_cols: int,
    sigma_px: float,
) -> NDArray[np.float64]:
    """Weighted, smoothed density of hole columns (possibly skew-adjusted)."""
    d = np.zeros(int(n_cols), dtype=np.float64)
    idx = np.round(cols).astype(np.int_)
    valid = (idx >= 0) & (idx < n_cols)
    np.add.at(d, idx[valid], weights[valid])
    if sigma_px > 0:
        d = gaussian_filter1d(d, sigma=sigma_px)
    return np.asarray(d, dtype=np.float64)


def _comb_energy(d: NDArray[np.float64], pitch: float) -> float:
    """Maximum energy a comb of spacing ``pitch`` captures over all phases."""
    n = len(d)
    if pitch < 1.0 or n == 0:
        return 0.0
    best = 0.0
    for phase in range(int(round(pitch))):
        idx = np.round(np.arange(phase, n, pitch)).astype(np.int_)
        idx = idx[idx < n]
        best = max(best, float(d[idx].sum()))
    return best


def _refine_skew(
    rows: NDArray[np.float64],
    cols: NDArray[np.float64],
    weights: NDArray[np.float64],
    n_cols: int,
    pitch_px: float,
    cfg: Config,
) -> float:
    """Find the small column-vs-row slope that makes the lanes most vertical.

    Searches slopes in ``[-lane_skew_max, lane_skew_max]`` and returns the one
    whose skew-adjusted column density has the strongest comb energy at
    ``pitch_px`` — i.e. the residual skew left by the coarse deskew, which on a
    very long roll still drifts the lanes by several teeth end to end.
    """
    if not np.isfinite(pitch_px) or rows.size == 0:
        return 0.0
    slopes = np.linspace(-cfg.lane_skew_max, cfg.lane_skew_max, cfg.lane_skew_steps)
    best_slope, best_score = 0.0, -np.inf
    for s in slopes:
        d = _density_from_cols(cols - s * rows, weights, n_cols, cfg.density_sigma_px)
        score = _comb_energy(d, pitch_px)
        if score > best_score:
            best_score, best_slope = score, float(s)
    return best_slope


def _windowed_pitch(
    holes: list[Hole],
    n_rows: int,
    n_cols: int,
    cfg: Config,
) -> tuple[float, float]:
    """Robust pitch (px) and a consistency confidence from overlapping windows.

    Returns ``(pitch_px, confidence)``. ``pitch_px`` is ``nan`` when no window
    yields a usable estimate.
    """
    rows = np.array([h.centroid_px[0] for h in holes], dtype=np.float64)
    k = max(1, int(cfg.n_windows))
    band = n_rows / k
    pitches: list[float] = []
    # overlapping bands: each window spans 2 nominal bands, stepping by one
    for i in range(k):
        lo = max(0.0, (i - 0.5) * band)
        hi = min(float(n_rows), (i + 1.5) * band)
        sel = [h for h, r in zip(holes, rows, strict=True) if lo <= r < hi]
        if len(sel) < 3:
            continue
        d = v_density(sel, n_cols, cfg.density_sigma_px)
        pitch, _conf, _method = estimate_pitch(
            d,
            min_pitch_px=cfg.min_pitch_px,
            max_pitch_px=cfg.max_pitch_px,
            min_freq_bin=cfg.min_freq_bin,
            agree_tol=cfg.pitch_agree_tol,
        )
        if np.isfinite(pitch):
            pitches.append(float(pitch))
    if not pitches:
        return (float("nan"), 0.0)
    arr = np.array(pitches, dtype=np.float64)
    med = float(np.median(arr))
    spread = float(np.std(arr) / med) if med > 0 else 1.0
    confidence = float(np.clip(1.0 - spread, 0.0, 1.0))
    return (med, confidence)


class LaneFinding:
    """Measure the lane model (pitch + offset + count) from the holes."""

    name: str = "lanes"
    consumes: ClassVar[tuple[str, ...]] = (
        "lane_pitch_mm",
        "lane_v0_mm",
        "n_lanes",
    )
    produces: ClassVar[tuple[str, ...]] = ("lane_model",)

    def run(self, ctx: PipelineContext) -> None:
        """Compute ``ctx.lane_model`` from ``ctx.holes`` and overrides.

        Raises
        ------
        LaneDetectionError
            When there are no holes, or no periodicity can be measured and no
            ``lane_pitch_mm`` override is supplied.
        """
        cfg = ctx.config
        ov = ctx.overrides
        mm_v = ctx.image.calibration.mm_per_px_v
        mm_u = ctx.image.calibration.mm_per_px_u
        n_rows, n_cols = ctx.image.gray.shape[:2]

        if not ctx.holes:
            raise LaneDetectionError("no holes available for lane finding")

        rows = np.array([h.centroid_px[0] for h in ctx.holes], dtype=np.float64)
        cols = np.array([h.centroid_px[1] for h in ctx.holes], dtype=np.float64)
        weights = np.array(
            [max(float(h.bbox_px[2] - h.bbox_px[0]), 1.0) for h in ctx.holes]
        )
        d0 = _density_from_cols(cols, weights, n_cols, cfg.density_sigma_px)

        # --- coarse pitch (px): override, else windowed consensus ------------
        method = "comb-fit"
        if ov.lane_pitch_mm is not None:
            pitch_guess = ov.lane_pitch_mm / mm_v
            confidence = 1.0
            method = "override"
        else:
            pitch_guess, conf_w = _windowed_pitch(ctx.holes, n_rows, n_cols, cfg)
            if not np.isfinite(pitch_guess):
                pitch_guess, conf_g, method = estimate_pitch(
                    d0,
                    min_pitch_px=cfg.min_pitch_px,
                    max_pitch_px=cfg.max_pitch_px,
                    min_freq_bin=cfg.min_freq_bin,
                    agree_tol=cfg.pitch_agree_tol,
                )
                confidence = conf_g
            else:
                confidence = conf_w
            if not np.isfinite(pitch_guess):
                raise LaneDetectionError(
                    "could not detect lane periodicity; supply lane_pitch_mm"
                )

        # --- residual-skew refine: the slope that makes lanes most vertical --
        # (handles drift that a coarse deskew leaves on very long rolls)
        slope = _refine_skew(rows, cols, weights, n_cols, pitch_guess, cfg)
        adj = cols - slope * rows
        d = _density_from_cols(adj, weights, n_cols, cfg.density_sigma_px)
        ctx.debug["v_density"] = d
        ctx.debug["lane_skew_mm"] = slope * (mm_v / mm_u)

        # --- pitch + offset on the deskewed columns -------------------------
        if ov.lane_pitch_mm is not None:
            pitch_px = pitch_guess
        else:
            pitch_px, _v0u = comb_fit(d, pitch_guess)
        if ov.lane_v0_mm is not None:
            v0_raw = ov.lane_v0_mm / mm_v
        else:
            _p, v0_raw = comb_fit(d, pitch_px)

        # --- normalise so the leftmost used lane is index 0, count lanes ----
        idx = np.round((adj - v0_raw) / pitch_px).astype(int)
        min_idx = int(idx.min())
        max_idx = int(idx.max())
        v0_px = v0_raw + min_idx * pitch_px
        n_lanes = max_idx - min_idx + 1
        if ov.n_lanes is not None:
            n_lanes = int(ov.n_lanes)

        ctx.lane_model = LaneModel(
            pitch_mm=pitch_px * mm_v,
            v0_mm=v0_px * mm_v,
            n_lanes=n_lanes,
            confidence=float(confidence),
            method=method,
        )

    # -- preview / interaction ------------------------------------------- #
    def preview(self, ctx: PipelineContext) -> StagePreview | None:
        lm = ctx.lane_model
        if lm is None:
            return None
        mm_v = ctx.image.calibration.mm_per_px_v
        centers_px = [
            (lm.v0_mm + i * lm.pitch_mm) / mm_v for i in range(lm.n_lanes)
        ]
        profile = ctx.debug.get("v_density")
        overlays: list[Overlay] = [Overlay(kind="lanes", data=centers_px)]
        if isinstance(profile, np.ndarray):
            overlays.append(Overlay(kind="profile", data=profile.tolist()))
        return StagePreview(
            base="gray",
            overlays=tuple(overlays),
            summary={
                "pitch_mm": round(lm.pitch_mm, 4),
                "n_lanes": lm.n_lanes,
                "confidence": round(lm.confidence, 3),
                "method": lm.method,
            },
        )

    def interaction_points(self, ctx: PipelineContext) -> list[InteractionField]:
        lm = ctx.lane_model
        pitch = lm.pitch_mm if lm else None
        v0 = lm.v0_mm if lm else None
        n_lanes = lm.n_lanes if lm else None
        fields: list[InteractionField] = [
            InteractionField(
                key="lane_pitch_mm",
                type="float",
                label="Lane pitch (mm)",
                current=pitch,
                options=None,
                constraints={"min": 0.5, "max": 50.0},
            ),
            InteractionField(
                key="lane_v0_mm",
                type="float",
                label="Lane 0 offset v0 (mm)",
                current=v0,
                options=None,
                constraints={"min": 0.0},
            ),
            InteractionField(
                key="n_lanes",
                type="int",
                label="Number of lanes",
                current=n_lanes,
                options=None,
                constraints={"min": 1},
            ),
        ]
        return fields
