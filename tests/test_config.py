"""Tests for perfora.config and perfora.errors."""

from __future__ import annotations

import dataclasses

import pytest
from perfora.config import Config
from perfora.errors import (
    CalibrationError,
    FormatError,
    LaneDetectionError,
    MissingBackendError,
    PerforaError,
    VideoReconstructionError,
)


def test_config_defaults() -> None:
    cfg = Config()
    assert cfg.lane_tol_frac == 0.25
    assert cfg.binarization_mode == "auto"


def test_config_frozen() -> None:
    cfg = Config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.lane_tol_frac = 0.5  # type: ignore[misc]


def test_to_params_types_and_keys() -> None:
    params = Config().to_params()
    assert "min_hole_area_mm2" in params
    for v in params.values():
        assert isinstance(v, (float, int, str, bool))


def test_config_override() -> None:
    assert Config(min_note_len_mm=2.5).min_note_len_mm == 2.5


def test_error_hierarchy() -> None:
    for cls in (
        CalibrationError,
        LaneDetectionError,
        MissingBackendError,
        FormatError,
        VideoReconstructionError,
    ):
        assert issubclass(cls, PerforaError)


def test_missing_backend_error_message_and_attrs() -> None:
    err = MissingBackendError("trocr", "trocr")
    msg = str(err)
    assert "perfora[trocr]" in msg  # how to install the extra
    assert "uv sync --extra trocr" in msg
    assert err.backend == "trocr"
    assert err.extra == "trocr"


def test_missing_backend_error_tesseract_mentions_system_engine() -> None:
    msg = str(MissingBackendError("tesseract", "tesseract"))
    assert "tesseract-ocr" in msg or "brew install tesseract" in msg
