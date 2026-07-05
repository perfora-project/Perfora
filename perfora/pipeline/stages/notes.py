"""Note assembly — perforation runs within a lane become sustained notes (§5).

Holes are grouped into lanes via the measured :class:`LaneModel`, sorted along
``u``, and merged into runs (small gaps are bridged so chain-perforated notes
become one note). Each run yields a :class:`NoteEvent` with a confidence that
combines how cleanly its holes sat on the lane centre and the run length. Notes
that are too short / noisy, or whose holes sat ambiguously between lanes, are
added to the review queue. User ``note_edits`` are applied last.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from perfora.model.document import NoteEvent, ReviewItem, ReviewReason
from perfora.pipeline.preview import Overlay, StagePreview
from perfora.pipeline.stages.base import InteractionField

if TYPE_CHECKING:
    from perfora.config import Config
    from perfora.model.document import LaneModel
    from perfora.pipeline.context import PipelineContext
    from perfora.pipeline.overrides import NoteEdit
    from perfora.pipeline.stages.holes import Hole

__all__ = ["NoteAssembly"]


def _group_by_lane(
    holes: list[Hole],
    lane_model: LaneModel,
    mm_v: float,
    mm_u: float,
    skew_mm: float,
) -> dict[int, list[tuple[Hole, float]]]:
    """Group holes by nearest lane, carrying each hole's signed residual (mm).

    ``skew_mm`` is the measured lane drift (v per u, mm/mm): the hole's column is
    corrected by ``skew_mm * u`` before assignment so a long roll's residual
    skew does not push end-of-roll notes into the wrong lane.
    """
    groups: dict[int, list[tuple[Hole, float]]] = {}
    for h in holes:
        v_mm = h.centroid_px[1] * mm_v - skew_mm * (h.centroid_px[0] * mm_u)
        lane, residual = lane_model.nearest_lane(v_mm)
        groups.setdefault(lane, []).append((h, residual))
    return groups


def _note_confidence(
    length_mm: float, residuals_mm: list[float], pitch_mm: float, cfg: Config
) -> float:
    """Confidence in ``[0, 1]`` from lane-centre cleanliness and run length."""
    if residuals_mm:
        mean_frac = sum(abs(r) for r in residuals_mm) / len(residuals_mm)
        mean_frac /= 0.5 * pitch_mm
    else:
        mean_frac = 1.0
    residual_factor = max(0.0, 1.0 - mean_frac)
    length_factor = min(1.0, length_mm / max(cfg.min_note_len_mm, 1e-6))
    return float(max(0.0, min(1.0, residual_factor * (0.5 + 0.5 * length_factor))))


class NoteAssembly:
    """Merge per-lane perforation runs into :class:`NoteEvent` objects."""

    name: str = "notes"
    consumes: ClassVar[tuple[str, ...]] = ("note_edits",)
    produces: ClassVar[tuple[str, ...]] = ("notes",)

    def run(self, ctx: PipelineContext) -> None:
        """Assemble notes from ``ctx.holes`` + ``ctx.lane_model``; apply edits."""
        lane_model = ctx.lane_model
        if lane_model is None:
            return
        cfg = ctx.config
        mm_u = ctx.image.calibration.mm_per_px_u
        mm_v = ctx.image.calibration.mm_per_px_v
        bridge_gap_mm = cfg.bridge_gap_mm
        tol_mm = cfg.lane_tol_frac * lane_model.pitch_mm

        skew_mm = float(ctx.debug.get("lane_skew_mm", 0.0))  # type: ignore[arg-type]
        notes: list[NoteEvent] = []
        ambiguous: list[bool] = []  # per-note: contained an ambiguous hole
        groups = _group_by_lane(ctx.holes, lane_model, mm_v, mm_u, skew_mm)
        for lane in sorted(groups):
            members = sorted(groups[lane], key=lambda hr: hr[0].bbox_px[0])
            runs = _build_runs(members, mm_u, bridge_gap_mm)
            for u_start, u_end, residuals in runs:
                length_mm = u_end - u_start
                conf = _note_confidence(
                    length_mm, residuals, lane_model.pitch_mm, cfg
                )
                notes.append(
                    NoteEvent(
                        lane=lane,
                        v_center_mm=lane_model.v_center(lane),
                        u_start_mm=u_start,
                        u_end_mm=u_end,
                        confidence=conf,
                    )
                )
                ambiguous.append(any(abs(r) > tol_mm for r in residuals))

        notes = _apply_note_edits(notes, ctx.overrides.note_edits, lane_model)
        ctx.notes = notes

        # Reviews reference note indices (holes are not in the document).
        for i, note in enumerate(notes):
            if i < len(ambiguous) and ambiguous[i]:
                ctx.review.append(
                    ReviewItem(
                        reason=ReviewReason.AMBIGUOUS_LANE,
                        ref_kind="note",
                        ref_id=i,
                        confidence=note.confidence,
                        message=(
                            f"note on lane {note.lane} has holes between lanes"
                        ),
                    )
                )
            if (
                note.length_mm < cfg.min_note_len_mm
                or note.confidence < cfg.note_conf_min
            ):
                ctx.review.append(
                    ReviewItem(
                        reason=ReviewReason.SHORT_OR_NOISY_NOTE,
                        ref_kind="note",
                        ref_id=i,
                        confidence=note.confidence,
                        message=(
                            f"short/low-confidence note "
                            f"(len={note.length_mm:.2f} mm)"
                        ),
                    )
                )

    # -- preview / interaction ------------------------------------------- #
    def preview(self, ctx: PipelineContext) -> StagePreview | None:
        if ctx.lane_model is None:
            return None
        mm_u = ctx.image.calibration.mm_per_px_u
        mm_v = ctx.image.calibration.mm_per_px_v
        half = 0.3 * ctx.lane_model.pitch_mm / mm_v
        spans = []
        for n in ctx.notes:
            vc = n.v_center_mm / mm_v
            spans.append(
                (
                    n.u_start_mm / mm_u,
                    vc - half,
                    n.u_end_mm / mm_u,
                    vc + half,
                )
            )
        used = {n.lane for n in ctx.notes}
        n_lanes = ctx.lane_model.n_lanes
        return StagePreview(
            base="gray",
            overlays=(Overlay(kind="spans", data=spans),),
            summary={
                "n_notes": len(ctx.notes),
                "lanes_used": len(used),
                "lanes_unused": max(n_lanes - len(used), 0),
            },
        )

    def interaction_points(self, ctx: PipelineContext) -> list[InteractionField]:
        # Note edits are item-based (add/remove/move); a CLI/UI iterates the
        # review queue and applies NoteEdit overrides, so no scalar fields here.
        return []


def _build_runs(
    members: list[tuple[Hole, float]], mm_u: float, bridge_gap_mm: float
) -> list[tuple[float, float, list[float]]]:
    """Merge sorted holes into ``(u_start_mm, u_end_mm, residuals)`` runs."""
    runs: list[tuple[float, float, list[float]]] = []
    cur_start: float | None = None
    cur_end = 0.0
    cur_res: list[float] = []
    for hole, residual in members:
        u0 = hole.bbox_px[0] * mm_u
        u1 = hole.bbox_px[2] * mm_u
        if cur_start is None:
            cur_start, cur_end, cur_res = u0, u1, [residual]
        elif u0 - cur_end <= bridge_gap_mm:
            cur_end = max(cur_end, u1)
            cur_res.append(residual)
        else:
            runs.append((cur_start, cur_end, cur_res))
            cur_start, cur_end, cur_res = u0, u1, [residual]
    if cur_start is not None:
        runs.append((cur_start, cur_end, cur_res))
    return runs


def _apply_note_edits(
    notes: list[NoteEvent], edits: list[NoteEdit], lane_model: LaneModel
) -> list[NoteEvent]:
    """Apply add/remove/move note edits, returning the new note list."""
    result: list[NoteEvent | None] = list(notes)
    for e in edits:
        if e.op == "add" and e.lane is not None:
            result.append(
                NoteEvent(
                    lane=e.lane,
                    v_center_mm=lane_model.v_center(e.lane),
                    u_start_mm=e.u_start_mm or 0.0,
                    u_end_mm=e.u_end_mm or 0.0,
                    confidence=1.0,
                )
            )
        elif (
            e.op == "remove"
            and e.ref_id is not None
            and 0 <= e.ref_id < len(result)
        ):
            result[e.ref_id] = None
        elif e.op == "move" and e.ref_id is not None and 0 <= e.ref_id < len(result):
            old = result[e.ref_id]
            if old is not None:
                lane = e.lane if e.lane is not None else old.lane
                result[e.ref_id] = NoteEvent(
                    lane=lane,
                    v_center_mm=lane_model.v_center(lane),
                    u_start_mm=(
                        e.u_start_mm if e.u_start_mm is not None else old.u_start_mm
                    ),
                    u_end_mm=(
                        e.u_end_mm if e.u_end_mm is not None else old.u_end_mm
                    ),
                    confidence=old.confidence,
                )
    return [n for n in result if n is not None]
