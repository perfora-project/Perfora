"""Render-agnostic stage previews.

A :class:`StagePreview` is *data*: a base-image selector plus a tuple of
:class:`Overlay` payloads and a short ``summary`` dict. A web UI, a desktop UI
and the terminal all consume the same structure. :meth:`StagePreview.rasterize`
is an optional convenience that bakes the overlays onto an image with OpenCV
(already a core dependency) for quick display or writing a PNG.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from perfora.sources.base import RollImage


@dataclass(frozen=True, slots=True)
class Overlay:
    """A single geometry payload to draw on a preview base image.

    Parameters
    ----------
    kind : str
        One of ``"quad"``, ``"polyline"``, ``"boxes"``, ``"profile"``,
        ``"lanes"``, ``"spans"``, ``"labels"``.
    data : object
        Geometry payload appropriate to ``kind`` (points, boxes, a 1-D profile,
        spans, ...). See :meth:`StagePreview.rasterize` for accepted shapes.
    space : str
        ``"px"`` or ``"mm"`` — the coordinate space of ``data``.
    style : dict
        Colour / label / opacity hints (renderer-specific, all optional).
    """

    kind: str
    data: object
    space: str = "px"
    style: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StagePreview:
    """A render-agnostic preview of a stage's result.

    Parameters
    ----------
    base : str
        Image to draw on: ``"color"``, ``"gray"``, ``"mask"``, ``"strip"`` or
        ``"none"``.
    overlays : tuple[Overlay, ...]
        Overlays to draw, in order.
    summary : dict
        Short facts for a status line (e.g. ``{"pitch_mm": 3.18}``).
    legend : tuple[tuple[str, tuple[int, int, int]], ...]
        Optional ``(label, BGR-colour)`` entries drawn as a legend key on the
        rasterized image, so overlay colours are self-explanatory.
    """

    base: str
    overlays: tuple[Overlay, ...] = ()
    summary: dict[str, str | float | int] = field(default_factory=dict)
    legend: tuple[tuple[str, tuple[int, int, int]], ...] = ()

    def rasterize(self, image: RollImage) -> NDArray[Any]:
        """Bake the overlays onto a BGR image and return it.

        Parameters
        ----------
        image : RollImage
            Source image whose ``gray``/``color`` provides the base raster. The
            ``mask`` base is read from ``image`` only if present; otherwise a
            blank canvas the size of ``gray`` is used.

        Returns
        -------
        NDArray
            A 3-channel ``uint8`` BGR image with overlays drawn.
        """
        import cv2

        canvas = self._base_canvas(image)
        for ov in self.overlays:
            _draw_overlay(cv2, canvas, ov)
        if self.legend:
            _draw_legend(cv2, canvas, self.legend)
        return canvas

    def _base_canvas(self, image: RollImage) -> NDArray[Any]:
        import cv2

        gray = image.gray
        if self.base == "color" and image.color is not None:
            base = np.ascontiguousarray(image.color)
            if base.ndim == 2:
                base = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
            return base.astype(np.uint8, copy=False)
        if self.base == "none":
            h, w = gray.shape[:2]
            return np.zeros((h, w, 3), dtype=np.uint8)
        # "gray" | "mask" | "strip" | fallback: promote single channel to BGR
        g = np.asarray(gray)
        if g.dtype != np.uint8:
            g = _to_uint8(g)
        return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def _to_uint8(arr: NDArray[Any]) -> NDArray[Any]:
    a = np.asarray(arr, dtype=np.float64)
    if not a.size:
        return np.zeros(a.shape, dtype=np.uint8)
    lo, hi = float(a.min()), float(a.max())
    if hi <= lo:
        return np.zeros(a.shape, dtype=np.uint8)
    scaled = (a - lo) / (hi - lo) * 255.0
    return scaled.astype(np.uint8)


def _color(
    style: dict[str, Any], default: tuple[int, int, int]
) -> tuple[int, int, int]:
    c = style.get("color", default)
    return (int(c[0]), int(c[1]), int(c[2]))


def _draw_legend(
    cv2: Any,
    canvas: NDArray[Any],
    entries: tuple[tuple[str, tuple[int, int, int]], ...],
) -> None:
    """Draw a colour key in the top-left corner over a translucent panel."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.5
    thick = 1
    pad, swatch, gap, row_h = 8, 22, 8, 20
    text_w = max(
        (cv2.getTextSize(label, font, scale, thick)[0][0] for label, _ in entries),
        default=0,
    )
    box_w = pad + swatch + gap + text_w + pad
    box_h = pad + row_h * len(entries) + pad
    box_w = min(box_w, canvas.shape[1])
    box_h = min(box_h, canvas.shape[0])

    panel = canvas[:box_h, :box_w].astype(np.float64)
    panel *= 0.35  # darken behind the legend for contrast
    canvas[:box_h, :box_w] = panel.astype(np.uint8)

    y = pad + row_h // 2
    for label, color in entries:
        bgr = (int(color[0]), int(color[1]), int(color[2]))
        cv2.line(canvas, (pad, y), (pad + swatch, y), bgr, 3, cv2.LINE_AA)
        cv2.putText(
            canvas,
            label,
            (pad + swatch + gap, y + 5),
            font,
            scale,
            (255, 255, 255),
            thick,
            cv2.LINE_AA,
        )
        y += row_h


def _draw_overlay(cv2: Any, canvas: NDArray[Any], ov: Overlay) -> None:
    """Draw one overlay onto ``canvas`` in place (best-effort, by ``kind``)."""
    style = ov.style
    data: Any = ov.data
    if ov.kind == "boxes":
        # data: iterable of (x, y, w, h)
        color = _color(style, (0, 200, 0))
        for x, y, w, h in data:
            cv2.rectangle(canvas, (int(x), int(y)), (int(x + w), int(y + h)), color, 1)
    elif ov.kind in ("quad", "polyline"):
        # data: iterable of (x, y)
        color = _color(style, (0, 128, 255))
        pts = np.asarray(list(data), dtype=np.int32)
        if pts.size:
            closed = ov.kind == "quad"
            cv2.polylines(canvas, [pts.reshape(-1, 1, 2)], closed, color, 2)
    elif ov.kind == "lanes":
        # data: iterable of v positions (columns, px); draws vertical lines
        color = _color(style, (255, 128, 0))
        h = canvas.shape[0]
        for v in data:
            cv2.line(canvas, (int(v), 0), (int(v), h), color, 1)
    elif ov.kind == "spans":
        # data: iterable of (u0, v0, u1, v1) boxes in px (note spans)
        color = _color(style, (0, 0, 255))
        for u0, v0, u1, v1 in data:
            cv2.rectangle(
                canvas, (int(v0), int(u0)), (int(v1), int(u1)), color, -1
            )
    elif ov.kind == "labels":
        # data: iterable of (x, y, text)
        color = _color(style, (255, 255, 255))
        for x, y, text in data:
            cv2.putText(
                canvas, str(text), (int(x), int(y)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA,
            )
    elif ov.kind == "profile":
        # data: 1-D array sampled across v; drawn as a curve along the top
        color = _color(style, (0, 255, 255))
        prof = np.asarray(list(data), dtype=np.float64)
        if prof.size:
            h = canvas.shape[0]
            m = float(prof.max()) or 1.0
            ys = (h - 1) - (prof / m * (h - 1)).astype(np.int32)
            xs = np.arange(prof.size, dtype=np.int32)
            curve = np.stack([xs, ys], axis=1).reshape(-1, 1, 2)
            cv2.polylines(canvas, [curve], False, color, 1)
