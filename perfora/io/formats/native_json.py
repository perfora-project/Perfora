"""Native perfora JSON format: lossless round-trip codec.

Format envelope
---------------
.. code-block:: json

    {
      "format": "native-json",
      "schema_version": 1,
      "document": { ... }
    }

All spatial quantities are stored as-is (floats in mm).  Enums are encoded
as their ``.value`` string.  The ``debug`` field of
:class:`~perfora.model.document.RollDocument` is intentionally omitted.
:attr:`TextRegion.associated_note_ids` and
:attr:`ReviewItem.suggestions` are stored as JSON arrays and decoded back
to ``tuple`` on read so dataclass equality is preserved.
"""

from __future__ import annotations

import json
import os
from typing import Any

from perfora.errors import FormatError
from perfora.io.base import Reader, Writer
from perfora.io.registry import register_reader, register_writer
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

_FORMAT_ID = "native-json"
_SCHEMA_VERSION = 1


# --------------------------------------------------------------------------- #
# Encoding helpers  (RollDocument -> JSON-serialisable dict)
# --------------------------------------------------------------------------- #
def _enc_provenance(p: Provenance) -> dict[str, Any]:
    return {
        "source_type": p.source_type,
        "source_name": p.source_name,
        "perfora_version": p.perfora_version,
        "created_utc": p.created_utc,
        "params": p.params,
    }


def _enc_calibration(c: Calibration) -> dict[str, Any]:
    return {
        "mm_per_px_u": c.mm_per_px_u,
        "mm_per_px_v": c.mm_per_px_v,
        "dpi": c.dpi,
        "source": c.source,
    }


def _enc_lane_model(lm: LaneModel) -> dict[str, Any]:
    return {
        "pitch_mm": lm.pitch_mm,
        "v0_mm": lm.v0_mm,
        "n_lanes": lm.n_lanes,
        "confidence": lm.confidence,
        "method": lm.method,
    }


def _enc_note(n: NoteEvent) -> dict[str, Any]:
    return {
        "lane": n.lane,
        "v_center_mm": n.v_center_mm,
        "u_start_mm": n.u_start_mm,
        "u_end_mm": n.u_end_mm,
        "confidence": n.confidence,
        "pitch": n.pitch,
    }


def _enc_bbox(b: BBox) -> dict[str, Any]:
    return {"u0": b.u0, "v0": b.v0, "u1": b.u1, "v1": b.v1}


def _enc_text(t: TextRegion) -> dict[str, Any]:
    return {
        "text": t.text,
        "bbox_mm": _enc_bbox(t.bbox_mm),
        "scope": t.scope.value,
        "kind": t.kind.value,
        "confidence": t.confidence,
        "recognized_by": t.recognized_by,
        "needs_review": t.needs_review,
        "associated_note_ids": list(t.associated_note_ids),
        "category": t.category,
    }


def _enc_review_item(r: ReviewItem) -> dict[str, Any]:
    return {
        "reason": r.reason.value,
        "ref_kind": r.ref_kind,
        "ref_id": r.ref_id,
        "confidence": r.confidence,
        "message": r.message,
        "suggestions": list(r.suggestions),
    }


def _enc_document(doc: RollDocument) -> dict[str, Any]:
    """Encode *doc* to a JSON-serialisable dict; ``debug`` is omitted."""
    return {
        "provenance": _enc_provenance(doc.provenance),
        "calibration": _enc_calibration(doc.calibration),
        "lane_model": _enc_lane_model(doc.lane_model),
        "notes": [_enc_note(n) for n in doc.notes],
        "texts": [_enc_text(t) for t in doc.texts],
        "review_queue": [_enc_review_item(r) for r in doc.review_queue],
        "standard_guess": doc.standard_guess,
    }


# --------------------------------------------------------------------------- #
# Decoding helpers  (JSON dict -> exact dataclass instances)
# --------------------------------------------------------------------------- #
def _dec_provenance(d: dict[str, Any]) -> Provenance:
    return Provenance(
        source_type=d["source_type"],
        source_name=d["source_name"],
        perfora_version=d["perfora_version"],
        created_utc=d["created_utc"],
        params=d["params"],
    )


def _dec_calibration(d: dict[str, Any]) -> Calibration:
    return Calibration(
        mm_per_px_u=d["mm_per_px_u"],
        mm_per_px_v=d["mm_per_px_v"],
        dpi=d.get("dpi"),
        source=d.get("source", "unknown"),
    )


def _dec_lane_model(d: dict[str, Any]) -> LaneModel:
    return LaneModel(
        pitch_mm=d["pitch_mm"],
        v0_mm=d["v0_mm"],
        n_lanes=d["n_lanes"],
        confidence=d["confidence"],
        method=d["method"],
    )


def _dec_note(d: dict[str, Any]) -> NoteEvent:
    return NoteEvent(
        lane=d["lane"],
        v_center_mm=d["v_center_mm"],
        u_start_mm=d["u_start_mm"],
        u_end_mm=d["u_end_mm"],
        confidence=d["confidence"],
        pitch=d.get("pitch"),
    )


def _dec_bbox(d: dict[str, Any]) -> BBox:
    return BBox(u0=d["u0"], v0=d["v0"], u1=d["u1"], v1=d["v1"])


def _dec_text(d: dict[str, Any]) -> TextRegion:
    return TextRegion(
        text=d["text"],
        bbox_mm=_dec_bbox(d["bbox_mm"]),
        scope=TextScope(d["scope"]),
        kind=TextKind(d["kind"]),
        confidence=d["confidence"],
        recognized_by=d["recognized_by"],
        needs_review=d["needs_review"],
        associated_note_ids=tuple(d.get("associated_note_ids", [])),
        category=d.get("category"),
    )


def _dec_review_item(d: dict[str, Any]) -> ReviewItem:
    return ReviewItem(
        reason=ReviewReason(d["reason"]),
        ref_kind=d["ref_kind"],
        ref_id=d["ref_id"],
        confidence=d["confidence"],
        message=d["message"],
        suggestions=tuple(d.get("suggestions", [])),
    )


def _dec_document(d: dict[str, Any]) -> RollDocument:
    return RollDocument(
        provenance=_dec_provenance(d["provenance"]),
        calibration=_dec_calibration(d["calibration"]),
        lane_model=_dec_lane_model(d["lane_model"]),
        notes=[_dec_note(n) for n in d["notes"]],
        texts=[_dec_text(t) for t in d["texts"]],
        review_queue=[_dec_review_item(r) for r in d["review_queue"]],
        standard_guess=d.get("standard_guess"),
    )


# --------------------------------------------------------------------------- #
# Public codec classes
# --------------------------------------------------------------------------- #
@register_writer
class NativeJsonWriter(Writer):
    """Writer for the native perfora JSON format.

    Serialises a :class:`~perfora.model.document.RollDocument` to a UTF-8
    JSON file with ``indent=2``.  The ``debug`` field is intentionally
    omitted from the output.
    """

    format_id = _FORMAT_ID
    extensions = (".perfora.json",)

    def write(
        self, doc: RollDocument, path: str | os.PathLike[str]
    ) -> None:
        """Serialise *doc* and write it to *path*.

        Parameters
        ----------
        doc : RollDocument
            Document to serialise.
        path : str or os.PathLike[str]
            Destination file path (created or overwritten).
        """
        payload: dict[str, Any] = {
            "format": _FORMAT_ID,
            "schema_version": _SCHEMA_VERSION,
            "document": _enc_document(doc),
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)


@register_reader
class NativeJsonReader(Reader):
    """Reader for the native perfora JSON format.

    Reads a file produced by :class:`NativeJsonWriter` and reconstructs the
    exact :class:`~perfora.model.document.RollDocument` dataclass tree,
    converting JSON arrays back to ``tuple`` where required so that
    dataclass ``__eq__`` round-trips correctly.
    """

    format_id = _FORMAT_ID
    extensions = (".perfora.json",)

    def read(self, path: str | os.PathLike[str]) -> RollDocument:
        """Parse *path* and return the reconstructed document.

        Parameters
        ----------
        path : str or os.PathLike[str]
            Source file path.

        Returns
        -------
        RollDocument

        Raises
        ------
        FormatError
            If the file's ``format`` or ``schema_version`` is unexpected.
        """
        with open(path, encoding="utf-8") as fh:
            payload: dict[str, Any] = json.load(fh)

        if payload.get("format") != _FORMAT_ID:
            raise FormatError(
                f"Expected format {_FORMAT_ID!r}, "
                f"got {payload.get('format')!r}"
            )
        sv = payload.get("schema_version")
        if sv != _SCHEMA_VERSION:
            raise FormatError(
                f"Unsupported schema_version {sv!r} "
                f"(expected {_SCHEMA_VERSION})"
            )
        return _dec_document(payload["document"])
