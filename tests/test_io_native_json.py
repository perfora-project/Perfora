"""Tests for the native-json I/O codec and the format registry.

Covers:
- Lossless round-trip for a non-trivial RollDocument
- Extension-based format inference
- Dash / underscore alias normalisation
- available_formats() listing
- Entry-point plugin discovery via monkeypatching
"""

from __future__ import annotations

import os

import pytest
from perfora.errors import FormatError
from perfora.io import (
    available_formats,
    get_writer,
    infer_format_from_path,
    read_document,
    write_document,
)
from perfora.model.calibration import Calibration
from perfora.model.document import (
    LaneModel,
    NoteEvent,
    Provenance,
    ReviewItem,
    ReviewReason,
    RollDocument,
    TextKind,
    TextRegion,
    TextScope,
)
from perfora.model.geometry import BBox


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_doc() -> RollDocument:
    """Build a non-trivial RollDocument that exercises every edge case."""
    return RollDocument(
        provenance=Provenance(
            source_type="image",
            source_name="scan_001.tiff",
            perfora_version="0.1.0",
            created_utc="2024-06-01T12:00:00Z",
            params={
                "threshold": 0.5,
                "min_note_len_mm": 2,
                "dpi": 600,
                "do_ocr": True,
            },
        ),
        calibration=Calibration(
            mm_per_px_u=25.4 / 600,
            mm_per_px_v=25.4 / 600,
            dpi=600.0,
            source="dpi",
        ),
        lane_model=LaneModel(
            pitch_mm=3.175,
            v0_mm=12.5,
            n_lanes=88,
            confidence=0.97,
            method="autocorr",
        ),
        notes=[
            NoteEvent(
                lane=40,
                v_center_mm=139.0,
                u_start_mm=50.0,
                u_end_mm=65.0,
                confidence=0.99,
                pitch=60,
            ),
            NoteEvent(
                lane=41,
                v_center_mm=142.175,
                u_start_mm=55.0,
                u_end_mm=70.0,
                confidence=0.85,
                # pitch intentionally omitted -> None
            ),
        ],
        texts=[
            TextRegion(
                text="Moonlight Sonata",
                bbox_mm=BBox(u0=10.0, v0=5.0, u1=80.0, v1=20.0),
                scope=TextScope.GLOBAL_HEADER,
                kind=TextKind.PRINTED,
                confidence=0.95,
                recognized_by="tesseract",
                needs_review=False,
                associated_note_ids=(),
                category="title",
            ),
            TextRegion(
                text="",
                bbox_mm=BBox(u0=200.0, v0=15.0, u1=250.0, v1=30.0),
                scope=TextScope.TIMELINE,
                kind=TextKind.HANDWRITTEN,
                confidence=0.2,
                recognized_by="",
                needs_review=True,
                associated_note_ids=(0, 1),
                category=None,
            ),
        ],
        review_queue=[
            ReviewItem(
                reason=ReviewReason.DETECTED_NOT_RECOGNIZED,
                ref_kind="text",
                ref_id=1,
                confidence=0.2,
                message="Detected but no backend could read it",
                suggestions=("forte", "mf"),
            ),
            ReviewItem(
                reason=ReviewReason.AMBIGUOUS_LANE,
                ref_kind="note",
                ref_id=0,
                confidence=0.45,
                message="Hole sits between lanes 40 and 41",
                suggestions=(),
            ),
        ],
        standard_guess="88-note",
    )


# --------------------------------------------------------------------------- #
# Test 1: lossless round-trip
# --------------------------------------------------------------------------- #
def test_model_roundtrip_native_json(tmp_path: pytest.TempPathFactory) -> None:
    doc = _make_doc()
    # Inject something into debug — it must NOT appear after round-trip.
    doc.debug["raw_mask"] = b"should not be serialized"

    out = tmp_path / "x.perfora.json"  # type: ignore[operator]
    write_document(doc, out)
    loaded = read_document(out)

    # debug is compare=False so this equality holds even though contents differ
    assert loaded == doc

    # debug was not serialised -> the loaded doc has the default empty dict
    assert loaded.debug == {}

    # Spot-check that tuple fields round-trip as tuples (not lists)
    assert isinstance(loaded.texts[1].associated_note_ids, tuple)
    assert loaded.texts[1].associated_note_ids == (0, 1)
    assert isinstance(loaded.review_queue[0].suggestions, tuple)
    assert loaded.review_queue[0].suggestions == ("forte", "mf")
    assert isinstance(loaded.review_queue[1].suggestions, tuple)
    assert loaded.review_queue[1].suggestions == ()

    # Enum values
    assert loaded.texts[0].scope is TextScope.GLOBAL_HEADER
    assert loaded.texts[1].scope is TextScope.TIMELINE
    assert loaded.texts[0].kind is TextKind.PRINTED
    assert loaded.review_queue[0].reason is ReviewReason.DETECTED_NOT_RECOGNIZED

    # Optional fields
    assert loaded.calibration.dpi == 600.0
    assert loaded.standard_guess == "88-note"
    assert loaded.notes[0].pitch == 60
    assert loaded.notes[1].pitch is None
    assert loaded.texts[0].category == "title"
    assert loaded.texts[1].category is None


# --------------------------------------------------------------------------- #
# Test 2: extension inference
# --------------------------------------------------------------------------- #
def test_extension_inference(tmp_path: pytest.TempPathFactory) -> None:
    # Known compound extension -> native-json
    assert infer_format_from_path("foo.perfora.json") == "native-json"

    # Writing with format=None infers from extension
    doc = _make_doc()
    out = tmp_path / "bar.perfora.json"  # type: ignore[operator]
    write_document(doc, out, format=None)
    assert out.exists()  # type: ignore[union-attr]

    # Unknown extension raises FormatError
    with pytest.raises(FormatError):
        infer_format_from_path("foo.unknown")


# --------------------------------------------------------------------------- #
# Test 3: dash / underscore alias
# --------------------------------------------------------------------------- #
def test_format_id_dash_underscore_alias() -> None:
    from perfora.io.formats.native_json import NativeJsonWriter

    w1 = get_writer("native_json")
    w2 = get_writer("native-json")
    assert isinstance(w1, NativeJsonWriter)
    assert isinstance(w2, NativeJsonWriter)


# --------------------------------------------------------------------------- #
# Test 4: available_formats lists native-json
# --------------------------------------------------------------------------- #
def test_available_formats_lists_native_json() -> None:
    fmts = available_formats()
    assert "native-json" in fmts
    info = fmts["native-json"]
    assert info["read"] is True
    assert info["write"] is True
    assert ".perfora.json" in info["extensions"]


# --------------------------------------------------------------------------- #
# Test 5: entry-point discovery via monkeypatch
# --------------------------------------------------------------------------- #
def test_registry_entry_point_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata as im

    import perfora.io.registry as reg
    from perfora.io.base import Writer

    class FakeWriter(Writer):
        format_id = "fake-fmt"
        extensions = (".fake",)

        def write(
            self, doc: RollDocument, path: str | os.PathLike[str]
        ) -> None:
            pass  # no-op

    class _FakeEP:
        name = "fake-fmt"
        group = "perfora.writers"

        def load(self) -> type[FakeWriter]:
            return FakeWriter

    def _fake_entry_points(**kwargs: str) -> list[_FakeEP]:
        if kwargs.get("group") == "perfora.writers":
            return [_FakeEP()]
        return []

    # Patch importlib.metadata.entry_points as used by the registry module
    monkeypatch.setattr(im, "entry_points", _fake_entry_points)
    # Reset the run-once guard so _load_entry_points() will fire again
    monkeypatch.setattr(reg, "_entry_points_loaded", False)

    try:
        fmts = available_formats()
        assert "fake-fmt" in fmts, (
            f"'fake-fmt' not in available_formats(); got: {list(fmts)}"
        )
        assert fmts["fake-fmt"]["write"] is True
        assert ".fake" in fmts["fake-fmt"]["extensions"]
        # The real writer is still present
        assert "native-json" in fmts
    finally:
        # Clean up the fake entry from the registry so it does not bleed
        # into other tests. monkeypatch restores _entry_points_loaded and
        # importlib.metadata.entry_points automatically.
        reg._WRITERS.pop("fake-fmt", None)
