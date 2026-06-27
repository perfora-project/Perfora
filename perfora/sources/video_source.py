"""Video source: reconstruct one flat strip from a moving-roll video (§6).

Because piano rolls are highly periodic, feature-based panorama stitching
(SIFT/ORB + homography, ``cv2.Stitcher``) mismatches repeated holes and ghosts.
This uses a **push-broom / slit-scan** reconstruction instead: measure the
inter-frame translation (sub-pixel ``cv2.phaseCorrelate``, with a Farneback
optical-flow fallback) and append the slit (centre) line proportionally to the
measured travel, so variable feed speed does not distort the ``u`` scale.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from numpy.typing import NDArray

from perfora.config import Config
from perfora.errors import VideoReconstructionError
from perfora.model.calibration import Calibration
from perfora.model.document import Provenance
from perfora.sources.base import RollImage

if TYPE_CHECKING:
    from collections.abc import Iterator

    from perfora.pipeline.progress import ProgressReporter

__all__ = ["VideoSource", "reconstruct"]


def _gray_roi(
    frame: NDArray[Any], roi: tuple[int, int, int, int] | None
) -> NDArray[np.float32]:
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    if roi is not None:
        x, y, w, h = roi
        g = g[y : y + h, x : x + w]
    return np.asarray(g, dtype=np.float32)


def _translation(
    prev: NDArray[np.float32],
    cur: NDArray[np.float32],
    window: NDArray[Any],
    min_corr_response: float,
) -> tuple[float, float]:
    """Return ``(du, dv)`` = (travel-row, lateral-col) shift between two frames."""
    (dx, dy), response = cv2.phaseCorrelate(prev, cur, window)
    if response < min_corr_response:
        flow = cv2.calcOpticalFlowFarneback(  # type: ignore[call-overload]
            prev, cur, None, 0.5, 3, 15, 3, 5, 1.2, 0
        )
        dy = float(np.median(flow[..., 1]))
        dx = float(np.median(flow[..., 0]))
    return (float(dy), float(dx))  # (du along rows, dv along cols)


def _corrected_row(
    g: NDArray[np.float32], center: int, cum_dv: float
) -> NDArray[np.uint8]:
    """Sample the slit (centre) line, undoing accumulated lateral drift."""
    row = g[center, :]
    shift = -int(round(cum_dv))
    if shift:
        row = np.roll(row, shift)
    return np.clip(row, 0, 255).astype(np.uint8)


def reconstruct(
    frames: list[NDArray[Any]],
    *,
    roi: tuple[int, int, int, int] | None,
    travel: str,
    config: Config,
    progress: ProgressReporter | None = None,
) -> NDArray[np.uint8]:
    """Reconstruct a flat strip from a sequence of frames via slit-scan.

    Raises
    ------
    VideoReconstructionError
        If fewer than two frames are usable or no travel is observed.
    """
    if len(frames) < 2:
        raise VideoReconstructionError("need at least two frames to reconstruct")

    prev = _gray_roi(frames[0], roi)
    h, w = prev.shape
    center = h // 2
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)

    if progress is not None:
        progress.on_stage_start("video", total=len(frames))

    strip_rows: list[NDArray[np.uint8]] = [_corrected_row(prev, center, 0.0)]
    acc = 0.0
    cum_dv = 0.0
    signed_du = 0.0
    for i in range(1, len(frames)):
        if progress is not None and progress.cancelled():
            break
        g = _gray_roi(frames[i], roi)
        du, dv = _translation(prev, g, win, config.min_corr_response)
        signed_du += du
        cum_dv += dv
        acc += abs(du)
        while acc >= 1.0:
            strip_rows.append(_corrected_row(g, center, cum_dv))
            acc -= 1.0
        prev = g
        if progress is not None:
            progress.on_progress("video", i + 1, len(frames))

    if len(strip_rows) < 2:
        raise VideoReconstructionError(
            "no travel observed; correlation may have collapsed"
        )

    strip = np.stack(strip_rows, axis=0)
    flip = signed_du > 0 if travel == "auto" else travel == "down"
    if flip:
        strip = np.flipud(strip)
    return np.ascontiguousarray(strip, dtype=np.uint8)


class VideoSource:
    """Reconstruct a :class:`RollImage` from a moving-roll video via slit-scan.

    Parameters
    ----------
    src : str, os.PathLike, or sequence of frames
        A video file path, or an in-memory sequence/array of BGR frames.
    roi : tuple[int, int, int, int] or None, optional
        ``(x, y, w, h)`` crop applied to every frame before reconstruction.
    travel : str, optional
        ``"auto"`` (infer direction), ``"up"`` or ``"down"``.
    dpi, physical_width_mm : float or None, optional
        Calibration inputs, as for :class:`ImageSource`.
    config : Config or None, optional
    progress : ProgressReporter or None, optional
        Receives per-frame progress and is polled for cooperative cancellation.
    """

    def __init__(
        self,
        src: str | os.PathLike[str] | list[NDArray[Any]] | NDArray[Any],
        *,
        roi: tuple[int, int, int, int] | None = None,
        travel: str = "auto",
        dpi: float | None = None,
        physical_width_mm: float | None = None,
        config: Config | None = None,
        progress: ProgressReporter | None = None,
    ) -> None:
        self._src = src
        self._roi = roi
        self._travel = travel
        self._dpi = dpi
        self._physical_width_mm = physical_width_mm
        self._config = config if config is not None else Config()
        self._progress = progress

    def _load_frames(self) -> list[NDArray[Any]]:
        if isinstance(self._src, (str, os.PathLike)):
            return list(_read_video_frames(self._src))
        return [np.asarray(f) for f in self._src]

    def to_roll_image(self) -> RollImage:
        """Reconstruct the strip and wrap it as a calibrated RollImage."""
        import perfora

        frames = self._load_frames()
        strip = reconstruct(
            frames,
            roi=self._roi,
            travel=self._travel,
            config=self._config,
            progress=self._progress,
        )
        w_px = strip.shape[1]
        if self._dpi is not None:
            mm = 25.4 / self._dpi
            cal = Calibration(mm, mm, self._dpi, source="dpi")
        elif self._physical_width_mm is not None:
            mmv = self._physical_width_mm / w_px
            cal = Calibration(mmv, mmv, None, source="physical_width")
        else:
            cal = Calibration(1.0, 1.0, None, source="assumed")
        name = (
            os.path.basename(str(self._src))
            if isinstance(self._src, (str, os.PathLike))
            else "frames"
        )
        prov = Provenance(
            source_type="video",
            source_name=name,
            perfora_version=perfora.__version__,
            created_utc=datetime.now(UTC).isoformat(),
            params={},
        )
        return RollImage(
            gray=strip,
            calibration=cal,
            provenance=prov,
            color=cv2.cvtColor(strip, cv2.COLOR_GRAY2BGR),
        )


def _read_video_frames(path: str | os.PathLike[str]) -> Iterator[NDArray[Any]]:
    cap = cv2.VideoCapture(str(path))
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield frame
    finally:
        cap.release()
