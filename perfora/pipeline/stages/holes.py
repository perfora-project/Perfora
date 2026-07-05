"""The ``Hole`` intermediate and the hole-extraction pipeline stage.

``Hole`` is an internal intermediate produced by hole extraction and consumed by
the lane-finder and note assembler. It lives entirely in pixel space and never
appears in :class:`~perfora.model.document.RollDocument`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
from numpy.typing import NDArray

from perfora.config import Config
from perfora.errors import PerforaError
from perfora.model.calibration import Calibration
from perfora.pipeline.preview import Overlay, StagePreview
from perfora.pipeline.stages.base import InteractionField

if TYPE_CHECKING:
    from perfora.pipeline.context import PipelineContext

__all__ = ["Hole", "HoleExtraction", "extract_holes"]


@dataclass(frozen=True, slots=True)
class Hole:
    """A single connected perforation region, in pixel coordinates.

    Parameters
    ----------
    bbox_px : tuple[int, int, int, int]
        Bounding box as ``(u_min, v_min, u_max, v_max)`` in pixels, where ``u``
        is the row (travel) axis and ``v`` is the column (width) axis.
        ``u_max`` and ``v_max`` follow the Python half-open convention (the
        row/column *past* the last pixel in the region).
    centroid_px : tuple[float, float]
        Region centroid as ``(u_px, v_px)``.
    area_px : float
        Region area in pixels (used with the calibration to get mm²).
    """

    bbox_px: tuple[int, int, int, int]
    centroid_px: tuple[float, float]
    area_px: float


def extract_holes(
    mask: NDArray[Any],
    calibration: Calibration,
    config: Config,
) -> list[Hole]:
    """Extract connected perforation regions from a boolean mask.

    Parameters
    ----------
    mask : NDArray
        Boolean mask, ``True`` where a perforation is present. Rows are the
        ``u`` (travel) axis; columns are the ``v`` (cross) axis.
    calibration : Calibration
        Pixel-to-millimetre conversion factors for the ``u`` and ``v`` axes.
    config : Config
        Filtering thresholds (``min_hole_area_mm2``, ``max_hole_area_mm2``,
        ``min_solidity``) and, when ``hole_split_watershed`` is set, the
        watershed separation distance ``hole_split_min_distance_px``.

    Returns
    -------
    list[Hole]
        One :class:`Hole` per accepted region. Regions are rejected when their
        area in mm² falls outside ``[min_hole_area_mm2, max_hole_area_mm2]`` or
        their solidity is below ``min_solidity``. When ``hole_split_watershed``
        is enabled, perforations that touch are separated first.
    """
    from skimage import measure

    if config.hole_split_watershed:
        labels = _watershed_labels(
            np.asarray(mask, dtype=bool), config.hole_split_min_distance_px
        )
    else:
        labels = measure.label(mask)  # type: ignore[no-untyped-call]
    holes: list[Hole] = []
    for r in measure.regionprops(labels):  # type: ignore[no-untyped-call]
        area_mm2: float = (
            float(r.area) * calibration.mm_per_px_u * calibration.mm_per_px_v
        )
        if area_mm2 < config.min_hole_area_mm2:
            continue
        if area_mm2 > config.max_hole_area_mm2:
            continue
        if float(r.solidity) < config.min_solidity:
            continue
        min_row, min_col, max_row, max_col = r.bbox
        row, col = r.centroid
        holes.append(
            Hole(
                bbox_px=(
                    int(min_row),
                    int(min_col),
                    int(max_row),
                    int(max_col),
                ),
                centroid_px=(float(row), float(col)),
                area_px=float(r.area),
            )
        )
    return holes


def _watershed_labels(
    mask: NDArray[np.bool_], min_distance: int
) -> NDArray[np.int_]:
    """Split touching perforations with a distance-transform watershed.

    Peaks of the Euclidean distance transform (kept at least ``min_distance`` px
    apart) seed a watershed on ``-distance``, so blobs that merged in the binary
    mask are cut at their necks. Falls back to plain connected-component
    labelling when the mask is empty or no peaks are found.
    """
    from scipy import ndimage as ndi
    from skimage.feature import peak_local_max
    from skimage.measure import label
    from skimage.segmentation import watershed

    if not mask.any():
        return np.zeros(mask.shape, dtype=np.int_)
    distance = ndi.distance_transform_edt(mask)
    coords = peak_local_max(  # type: ignore[no-untyped-call]
        distance, min_distance=max(1, int(min_distance)), labels=mask
    )
    if len(coords) == 0:
        return np.asarray(label(mask), dtype=np.int_)  # type: ignore[no-untyped-call]
    peak_mask = np.zeros(distance.shape, dtype=bool)
    peak_mask[tuple(coords.T)] = True
    markers = label(peak_mask)  # type: ignore[no-untyped-call]
    result = watershed(-distance, markers, mask=mask)  # type: ignore[no-untyped-call]
    return np.asarray(result, dtype=np.int_)


class HoleExtraction:
    """Hole-extraction stage: finds connected perforation regions in the mask.

    Requires :attr:`~perfora.pipeline.context.PipelineContext.mask` to have
    been set by :class:`~perfora.pipeline.stages.preprocess.Preprocess`.
    Each connected component that passes the area and solidity thresholds
    in :class:`~perfora.config.Config` becomes one :class:`Hole` in
    :attr:`~perfora.pipeline.context.PipelineContext.holes`.
    """

    name: str = "holes"
    consumes: ClassVar[tuple[str, ...]] = ()
    produces: ClassVar[tuple[str, ...]] = ("holes",)

    def run(self, ctx: PipelineContext) -> None:
        """Detect holes in ``ctx.mask`` and store them in ``ctx.holes``.

        Parameters
        ----------
        ctx : PipelineContext
            Shared pipeline state.  Reads ``ctx.mask``; writes ``ctx.holes``.

        Raises
        ------
        PerforaError
            If ``ctx.mask`` is ``None`` (the Preprocess stage has not run).
        """
        if ctx.mask is None:
            raise PerforaError(
                "HoleExtraction requires ctx.mask; run Preprocess first."
            )
        ctx.holes = extract_holes(ctx.mask, ctx.image.calibration, ctx.config)

    def preview(self, ctx: PipelineContext) -> StagePreview:
        """Return a preview with bounding boxes for every detected hole.

        Parameters
        ----------
        ctx : PipelineContext
            Pipeline state after :meth:`run`.

        Returns
        -------
        StagePreview
            Base is ``"mask"``; overlays contain a single ``"boxes"`` entry
            with one ``(x, y, w, h)`` tuple per hole, where ``x = v_min``,
            ``y = u_min``, ``w = v_max - v_min``, ``h = u_max - u_min``.
        """
        boxes = [
            (
                h.bbox_px[1],               # x = v_min (col)
                h.bbox_px[0],               # y = u_min (row)
                h.bbox_px[3] - h.bbox_px[1],  # w = v_max - v_min
                h.bbox_px[2] - h.bbox_px[0],  # h = u_max - u_min
            )
            for h in ctx.holes
        ]
        return StagePreview(
            base="mask",
            overlays=(Overlay(kind="boxes", data=boxes),),
            summary={"n_holes": len(ctx.holes)},
        )

    def interaction_points(self, ctx: PipelineContext) -> list[InteractionField]:
        """Return an empty list — hole extraction has no user-adjustable knobs.

        Parameters
        ----------
        ctx : PipelineContext
            Pipeline state (unused).

        Returns
        -------
        list[InteractionField]
            Always empty.
        """
        return []
