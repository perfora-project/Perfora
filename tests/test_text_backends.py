"""Tests for text detection / recognition backends.

Backends that require optional extras ([easyocr], [tesseract], [trocr]) are
skipped automatically when those extras are not installed.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from typing import Any

import cv2
import numpy as np
import pytest
from perfora.errors import MissingBackendError
from perfora.model.calibration import Calibration
from perfora.model.document import Provenance, TextKind
from perfora.sources.base import RollImage
from perfora.text.base import DetBox
from perfora.text.detectors import ContourDetector  # noqa: E402

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _roll_image(
    gray: Any,
    mm_per_px: float = 0.1,
) -> RollImage:
    """Wrap a numpy array in a minimal RollImage."""
    cal = Calibration(
        mm_per_px_u=mm_per_px,
        mm_per_px_v=mm_per_px,
        dpi=254,
        source="dpi",
    )
    prov = Provenance("image", "test", "0.1.0", "2026-06-27T00:00:00Z", {})
    return RollImage(gray=gray, calibration=cal, provenance=prov)


def _text_image(
    height: int = 200,
    width: int = 400,
) -> tuple[Any, list[tuple[int, int, int, int]]]:
    """Render two lines of black text on a white background.

    Returns
    -------
    img : uint8 ndarray, shape (height, width)
    text_bands : list of (x, y, w, h) approximate bounding bands for the text
    """
    img = np.full((height, width), 255, dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 1.0
    thickness = 2
    color = 0  # black

    y1, y2 = 60, 140
    cv2.putText(img, "NOCTURNE", (30, y1), font, scale, color, thickness)
    cv2.putText(img, "Chopin", (30, y2), font, scale, color, thickness)

    # Approximate bands (loose): y-range where the text sits
    bands = [
        (30, y1 - 30, 200, 40),  # approx band for line 1
        (30, y2 - 30, 200, 40),  # approx band for line 2
    ]
    return img, bands


# --------------------------------------------------------------------------- #
# ContourDetector — core, no extra deps
# --------------------------------------------------------------------------- #

class TestContourDetector:
    def test_returns_list_of_detbox(self) -> None:
        img_arr, _ = _text_image()
        roll = _roll_image(img_arr)
        det = ContourDetector()
        results = det.detect(roll)
        assert isinstance(results, list)
        for box in results:
            assert isinstance(box, DetBox)

    def test_detects_at_least_one_box(self) -> None:
        img_arr, _ = _text_image()
        roll = _roll_image(img_arr)
        results = ContourDetector().detect(roll)
        assert len(results) >= 1, (
            f"Expected >= 1 detection on a text image, got {len(results)}"
        )

    def test_bbox_is_four_ints(self) -> None:
        img_arr, _ = _text_image()
        roll = _roll_image(img_arr)
        for box in ContourDetector().detect(roll):
            x, y, w, h = box.bbox_px
            assert isinstance(x, int)
            assert isinstance(y, int)
            assert isinstance(w, int)
            assert isinstance(h, int)

    def test_kind_hint_is_unknown(self) -> None:
        img_arr, _ = _text_image()
        roll = _roll_image(img_arr)
        for box in ContourDetector().detect(roll):
            assert box.kind_hint is TextKind.UNKNOWN

    def test_at_least_one_box_in_text_vertical_band(self) -> None:
        """At least one box should overlap the y-range where text was drawn."""
        img_arr, bands = _text_image()
        roll = _roll_image(img_arr)
        results = ContourDetector().detect(roll)

        # Check that at least one detected box has its y in one of the bands
        def _overlaps_band(
            box: DetBox, band: tuple[int, int, int, int]
        ) -> bool:
            _bx, by, _bw, bh = box.bbox_px
            _, band_y, _, band_h = band
            box_y0, box_y1 = by, by + bh
            band_y0, band_y1 = band_y, band_y + band_h
            return box_y0 < band_y1 and box_y1 > band_y0

        found = any(
            _overlaps_band(box, band)
            for box in results
            for band in bands
        )
        assert found, (
            f"No detected box overlaps the text bands.\n"
            f"Boxes: {[b.bbox_px for b in results]}\n"
            f"Bands: {bands}"
        )

    def test_blank_image_produces_no_large_box(self) -> None:
        """A fully white (blank) image should not produce a full-image box."""
        img_arr = np.full((200, 400), 255, dtype=np.uint8)
        roll = _roll_image(img_arr)
        results = ContourDetector().detect(roll)
        # No box should cover > 90% of the image area
        img_area = 200 * 400
        for box in results:
            _, _, w, h = box.bbox_px
            assert w * h < img_area * 0.90

    def test_accepts_color_roll_image(self) -> None:
        """ContourDetector uses .gray; color field does not matter."""
        img_arr, _ = _text_image()
        color = cv2.cvtColor(img_arr, cv2.COLOR_GRAY2BGR)
        cal = Calibration(mm_per_px_u=0.1, mm_per_px_v=0.1, source="dpi")
        prov = Provenance("image", "test", "0.1.0", "2026-06-27T00:00:00Z", {})
        roll = RollImage(gray=img_arr, calibration=cal, provenance=prov, color=color)
        results = ContourDetector().detect(roll)
        assert len(results) >= 1


# --------------------------------------------------------------------------- #
# EasyOCRDetector — optional [easyocr]
# --------------------------------------------------------------------------- #

_easyocr_available = importlib.util.find_spec("easyocr") is not None


class TestEasyOCRDetector:
    @pytest.mark.skipif(
        _easyocr_available,
        reason="easyocr IS installed; skip MissingBackendError path",
    )
    def test_raises_missing_backend_error_when_not_installed(self) -> None:
        from perfora.text.detectors.easyocr_detector import EasyOCRDetector

        with pytest.raises(MissingBackendError) as exc_info:
            EasyOCRDetector()
        assert "easyocr" in str(exc_info.value)
        assert exc_info.value.backend == "easyocr"
        assert exc_info.value.extra == "easyocr"

    @pytest.mark.skipif(
        not _easyocr_available,
        reason="needs [easyocr] extra",
    )
    def test_detects_text_when_installed(self) -> None:
        from perfora.text.detectors.easyocr_detector import EasyOCRDetector

        img_arr, _ = _text_image()
        roll = _roll_image(img_arr)
        det = EasyOCRDetector()
        results = det.detect(roll)
        assert isinstance(results, list)
        for box in results:
            assert isinstance(box, DetBox)
            x, y, w, h = box.bbox_px
            assert isinstance(x, int)
            assert isinstance(y, int)
            assert isinstance(w, int)
            assert isinstance(h, int)


# --------------------------------------------------------------------------- #
# TesseractRecognizer — optional [tesseract]
# --------------------------------------------------------------------------- #

_pytesseract_available = importlib.util.find_spec("pytesseract") is not None


class TestTesseractRecognizer:
    @pytest.mark.skipif(
        _pytesseract_available,
        reason="pytesseract IS installed; skip MissingBackendError path",
    )
    def test_raises_missing_backend_error_when_not_installed(self) -> None:
        from perfora.text.recognizers.tesseract import TesseractRecognizer

        with pytest.raises(MissingBackendError) as exc_info:
            TesseractRecognizer()
        assert "tesseract" in str(exc_info.value)
        assert exc_info.value.backend == "tesseract"
        assert exc_info.value.extra == "tesseract"

    @pytest.mark.skipif(
        not _pytesseract_available,
        reason="needs [tesseract] extra",
    )
    def test_printed_labels_recognized(self) -> None:
        from perfora.text.recognizers.tesseract import TesseractRecognizer

        # Render a clear printed word on white background
        img = np.full((60, 200), 255, dtype=np.uint8)
        cv2.putText(
            img, "FORTE", (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2
        )
        rec = TesseractRecognizer()
        result = rec.recognize(img)
        assert isinstance(result.text, str)
        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0
        # Loose check: recognized text should contain the word (case-insensitive)
        assert "forte" in result.text.lower(), (
            f"Expected 'forte' in {result.text!r}"
        )

    @pytest.mark.skipif(
        not _pytesseract_available,
        reason="needs [tesseract] extra",
    )
    def test_empty_image_returns_empty_string(self) -> None:
        from perfora.text.recognizers.tesseract import TesseractRecognizer

        img = np.full((60, 200), 255, dtype=np.uint8)
        rec = TesseractRecognizer()
        result = rec.recognize(img)
        assert isinstance(result.text, str)
        assert result.confidence == 0.0 or result.text == ""

    def test_handles_attribute_is_printed(self) -> None:
        from perfora.text.recognizers.tesseract import TesseractRecognizer

        assert TesseractRecognizer.handles is TextKind.PRINTED


# --------------------------------------------------------------------------- #
# TrocrRecognizer — optional [trocr]
# --------------------------------------------------------------------------- #

_transformers_available = importlib.util.find_spec("transformers") is not None
_torch_available = importlib.util.find_spec("torch") is not None
_trocr_available = _transformers_available and _torch_available


class TestTrocrRecognizer:
    @pytest.mark.skipif(
        _trocr_available,
        reason="trocr deps ARE installed; skip MissingBackendError path",
    )
    def test_raises_missing_backend_error_when_not_installed(self) -> None:
        from perfora.text.recognizers.trocr import TrocrRecognizer

        rec = TrocrRecognizer()  # construction is fine (lazy load)
        img = np.full((60, 200), 255, dtype=np.uint8)
        with pytest.raises(MissingBackendError) as exc_info:
            rec.recognize(img)
        assert "trocr" in str(exc_info.value)
        assert exc_info.value.backend == "trocr"
        assert exc_info.value.extra == "trocr"

    @pytest.mark.skipif(
        not _trocr_available,
        reason="needs [trocr] extra",
    )
    def test_handwritten_recognition_runs(self) -> None:
        from perfora.text.recognizers.trocr import TrocrRecognizer

        img = np.full((60, 200), 255, dtype=np.uint8)
        cv2.putText(img, "Hello", (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
        rec = TrocrRecognizer()
        result = rec.recognize(img)
        assert isinstance(result.text, str)
        assert result.confidence == 0.5  # documented fixed value

    def test_handles_attribute_is_handwritten(self) -> None:
        from perfora.text.recognizers.trocr import TrocrRecognizer

        assert TrocrRecognizer.handles is TextKind.HANDWRITTEN

    def test_construction_does_not_load_model(self) -> None:
        """TrocrRecognizer.__init__ must not trigger any heavy imports."""
        from perfora.text.recognizers.trocr import TrocrRecognizer

        rec = TrocrRecognizer()
        # Internal state: processor and model are None until first recognize call
        assert rec._processor is None  # noqa: SLF001
        assert rec._model is None  # noqa: SLF001


# --------------------------------------------------------------------------- #
# MissingBackendError message check
# --------------------------------------------------------------------------- #

class TestMissingBackendErrorMessages:
    """The error message must mention the pip extra."""

    def test_message_mentions_extra(self) -> None:
        err = MissingBackendError("mybackend", "myextra")
        assert "myextra" in str(err)
        assert "mybackend" in str(err)


# --------------------------------------------------------------------------- #
# Import-lightness guard
# --------------------------------------------------------------------------- #

class TestImportLightness:
    """Importing the detector/recognizer packages must not pull in heavy deps."""

    def test_importing_detectors_does_not_import_easyocr(self) -> None:
        # Guard: only meaningful if easyocr wasn't already loaded before this
        # test suite started.  If it's already in sys.modules we cannot
        # distinguish cause, so we simply skip the assertion.
        if "easyocr" in sys.modules:
            pytest.skip("easyocr already in sys.modules before test")

        importlib.import_module("perfora.text.detectors")
        assert "easyocr" not in sys.modules, (
            "importing perfora.text.detectors imported easyocr"
        )

    def test_importing_recognizers_does_not_import_torch(self) -> None:
        if "torch" in sys.modules:
            pytest.skip("torch already in sys.modules before test")

        importlib.import_module("perfora.text.recognizers")
        assert "torch" not in sys.modules, (
            "importing perfora.text.recognizers imported torch"
        )

    def test_importing_recognizers_does_not_import_pytesseract(self) -> None:
        if "pytesseract" in sys.modules:
            pytest.skip("pytesseract already in sys.modules before test")

        importlib.import_module("perfora.text.recognizers")
        assert "pytesseract" not in sys.modules, (
            "importing perfora.text.recognizers imported pytesseract"
        )

    def test_importing_recognizers_does_not_import_transformers(self) -> None:
        if "transformers" in sys.modules:
            pytest.skip("transformers already in sys.modules before test")

        importlib.import_module("perfora.text.recognizers")
        assert "transformers" not in sys.modules, (
            "importing perfora.text.recognizers imported transformers"
        )
