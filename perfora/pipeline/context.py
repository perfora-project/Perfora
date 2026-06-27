"""The shared pipeline state passed between stages."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from numpy.typing import NDArray

from perfora.config import Config
from perfora.errors import PerforaError
from perfora.model.document import (
    LaneModel,
    NoteEvent,
    RollDocument,
    TextRegion,
)
from perfora.pipeline.overrides import Overrides

if TYPE_CHECKING:
    from perfora.model.document import ReviewItem
    from perfora.pipeline.stages.holes import Hole
    from perfora.sources.base import RollImage


@dataclass(slots=True)
class PipelineContext:
    """Intermediate and final results plus the user overrides, shared by stages.

    Each stage reads the overrides that concern it *before* computing, then
    writes its result into the matching field here.
    """

    image: RollImage
    config: Config
    overrides: Overrides = field(default_factory=Overrides)
    mask: NDArray[Any] | None = None
    holes: list[Hole] = field(default_factory=list)
    lane_model: LaneModel | None = None
    notes: list[NoteEvent] = field(default_factory=list)
    texts: list[TextRegion] = field(default_factory=list)
    review: list[ReviewItem] = field(default_factory=list)

    def to_document(self) -> RollDocument:
        """Assemble the final :class:`RollDocument` from the current state.

        Raises
        ------
        PerforaError
            If called before a :class:`LaneModel` has been produced.
        """
        if self.lane_model is None:
            raise PerforaError(
                "Cannot build a RollDocument before the lane model is computed"
            )
        # The source stamps identity (type/name/version/created); the pipeline
        # stamps the effective config it actually ran with.
        provenance = replace(self.image.provenance, params=self.config.to_params())
        return RollDocument(
            provenance=provenance,
            calibration=self.image.calibration,
            lane_model=self.lane_model,
            notes=list(self.notes),
            texts=list(self.texts),
            review_queue=list(self.review),
        )
