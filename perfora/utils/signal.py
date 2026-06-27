"""Periodicity helpers for the lane-finder (original perfora logic).

These operate on a 1-D *density profile* ``d`` sampled along the cross axis
``v``: ``d[v]`` is high near a lane centre. The pitch (lane spacing) is recovered
with two independent estimators — autocorrelation and FFT — that are
cross-checked, then refined to sub-pixel precision by fitting a comb of equally
spaced teeth to the profile's peaks.

No roll-standard constant is used anywhere here; everything is measured from the
data. All quantities are in **pixels** (the caller converts to mm via the
calibration).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy import signal as _sig


def autocorrelation(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Return the mean-removed autocorrelation at non-negative lags, lag-0 = 1.

    Parameters
    ----------
    x : NDArray
        1-D signal.

    Returns
    -------
    NDArray
        ``ac`` with ``ac[0] == 1`` (unless ``x`` is constant, then all zeros).
    """
    xc = np.asarray(x, dtype=np.float64)
    xc = xc - xc.mean()
    full = _sig.correlate(xc, xc, mode="full")
    ac = full[len(xc) - 1 :]
    if ac[0] > 0:
        ac = ac / ac[0]
    return np.asarray(ac, dtype=np.float64)


def autocorr_pitch(
    d: NDArray[np.float64], min_pitch_px: int, max_pitch_px: int
) -> tuple[float, float]:
    """Estimate the pitch as the strongest autocorrelation lag in a band.

    Returns
    -------
    (lag, strength)
        ``lag`` in pixels and the normalized peak height in ``[0, 1]`` as a
        confidence proxy. ``(nan, 0.0)`` if the band is empty.
    """
    ac = autocorrelation(d)
    hi = min(max_pitch_px, len(ac) - 1)
    if hi < min_pitch_px:
        return (float("nan"), 0.0)
    band = ac[min_pitch_px : hi + 1]
    k = int(np.argmax(band))
    return (float(min_pitch_px + k), float(band[k]))


def fft_pitch(d: NDArray[np.float64], min_freq_bin: int) -> tuple[float, float]:
    """Estimate the pitch from the dominant non-DC frequency.

    Returns
    -------
    (period, power_fraction)
        ``period = len(d) / k`` in pixels for the peak bin ``k``, and that bin's
        share of total spectral power as a confidence proxy. ``(nan, 0.0)`` if no
        bin is available.
    """
    x = np.asarray(d, dtype=np.float64)
    x = x - x.mean()
    power = np.abs(np.fft.rfft(x)) ** 2
    if min_freq_bin < len(power):
        power[:min_freq_bin] = 0.0
    total = float(power.sum())
    if total <= 0.0:
        return (float("nan"), 0.0)
    k = int(np.argmax(power))
    if k == 0:
        return (float("nan"), 0.0)
    return (len(x) / k, float(power[k] / total))


def detect_peaks(d: NDArray[np.float64], min_distance: float) -> NDArray[np.int_]:
    """Return indices of local maxima at least ``min_distance`` px apart."""
    distance = max(1, int(round(min_distance)))
    peaks, _ = _sig.find_peaks(np.asarray(d, dtype=np.float64), distance=distance)
    return np.asarray(peaks, dtype=np.int_)


def comb_fit(d: NDArray[np.float64], pitch0: float) -> tuple[float, float]:
    """Refine ``(pitch, v0)`` by aligning a comb to the profile.

    First a phase sweep over one period finds the offset ``v0`` capturing the
    most energy; then the *measured* peak positions are linearly regressed
    against their *nominal* lane indices (``peak ≈ v0 + index * pitch``), which
    yields a sub-pixel pitch and offset and averages out per-lane jitter.

    Parameters
    ----------
    d : NDArray
        The density profile.
    pitch0 : float
        Coarse pitch estimate in pixels (from :func:`estimate_pitch`).

    Returns
    -------
    (pitch, v0)
        Refined pitch and lane-0 offset, in pixels.
    """
    x = np.asarray(d, dtype=np.float64)
    n = len(x)
    p0 = float(pitch0)
    if not np.isfinite(p0) or p0 < 1.0 or n == 0:
        return (p0, 0.0)

    # 1. phase sweep for the offset that captures the most energy
    best_phase, best_score = 0, -np.inf
    for phase in range(int(round(p0))):
        centres = np.arange(phase, n, p0)
        idx = np.round(centres).astype(np.int_)
        idx = idx[idx < n]
        score = float(x[idx].sum())
        if score > best_score:
            best_score, best_phase = score, phase
    v0 = float(best_phase)

    # 2. regression of measured peaks against nominal lane index
    peaks = detect_peaks(x, min_distance=0.6 * p0)
    if peaks.size >= 2:
        nominal = np.round((peaks - v0) / p0).astype(np.float64)
        slope, intercept = np.polyfit(nominal, peaks.astype(np.float64), 1)
        # guard against degenerate fits (e.g. picking a harmonic)
        if slope > 0 and abs(slope - p0) / p0 <= 0.5:
            return (float(slope), float(intercept))
    return (p0, v0)


def peak_coverage(peaks: NDArray[np.int_], pitch: float) -> float:
    """Fraction of ``peaks`` that sit on a comb of spacing ``pitch``.

    The comb phase is the circular mean of the peaks modulo ``pitch``. The true
    fundamental explains (almost) every peak; a harmonic (e.g. ``2 * pitch``)
    lands on only a subset, so coverage cleanly separates octave errors.
    """
    if peaks.size == 0 or not np.isfinite(pitch) or pitch < 1.0:
        return 0.0
    ang = 2.0 * np.pi * (peaks % pitch) / pitch
    phase = np.arctan2(np.sin(ang).mean(), np.cos(ang).mean()) / (2.0 * np.pi) * pitch
    centred = ((peaks - phase + 0.5 * pitch) % pitch) - 0.5 * pitch
    return float(np.mean(np.abs(centred) < 0.25 * pitch))


def estimate_pitch(
    d: NDArray[np.float64],
    *,
    min_pitch_px: int,
    max_pitch_px: int,
    min_freq_bin: int,
    agree_tol: float,
) -> tuple[float, float, str]:
    """Cross-check autocorrelation and FFT to estimate the lane pitch.

    The two estimators each propose a pitch; the candidate whose comb best
    *covers* the profile's peaks is chosen (this rejects octave errors, where one
    estimator latches onto ``2 * pitch``). When the estimators already agree
    within ``agree_tol`` the result is high-confidence.

    Returns
    -------
    (pitch, confidence, method)
        ``pitch`` in pixels, a confidence in ``[0, 1]``, and a method label
        (``"autocorr"``, ``"fft"`` or ``"comb-fit"``). ``(nan, 0, "comb-fit")``
        when no usable estimate exists.
    """
    lag_ac, _s_ac = autocorr_pitch(d, min_pitch_px, max_pitch_px)
    per_fft, _s_fft = fft_pitch(d, min_freq_bin)
    ac_ok = bool(np.isfinite(lag_ac))
    fft_ok = bool(np.isfinite(per_fft) and min_pitch_px <= per_fft <= max_pitch_px)

    candidates: list[tuple[float, str]] = []
    if ac_ok:
        candidates.append((float(lag_ac), "autocorr"))
    if fft_ok:
        candidates.append((float(per_fft), "fft"))
    if not candidates:
        return (float("nan"), 0.0, "comb-fit")

    if ac_ok and fft_ok:
        rel = abs(lag_ac - per_fft) / (0.5 * (lag_ac + per_fft))
        if rel < agree_tol:
            pitch = 0.5 * (lag_ac + per_fft)
            peaks = detect_peaks(d, min_distance=0.6 * pitch)
            conf = float(np.clip(0.6 + 0.4 * peak_coverage(peaks, pitch), 0.0, 1.0))
            return (float(pitch), conf, "autocorr")

    # Disagreement (or a single estimator): pick the best peak coverage. Ties go
    # to the smaller pitch, which is the fundamental.
    min_cand = min(p for p, _ in candidates)
    peaks = detect_peaks(d, min_distance=0.6 * min_cand)
    scored = [
        (peak_coverage(peaks, p), -p, p, label) for p, label in candidates
    ]
    scored.sort(reverse=True)
    best_cov, _negp, best_pitch, best_label = scored[0]
    method = best_label if len(candidates) == 1 else "comb-fit"
    conf = float(np.clip(0.5 * best_cov, 0.0, 1.0))
    return (best_pitch, conf, method)
