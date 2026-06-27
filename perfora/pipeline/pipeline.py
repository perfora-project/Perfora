"""The pipeline orchestrator and the default stage ordering.

For interactive, stepwise, previewable execution use
:class:`~perfora.pipeline.session.Session`. :class:`Pipeline` is the plain
one-shot runner.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from perfora.config import Config
from perfora.pipeline.context import PipelineContext

if TYPE_CHECKING:
    from perfora.model.document import RollDocument
    from perfora.pipeline.stages.base import Stage
    from perfora.sources.base import Source


class Pipeline:
    """An ordered list of stages run over a single source."""

    def __init__(self, stages: list[Stage]) -> None:
        self.stages = stages

    def run(self, source: Source, config: Config | None = None) -> RollDocument:
        """Run all stages over ``source`` and return the document."""
        image = source.to_roll_image()
        ctx = PipelineContext(image=image, config=config or Config())
        for stage in self.stages:
            stage.run(ctx)
        return ctx.to_document()


def default_pipeline(text_engine: object | None = None) -> Pipeline:
    """Return the default decode pipeline.

    Parameters
    ----------
    text_engine : object or None, optional
        The text engine for the text stage (Phase 2+). Accepted now so the
        signature is stable; the text stage is appended once it exists.

    Returns
    -------
    Pipeline
        The full pipeline: preprocess -> holes -> lanes -> notes -> text.
    """
    from perfora.pipeline.stages.holes import HoleExtraction
    from perfora.pipeline.stages.lanes import LaneFinding
    from perfora.pipeline.stages.notes import NoteAssembly
    from perfora.pipeline.stages.preprocess import Preprocess
    from perfora.pipeline.stages.text import TextStage
    from perfora.text.engine import TextEngine

    engine = text_engine if isinstance(text_engine, TextEngine) else None
    return Pipeline(
        [
            Preprocess(),
            HoleExtraction(),
            LaneFinding(),
            NoteAssembly(),
            TextStage(engine),
        ]
    )
