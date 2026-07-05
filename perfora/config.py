"""Pipeline configuration dataclass."""

from __future__ import annotations

import dataclasses
from typing import cast

__all__ = ["Config"]


@dataclasses.dataclass(frozen=True, slots=True)
class Config:
    """Pipeline configuration; all thresholds recorded into Provenance.params.

    This dataclass is **frozen** — never mutate in place; use
    ``dataclasses.replace(cfg, field=value)`` to create a modified copy.

    All field values are scalar (``float | int | str | bool``) so the
    configuration serialises cleanly to JSON or YAML.
    """

    # -- Image: deskew / page detection (ALGORITHMS §1) ------------------- #
    #: Gaussian blur sigma (px) applied before edge detection in deskew.
    deskew_blur_sigma: float = 2.0
    #: Lower Canny threshold for page/edge detection.
    canny_low: float = 50.0
    #: Upper Canny threshold for page/edge detection.
    canny_high: float = 150.0
    #: ``approxPolyDP`` epsilon as a fraction of contour perimeter (page quad).
    page_approx_eps_frac: float = 0.02
    #: A detected page quad must cover at least this fraction of the image.
    min_page_area_frac: float = 0.2
    #: Background-keyed segmentation is trusted only if the roll occupies at
    #: least this fraction of the frame (else fall back to the page-quad path).
    min_roll_area_frac: float = 0.05
    #: Longest side (px) a scan is downscaled to before processing. Kept just
    #: under OpenCV's 32767 warp limit; the calibration is adjusted on downscale
    #: so millimetre geometry is unchanged. Lower it under memory pressure.
    max_image_px: int = 32000

    # -- Preprocess / binarization (§2) ----------------------------------- #
    #: Hole polarity: ``"auto"``, ``"bright_holes"``, ``"dark_holes"`` or
    #: ``"adaptive"``. A perforation is the brightness minority within the roll.
    binarization_mode: str = "auto"
    #: Connected components smaller than this (px) are removed as speckle.
    speckle_min_area_px: int = 9
    #: Square footprint side (px) for the binary opening that detaches blobs.
    opening_kernel_px: int = 3

    # -- Hole extraction (§3) --------------------------------------------- #
    #: Minimum perforation area (mm²); smaller blobs are rejected as noise.
    min_hole_area_mm2: float = 0.5
    #: Maximum perforation area (mm²); larger blobs are rejected as tears.
    max_hole_area_mm2: float = 200.0
    #: Minimum region solidity; rejects torn edges and text strokes.
    min_solidity: float = 0.7
    #: Split touching perforations with a distance-transform watershed. Off by
    #: default; best for round holes that merge side-by-side, and can over-split
    #: long slot-shaped perforations, so leave off for slot rolls.
    hole_split_watershed: bool = False
    #: Minimum separation (px) between hole centres for the watershed peak
    #: detection — roughly the smallest hole spacing you want resolved.
    hole_split_min_distance_px: int = 4

    # -- Lane finding (§4) ------------------------------------------------ #
    #: Gaussian smoothing (px) of the cross-axis hole-density profile.
    density_sigma_px: float = 1.5
    #: Smallest lane pitch (px) the autocorrelation search will consider.
    min_pitch_px: int = 3
    #: Largest lane pitch (px) the autocorrelation search will consider.
    max_pitch_px: int = 200
    #: FFT bins below this are zeroed when estimating the pitch frequency.
    min_freq_bin: int = 2
    #: Relative tolerance for the autocorrelation/FFT pitch agreement check.
    pitch_agree_tol: float = 0.05
    #: Number of overlapping ``u`` windows used for the robust pitch consensus.
    n_windows: int = 8
    #: A hole farther than this fraction of the pitch from a lane centre is
    #: flagged ``ambiguous_lane``.
    lane_tol_frac: float = 0.25
    #: Largest absolute column-vs-row slope searched to make lanes vertical
    #: (residual-skew refinement); ~0.7 degrees mops up drift a coarse deskew
    #: leaves on long rolls.
    lane_skew_max: float = 0.012
    #: Number of slopes tried across the residual-skew search range.
    lane_skew_steps: int = 61

    # -- Note assembly (§5) ----------------------------------------------- #
    #: Max gap (mm, along the roll) between consecutive perforations in a lane
    #: that is merged into one note. Small and resolution-independent so only
    #: true chain-perforation gaps merge, not distinct notes; ``0.0`` disables
    #: merging entirely (every perforation becomes its own note).
    bridge_gap_mm: float = 0.5
    #: Notes shorter than this (mm) are flagged ``short_or_noisy_note``.
    min_note_len_mm: float = 1.0
    #: Notes below this confidence are flagged for review.
    note_conf_min: float = 0.5

    # -- Video slit-scan (§6) --------------------------------------------- #
    #: Minimum ``phaseCorrelate`` response before the optical-flow fallback.
    min_corr_response: float = 0.3
    #: Slit width (px) sampled per unit of travel during reconstruction.
    slice_width_px: int = 1
    #: Frames used to auto-detect the travel direction.
    travel_detect_frames: int = 30

    # -- Text scope + association (§7) ------------------------------------ #
    #: Leading ``u`` fraction classified as ``global_header``.
    header_frac: float = 0.12
    #: Trailing ``u`` fraction classified as ``global_footer``.
    footer_frac: float = 0.12
    #: Margin (mm) added around the lane band when testing play-area membership.
    play_margin_mm: float = 2.0
    #: Padding (mm) when associating a timeline text box with the notes it spans.
    assoc_pad_mm: float = 2.0
    #: Restrict timeline association to notes whose lane is near the box in ``v``.
    assoc_lane_aware: bool = True

    # -- Review thresholds (§8) ------------------------------------------- #
    #: Recognised text below this confidence is flagged ``low_ocr_confidence``.
    ocr_conf_min: float = 0.5
    #: A text box within this distance (mm) of a band boundary is flagged
    #: ``uncertain_scope``.
    scope_edge_mm: float = 2.0

    def to_params(self) -> dict[str, float | int | str | bool]:
        """Return all fields as a flat dict.

        Returns
        -------
        dict[str, float | int | str | bool]
            Mapping of field name to its current value.  Suitable for
            recording into ``Provenance.params``.
        """
        return cast(
            dict[str, float | int | str | bool],
            dataclasses.asdict(self),
        )
