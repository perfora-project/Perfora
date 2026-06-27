"""Tests for the periodicity helpers in ``perfora.utils.signal``."""

from __future__ import annotations

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from perfora.utils.signal import (
    autocorrelation,
    comb_fit,
    detect_peaks,
    estimate_pitch,
    fft_pitch,
)

# Config-default search band for these tests.
_BAND = {"min_pitch_px": 3, "max_pitch_px": 200, "min_freq_bin": 2, "agree_tol": 0.05}


def make_profile(
    pitch: float,
    v0: float,
    n_lanes: int = 30,
    noise: float = 0.0,
    seed: int = 0,
) -> np.ndarray:
    """Build a 1-D comb density profile with gaussian bumps at lane centres."""
    n = int(round(v0 + (n_lanes - 1) * pitch)) + 20
    xs = np.arange(n, dtype=np.float64)
    sigma = max(0.8, pitch * 0.12)
    d = np.zeros(n, dtype=np.float64)
    for lane in range(n_lanes):
        c = v0 + lane * pitch
        if 0 <= c < n:
            d += np.exp(-0.5 * ((xs - c) / sigma) ** 2)
    if noise > 0:
        d += np.random.default_rng(seed).normal(0.0, noise, n)
    return d


def test_autocorrelation_lag0_is_one() -> None:
    d = make_profile(pitch=8.0, v0=3.0)
    ac = autocorrelation(d)
    assert abs(ac[0] - 1.0) < 1e-9
    assert ac.shape[0] == d.shape[0]


def test_fft_pitch_on_pure_sine() -> None:
    n = 512
    period = 16.0
    x = np.sin(2 * np.pi * np.arange(n) / period)
    per, frac = fft_pitch(x, min_freq_bin=2)
    assert abs(per - period) / period < 0.02
    assert frac > 0.5


def test_detect_peaks_counts_comb_teeth() -> None:
    d = make_profile(pitch=10.0, v0=5.0, n_lanes=12)
    peaks = detect_peaks(d, min_distance=6.0)
    assert abs(len(peaks) - 12) <= 1


def test_estimate_and_comb_fit_clean() -> None:
    pitch, v0 = 7.3, 2.1
    d = make_profile(pitch=pitch, v0=v0, n_lanes=25)
    p0, conf, method = estimate_pitch(d, **_BAND)
    assert abs(p0 - pitch) / pitch < 0.05
    assert conf > 0.5
    refined, v0_rec = comb_fit(d, p0)
    assert abs(refined - pitch) / pitch < 0.01
    assert abs(v0_rec - v0) < pitch


@settings(max_examples=60, deadline=None)
@given(
    pitch=st.floats(min_value=5.0, max_value=35.0),
    v0_frac=st.floats(min_value=0.0, max_value=0.99),
    noise=st.floats(min_value=0.0, max_value=0.08),
    seed=st.integers(min_value=0, max_value=10_000),
)
def test_pitch_recovery_param_sweep(
    pitch: float, v0_frac: float, noise: float, seed: int
) -> None:
    """Pitch is recovered across random pitch/offset/noise with no constants."""
    v0 = v0_frac * pitch
    d = make_profile(pitch=pitch, v0=v0, n_lanes=30, noise=noise, seed=seed)
    p0, _conf, _method = estimate_pitch(d, **_BAND)
    refined, _v0 = comb_fit(d, p0)
    assert abs(refined - pitch) / pitch < 0.03
