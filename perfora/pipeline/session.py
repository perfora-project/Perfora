"""The :class:`Session`: a UI-drivable, stepwise pipeline runner.

A UI — or the interactive CLI — drives the pipeline one stage at a time: run a
stage, :meth:`preview` it, :meth:`apply_override` to adjust its inputs,
:meth:`rerun_from` that point, repeat. The one-shot
:func:`perfora.process` is just ``Session(source, ...).run_all()``.

Re-run semantics
----------------
Stages are linearly ordered, so editing the output of stage *K* invalidates
*K+1 … end*. :meth:`apply_override` / :meth:`invalidate_from` reset the cursor
and clear downstream results (including the review items those stages produced);
:meth:`rerun_from` then recomputes what changed.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from perfora.config import Config
from perfora.errors import PerforaError
from perfora.pipeline.context import PipelineContext
from perfora.pipeline.overrides import Overrides
from perfora.pipeline.progress import NullProgressReporter, ProgressReporter

if TYPE_CHECKING:
    from perfora.model.document import ReviewItem, RollDocument
    from perfora.pipeline.preview import StagePreview
    from perfora.pipeline.stages.base import InteractionField, Stage
    from perfora.sources.base import Source

# ctx fields reset to a non-empty default (lists); everything else resets to None.
_LIST_FIELDS = frozenset({"holes", "notes", "texts"})


@dataclass(slots=True)
class StageResult:
    """The outcome of running one stage."""

    stage: str
    preview: StagePreview | None
    interaction: list[InteractionField]
    new_reviews: list[ReviewItem]


class Session:
    """Drives a pipeline stepwise with previews, overrides and snapshots.

    Parameters
    ----------
    source : Source
        Produces the canonical :class:`~perfora.sources.base.RollImage`.
    stages : list[Stage] or None, optional
        Explicit stage list. When ``None``, the default pipeline is used (wired
        in Phase 1+); tests pass their own stages.
    config : Config or None, optional
        Pipeline thresholds.
    overrides : Overrides or None, optional
        Pre-seeded user corrections.
    progress : ProgressReporter or None, optional
        Progress / cancellation sink (defaults to a no-op reporter).
    """

    def __init__(
        self,
        source: Source,
        *,
        stages: list[Stage] | None = None,
        config: Config | None = None,
        overrides: Overrides | None = None,
        progress: ProgressReporter | None = None,
    ) -> None:
        self.source = source
        self.config = config or Config()
        self._progress: ProgressReporter = progress or NullProgressReporter()
        if stages is None:
            from perfora.pipeline.pipeline import default_pipeline

            stages = default_pipeline().stages
        self.stages: list[Stage] = stages
        names = [s.name for s in stages]
        if len(set(names)) != len(names):
            raise PerforaError(f"stage names must be unique, got {names}")
        self._index = {name: i for i, name in enumerate(names)}
        self.ctx = PipelineContext(
            image=source.to_roll_image(),
            config=self.config,
            overrides=overrides or Overrides(),
        )
        self.cursor = 0
        self._results: list[StageResult] = []

    # -- helpers ----------------------------------------------------------- #
    def _stage_index(self, name: str) -> int:
        if name not in self._index:
            raise PerforaError(
                f"unknown stage {name!r}; known stages: {list(self._index)}"
            )
        return self._index[name]

    def _reset_ctx_field(self, field_name: str) -> None:
        if field_name in _LIST_FIELDS:
            setattr(self.ctx, field_name, [])
        else:
            setattr(self.ctx, field_name, None)

    # -- running ----------------------------------------------------------- #
    def step(self) -> StageResult:
        """Run exactly one stage and return its :class:`StageResult`."""
        if self.cursor >= len(self.stages):
            raise PerforaError("pipeline is already complete; nothing to step")
        stage = self.stages[self.cursor]
        self._progress.on_stage_start(stage.name)
        before = len(self.ctx.review)
        stage.run(self.ctx)
        new_reviews = list(self.ctx.review[before:])
        result = StageResult(
            stage=stage.name,
            preview=stage.preview(self.ctx),
            interaction=stage.interaction_points(self.ctx),
            new_reviews=new_reviews,
        )
        self._results.append(result)  # invariant: len(_results) == cursor + 1 now
        self.cursor += 1
        self._progress.on_stage_end(stage.name, result)
        return result

    def run_to(self, stage: str) -> None:
        """Run up to and including the named stage."""
        target = self._stage_index(stage)
        while self.cursor <= target:
            self.step()

    def run_all(self) -> RollDocument:
        """Run the remaining stages and return the assembled document."""
        while self.cursor < len(self.stages):
            self.step()
        return self.ctx.to_document()

    # -- inspection -------------------------------------------------------- #
    def preview(self, stage: str | None = None) -> StagePreview | None:
        """Return a stage's preview (last-run stage when ``stage`` is ``None``)."""
        if stage is None:
            return self._results[-1].preview if self._results else None
        idx = self._stage_index(stage)
        if idx < len(self._results):
            return self._results[idx].preview
        return self.stages[idx].preview(self.ctx)

    def interaction_points(self, stage: str | None = None) -> list[InteractionField]:
        """Return a stage's interaction points (last-run stage if ``None``)."""
        if stage is None:
            return list(self._results[-1].interaction) if self._results else []
        idx = self._stage_index(stage)
        if idx < len(self._results):
            return list(self._results[idx].interaction)
        return self.stages[idx].interaction_points(self.ctx)

    # -- editing / re-run -------------------------------------------------- #
    def apply_override(self, **changes: Any) -> None:
        """Record overrides and invalidate from the earliest affected stage.

        Each key must be a field of
        :class:`~perfora.pipeline.overrides.Overrides`. The earliest stage that
        declares it ``consumes`` one of the changed keys is invalidated (and the
        cursor moves back to it); if no stage consumes a key it is simply
        recorded.
        """
        valid = {f.name for f in dataclasses.fields(Overrides)}
        for key, value in changes.items():
            if key not in valid:
                raise PerforaError(
                    f"unknown override {key!r}; valid keys: {sorted(valid)}"
                )
            setattr(self.ctx.overrides, key, value)

        changed = set(changes)
        affected = [
            i
            for i, st in enumerate(self.stages)
            if changed & set(getattr(st, "consumes", ()))
        ]
        if affected:
            self.invalidate_from(self.stages[min(affected)].name)

    def invalidate_from(self, stage: str) -> None:
        """Drop results from ``stage`` onward and move the cursor back to it."""
        idx = self._stage_index(stage)
        for st in self.stages[idx:]:
            for field_name in getattr(st, "produces", ()):
                self._reset_ctx_field(field_name)
        del self._results[idx:]
        self.ctx.review = [r for res in self._results for r in res.new_reviews]
        self.cursor = min(self.cursor, idx)

    def rerun_from(self, stage: str) -> None:
        """Invalidate from ``stage`` and recompute through to the last stage."""
        self.invalidate_from(stage)
        while self.cursor < len(self.stages):
            self.step()

    # -- save / resume ----------------------------------------------------- #
    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the session state.

        Restored deterministically by re-running to the saved cursor with the
        saved config and overrides (see :meth:`restore`); intermediate images
        and masks are never serialized.
        """
        return {
            "cursor": self.cursor,
            "config": self.config.to_params(),
            "overrides": self.ctx.overrides.to_dict(),
            "stage_names": [s.name for s in self.stages],
        }

    @classmethod
    def restore(
        cls,
        snapshot: dict[str, Any],
        source: Source,
        *,
        stages: list[Stage] | None = None,
    ) -> Session:
        """Rebuild a session from :meth:`snapshot` and re-run to its cursor.

        Parameters
        ----------
        snapshot : dict
            Output of :meth:`snapshot`.
        source : Source
            The same source the snapshot was taken against (not serialized).
        stages : list[Stage] or None, optional
            Stage list to use; must match the snapshot's stage names. Defaults
            to the default pipeline.
        """
        config = Config(**snapshot["config"])
        overrides = Overrides.from_dict(snapshot["overrides"])
        session = cls(source, stages=stages, config=config, overrides=overrides)
        saved_names = snapshot.get("stage_names")
        if saved_names is not None and [s.name for s in session.stages] != saved_names:
            raise PerforaError(
                "stage set does not match the snapshot; pass matching stages"
            )
        target = int(snapshot["cursor"])
        while session.cursor < target:
            session.step()
        return session
