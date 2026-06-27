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

    # Image: deskew / page detection (ALGORITHMS §1)
    deskew_blur_sigma: float = 2.0
    canny_low: float = 50.0
    canny_high: float = 150.0
    page_approx_eps_frac: float = 0.02
    min_page_area_frac: float = 0.2

    # Preprocess / binarization (§2)
    binarization_mode: str = "auto"  # "auto"|"bright_holes"|"dark_holes"|"adaptive"
    speckle_min_area_px: int = 9
    opening_kernel_px: int = 3

    # Hole extraction (§3)
    min_hole_area_mm2: float = 0.5
    max_hole_area_mm2: float = 200.0
    min_solidity: float = 0.7

    # Lane finding (§4)
    density_sigma_px: float = 1.5
    min_pitch_px: int = 3
    max_pitch_px: int = 200
    min_freq_bin: int = 2
    pitch_agree_tol: float = 0.05
    n_windows: int = 8
    lane_tol_frac: float = 0.25

    # Note assembly (§5)
    bridge_gap_frac: float = 0.5  # bridge gap as a fraction of lane pitch
    min_note_len_mm: float = 1.0
    note_conf_min: float = 0.5

    # Video slit-scan (§6)
    min_corr_response: float = 0.3
    slice_width_px: int = 1
    travel_detect_frames: int = 30

    # Text scope + association (§7)
    header_frac: float = 0.12
    footer_frac: float = 0.12
    play_margin_mm: float = 2.0
    assoc_pad_mm: float = 2.0
    assoc_lane_aware: bool = True

    # Review thresholds (§8)
    ocr_conf_min: float = 0.5
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
