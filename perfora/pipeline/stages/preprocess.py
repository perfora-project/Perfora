"""Binarization stage: converts the canonical grey image to a Boolean mask.

The mask is ``True`` where a perforation is present. The strategy (polarity
and local vs global threshold) is controlled by
:attr:`~perfora.config.Config.binarization_mode` and can be overridden
per-run via :attr:`~perfora.pipeline.overrides.Overrides.binarization_mode`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

import numpy as np
from numpy.typing import NDArray

from perfora.pipeline.preview import StagePreview
from perfora.pipeline.stages.base import InteractionField

if TYPE_CHECKING:
    from perfora.pipeline.context import PipelineContext

__all__ = ["Preprocess", "binarize", "binarize_in_roll"]

_MODES: list[object] = ["auto", "bright_holes", "dark_holes", "adaptive"]


def binarize(
    gray: NDArray[Any],
    mode: str,
    *,
    speckle_min_area_px: int,
    opening_kernel_px: int,
) -> NDArray[np.bool_]:
    """Convert a grey image to a boolean perforation mask.

    Parameters
    ----------
    gray : NDArray
        Single-channel grayscale image (uint8 or float).
    mode : str
        Binarization strategy — one of ``"auto"``, ``"bright_holes"``,
        ``"dark_holes"``, ``"adaptive"``.
    speckle_min_area_px : int
        Connected components strictly smaller than this (in pixels) are
        removed after thresholding.
    opening_kernel_px : int
        Side length (in pixels) of the square footprint used for binary
        opening.  Values ``< 1`` are treated as 1 (no-op).

    Returns
    -------
    NDArray[np.bool_]
        Boolean mask, same spatial shape as ``gray``, ``True`` at perforations.

    Notes
    -----
    The ``"auto"`` mode applies the *minority rule*: compute a global Otsu
    threshold; whichever side (bright or dark) occupies **less than half** the
    pixels is assumed to be the perforations, because holes are always a
    minority of pixels on a roll image.
    """
    from skimage import filters

    g = np.asarray(gray, dtype=np.float64)

    resolved = mode
    if resolved == "auto":
        otsu_thr = float(filters.threshold_otsu(g))  # type: ignore[no-untyped-call]
        bright_frac = float(np.mean(g > otsu_thr))
        resolved = "bright_holes" if bright_frac < 0.5 else "dark_holes"

    raw: NDArray[Any]
    if resolved == "bright_holes":
        thr = float(filters.threshold_otsu(g))  # type: ignore[no-untyped-call]
        raw = g > thr
    elif resolved == "dark_holes":
        thr = float(filters.threshold_otsu(g))  # type: ignore[no-untyped-call]
        raw = g < thr
    elif resolved == "adaptive":
        global_thr = float(filters.threshold_otsu(g))  # type: ignore[no-untyped-call]
        bright_frac = float(np.mean(g > global_thr))
        bright_minority = bright_frac < 0.5
        local_thr: NDArray[Any] = filters.threshold_sauvola(  # type: ignore[no-untyped-call]
            g, window_size=25
        )
        raw = g > local_thr if bright_minority else g < local_thr
    else:
        raise ValueError(f"Unknown binarization mode: {mode!r}")

    # max_size N removes objects with size <= N (i.e. keeps objects with size
    # >= N+1), so max_size = speckle_min_area_px - 1 mirrors the old
    # min_size = speckle_min_area_px semantics (keep size >= speckle_min_area_px).
    return _clean(raw, speckle_min_area_px, opening_kernel_px)


def _clean(
    raw: NDArray[Any], speckle_min_area_px: int, opening_kernel_px: int
) -> NDArray[np.bool_]:
    """Remove speckle and detach touching blobs from a raw boolean mask."""
    from skimage import morphology

    cleaned = morphology.remove_small_objects(
        np.asarray(raw, dtype=np.bool_),
        max_size=max(0, speckle_min_area_px - 1),
    )
    fp = np.ones((max(1, opening_kernel_px), max(1, opening_kernel_px)), dtype=bool)
    opened = morphology.opening(cleaned, footprint=fp)
    return cast("NDArray[np.bool_]", np.asarray(opened, dtype=np.bool_))


def binarize_in_roll(
    gray: NDArray[Any],
    roll_mask: NDArray[np.bool_],
    mode: str,
    *,
    speckle_min_area_px: int,
    opening_kernel_px: int,
) -> NDArray[np.bool_]:
    """Binarize **within** a roll mask: a perforation is a spot that looks like
    the background (the bed seen through the hole).

    The polarity is decided from the roll's own pixels (the perforations are a
    minority), so this works whether holes are brighter (white bed) or darker
    (dark backing) than the roll material, and background outside the roll can
    never be mistaken for a hole.
    """
    from skimage import filters

    g = np.asarray(gray, dtype=np.float64)
    roll_vals = g[roll_mask]
    if roll_vals.size == 0:
        return np.zeros(g.shape, dtype=np.bool_)
    thr = float(filters.threshold_otsu(roll_vals))  # type: ignore[no-untyped-call]

    resolved = mode
    if resolved in ("auto", "adaptive"):
        bright_frac = float(np.mean(roll_vals > thr))
        resolved = "bright_holes" if bright_frac < 0.5 else "dark_holes"
    raw = (g > thr) if resolved == "bright_holes" else (g < thr)
    raw = raw & roll_mask
    return _clean(raw, speckle_min_area_px, opening_kernel_px)


class Preprocess:
    """Binarization stage — converts the grey roll image to a perforation mask.

    Reads :attr:`~perfora.sources.base.RollImage.gray` from the context,
    applies the configured binarization strategy, cleans up speckle and
    small gaps, and stores the result as
    :attr:`~perfora.pipeline.context.PipelineContext.mask`.
    """

    name: str = "preprocess"
    consumes: ClassVar[tuple[str, ...]] = ("binarization_mode",)
    produces: ClassVar[tuple[str, ...]] = ("mask",)

    def run(self, ctx: PipelineContext) -> None:
        """Compute the perforation mask and store it in ``ctx.mask``.

        Parameters
        ----------
        ctx : PipelineContext
            Shared pipeline state.  ``ctx.image.gray`` is read;
            ``ctx.mask`` is written as a ``bool`` array.
        """
        mode = ctx.overrides.binarization_mode or ctx.config.binarization_mode
        roll_mask = ctx.image.roll_mask
        if roll_mask is not None:
            ctx.mask = binarize_in_roll(
                ctx.image.gray,
                np.asarray(roll_mask, dtype=np.bool_),
                mode,
                speckle_min_area_px=ctx.config.speckle_min_area_px,
                opening_kernel_px=ctx.config.opening_kernel_px,
            )
        else:
            ctx.mask = binarize(
                ctx.image.gray,
                mode,
                speckle_min_area_px=ctx.config.speckle_min_area_px,
                opening_kernel_px=ctx.config.opening_kernel_px,
            )

    def preview(self, ctx: PipelineContext) -> StagePreview:
        """Return a preview summarising the mask.

        Parameters
        ----------
        ctx : PipelineContext
            Pipeline state after :meth:`run`.

        Returns
        -------
        StagePreview
            Base is ``"mask"``; summary carries ``hole_fraction`` (fraction of
            ``True`` pixels) and the resolved ``mode`` string.
        """
        mode = ctx.overrides.binarization_mode or ctx.config.binarization_mode
        hole_frac: float = (
            float(np.asarray(ctx.mask).mean()) if ctx.mask is not None else 0.0
        )
        return StagePreview(
            base="mask",
            overlays=(),
            summary={"hole_fraction": hole_frac, "mode": mode},
        )

    def interaction_points(self, ctx: PipelineContext) -> list[InteractionField]:
        """Return the one editable decision for the binarization stage.

        Parameters
        ----------
        ctx : PipelineContext
            Pipeline state (used to read the current effective mode).

        Returns
        -------
        list[InteractionField]
            A single ``InteractionField`` for ``binarization_mode`` with
            ``type="enum"`` and ``options`` listing all four valid values.
        """
        mode = ctx.overrides.binarization_mode or ctx.config.binarization_mode
        return [
            InteractionField(
                key="binarization_mode",
                type="enum",
                label="Binarization mode",
                current=mode,
                options=list(_MODES),
                constraints=None,
            )
        ]
