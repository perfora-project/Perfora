"""Text stage: orchestrate detect -> recognize -> scope -> associate (§6) + edits.

Runs a :class:`~perfora.text.engine.TextEngine` (the default offline engine when
none is supplied), writes the resulting regions and review items into the
context, and applies any user ``text_edits``.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, ClassVar

from perfora.model.document import TextKind, TextRegion, TextScope
from perfora.model.geometry import BBox
from perfora.pipeline.preview import Overlay, StagePreview
from perfora.pipeline.stages.base import InteractionField

if TYPE_CHECKING:
    from perfora.pipeline.context import PipelineContext
    from perfora.pipeline.overrides import TextEdit
    from perfora.text.engine import TextEngine

__all__ = ["TextStage"]


class TextStage:
    """Detect/recognize/scope/associate text and apply user text edits."""

    name: str = "text"
    consumes: ClassVar[tuple[str, ...]] = ("text_edits",)
    produces: ClassVar[tuple[str, ...]] = ("texts",)

    def __init__(self, engine: TextEngine | None = None) -> None:
        self._engine = engine

    def _get_engine(self) -> TextEngine:
        if self._engine is None:
            from perfora.text.engine import default_text_engine

            self._engine = default_text_engine()
        return self._engine

    def run(self, ctx: PipelineContext) -> None:
        """Populate ``ctx.texts`` and append text review items; apply edits."""
        if ctx.lane_model is None:
            return
        engine = self._get_engine()
        texts, reviews = engine.run(
            ctx.image, ctx.lane_model, ctx.notes, ctx.config
        )
        texts = _apply_text_edits(texts, ctx.overrides.text_edits)
        ctx.texts = texts
        ctx.review.extend(reviews)

    # -- preview / interaction ------------------------------------------- #
    def preview(self, ctx: PipelineContext) -> StagePreview | None:
        mm_u = ctx.image.calibration.mm_per_px_u
        mm_v = ctx.image.calibration.mm_per_px_v
        boxes = []
        labels = []
        for t in ctx.texts:
            x = t.bbox_mm.v0 / mm_v
            y = t.bbox_mm.u0 / mm_u
            w = (t.bbox_mm.v1 - t.bbox_mm.v0) / mm_v
            h = (t.bbox_mm.u1 - t.bbox_mm.u0) / mm_u
            boxes.append((x, y, w, h))
            tag = t.text or "?"
            if t.needs_review:
                tag += " [review]"
            labels.append((x, max(0.0, y - 2.0), tag))
        n_review = sum(1 for t in ctx.texts if t.needs_review)
        return StagePreview(
            base="color",
            overlays=(
                Overlay(kind="boxes", data=boxes, style={"color": (0, 0, 255)}),
                Overlay(kind="labels", data=labels),
            ),
            summary={"n_texts": len(ctx.texts), "n_review": n_review},
        )

    def interaction_points(self, ctx: PipelineContext) -> list[InteractionField]:
        # Text edits are item-based (retype/rescope/add/remove); a UI/CLI walks
        # the review queue and applies TextEdit overrides per region.
        return []


def _apply_text_edits(
    texts: list[TextRegion], edits: list[TextEdit]
) -> list[TextRegion]:
    """Apply set_text/set_scope/set_kind/add/remove edits, return the new list."""
    result: list[TextRegion | None] = list(texts)
    for e in edits:
        if e.op == "add":
            bbox = BBox(*e.bbox_mm) if e.bbox_mm is not None else BBox(0, 0, 0, 0)
            result.append(
                TextRegion(
                    text=e.text or "",
                    bbox_mm=bbox,
                    scope=TextScope(e.scope) if e.scope else TextScope.GLOBAL_MARGIN,
                    kind=TextKind(e.kind) if e.kind else TextKind.UNKNOWN,
                    confidence=1.0,
                    recognized_by="user",
                    needs_review=False,
                )
            )
            continue
        if e.ref_id is None or not (0 <= e.ref_id < len(result)):
            continue
        old = result[e.ref_id]
        if old is None:
            continue
        if e.op == "remove":
            result[e.ref_id] = None
        elif e.op == "set_text":
            result[e.ref_id] = dataclasses.replace(
                old, text=e.text or "", recognized_by="user", needs_review=False
            )
        elif e.op == "set_scope" and e.scope is not None:
            result[e.ref_id] = dataclasses.replace(old, scope=TextScope(e.scope))
        elif e.op == "set_kind" and e.kind is not None:
            result[e.ref_id] = dataclasses.replace(old, kind=TextKind(e.kind))
    return [t for t in result if t is not None]
