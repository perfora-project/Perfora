"""Review-item builders and dedupe — one place for consistent thresholds (§8).

Routine uncertainty is *data*, not exceptions: low-confidence or boundary
results become :class:`ReviewItem` entries that a future UI walks and resolves.
The reference (``ref_kind`` + ``ref_id``) points at a document note or text so
the UI can render the bbox-bearing region directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from perfora.model.document import ReviewItem, ReviewReason

if TYPE_CHECKING:
    from perfora.config import Config
    from perfora.model.document import TextRegion


def text_review_item(
    idx: int, region: TextRegion, config: Config
) -> ReviewItem | None:
    """Return a review item for a text region, or ``None`` if it is clean.

    A detected-but-unrecognized box yields ``DETECTED_NOT_RECOGNIZED``; an
    under-threshold recognition yields ``LOW_OCR_CONFIDENCE``.
    """
    if region.recognized_by == "" or region.text == "":
        return ReviewItem(
            reason=ReviewReason.DETECTED_NOT_RECOGNIZED,
            ref_kind="text",
            ref_id=idx,
            confidence=region.confidence,
            message="text detected but not recognized (no backend or empty)",
        )
    if region.confidence < config.ocr_conf_min:
        return ReviewItem(
            reason=ReviewReason.LOW_OCR_CONFIDENCE,
            ref_kind="text",
            ref_id=idx,
            confidence=region.confidence,
            message=f"low OCR confidence ({region.confidence:.2f})",
        )
    return None


def scope_review_item(idx: int, region: TextRegion) -> ReviewItem:
    """Return an ``UNCERTAIN_SCOPE`` review item for a boundary-case region."""
    return ReviewItem(
        reason=ReviewReason.UNCERTAIN_SCOPE,
        ref_kind="text",
        ref_id=idx,
        confidence=region.confidence,
        message=f"scope near a band boundary ({region.scope.value})",
    )


def dedupe(items: list[ReviewItem]) -> list[ReviewItem]:
    """Drop duplicate items sharing ``(reason, ref_kind, ref_id)``, order-stable."""
    seen: set[tuple[ReviewReason, str, int]] = set()
    out: list[ReviewItem] = []
    for it in items:
        key = (it.reason, it.ref_kind, it.ref_id)
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out
