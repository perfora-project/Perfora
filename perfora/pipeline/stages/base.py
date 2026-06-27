"""The ``Stage`` protocol and the ``InteractionField`` UI descriptor.

A stage computes one step of the pipeline, reading from and writing to a shared
:class:`~perfora.pipeline.context.PipelineContext`. Beyond ``run``, every stage
advertises a :meth:`preview` and the :meth:`interaction_points` a UI may edit,
so an external UI or the interactive CLI can drive the pipeline generically.

Two optional class attributes let :class:`~perfora.pipeline.session.Session`
manage re-runs without hard-coding stage internals:

``consumes``
    Override keys (fields of :class:`~perfora.pipeline.overrides.Overrides`) the
    stage reads. Editing one of these invalidates from this stage onward.
``produces``
    :class:`~perfora.pipeline.context.PipelineContext` field names the stage
    writes; they are reset when the stage is invalidated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from perfora.pipeline.context import PipelineContext
    from perfora.pipeline.preview import StagePreview


class InteractionField(TypedDict):
    """A single editable decision a stage exposes to a generic UI.

    Keys
    ----
    key : str
        Maps to an :class:`~perfora.pipeline.overrides.Overrides` field or edit
        list.
    type : str
        ``"float"``, ``"int"``, ``"enum"``, ``"bool"``, ``"points"``,
        ``"boxes"`` or ``"text"``.
    label : str
        Human-readable label.
    current : object
        The current value (may be ``None`` before the stage has run).
    options : list or None
        Allowed values for ``"enum"``.
    constraints : dict or None
        E.g. ``{"min": .., "max": ..}`` for numeric fields.
    """

    key: str
    type: str
    label: str
    current: object
    options: list[object] | None
    constraints: dict[str, object] | None


@runtime_checkable
class Stage(Protocol):
    """One ordered, independently testable step of the pipeline."""

    name: str
    consumes: ClassVar[tuple[str, ...]]
    produces: ClassVar[tuple[str, ...]]

    def run(self, ctx: PipelineContext) -> None:
        """Compute this stage's result, honouring ``ctx.overrides`` first."""
        ...

    def preview(self, ctx: PipelineContext) -> StagePreview | None:
        """Return a render-agnostic preview of the result, or ``None``."""
        ...

    def interaction_points(self, ctx: PipelineContext) -> list[InteractionField]:
        """Return the editable decisions a UI/CLI may override."""
        ...
