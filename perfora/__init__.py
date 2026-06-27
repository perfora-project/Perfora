"""perfora — digitize player-piano roll scans and videos.

Public API
----------
``process``
    One-shot decode of a source into a :class:`RollDocument`.
``read`` / ``write``
    Reversible I/O with runtime format selection (native JSON ships first).
``Session``
    Stepwise, previewable, override-driven execution for a UI / interactive CLI.
``register_reader`` / ``register_writer`` / ``available_formats``
    The pluggable I/O format registry.

``ImageSource`` and ``VideoSource`` are added in Phases 1 and 3.

Importing this package stays light: only the core scientific stack
(numpy/scipy/pandas/scikit-image/opencv) is touched, never the optional OCR/ML
backends.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from perfora.config import Config
from perfora.io.registry import (
    available_formats,
    read_document,
    register_reader,
    register_writer,
    write_document,
)
from perfora.pipeline.session import Session
from perfora.sources.image_source import ImageSource
from perfora.sources.video_source import VideoSource

if TYPE_CHECKING:
    from perfora.model.document import RollDocument
    from perfora.sources.base import Source

__version__ = "0.1.0"

__all__ = [
    "ImageSource",
    "Session",
    "VideoSource",
    "__version__",
    "available_formats",
    "process",
    "read",
    "register_reader",
    "register_writer",
    "write",
]


def process(
    source: Source,
    config: Config | None = None,
    text_engine: object | None = None,
) -> RollDocument:
    """Decode ``source`` into a :class:`RollDocument` in one shot.

    Equivalent to ``Session(source, config=config).run_all()`` with the default
    pipeline. The concrete decode stages are wired in Phase 1+.
    """
    from perfora.pipeline.pipeline import default_pipeline

    return default_pipeline(text_engine).run(source, config)


def read(path: str | os.PathLike[str], format: str | None = None) -> RollDocument:
    """Read a :class:`RollDocument` from ``path``.

    Parameters
    ----------
    path : str or os.PathLike
        Input file.
    format : str or None, optional
        Explicit format id (``-``/``_`` interchangeable). Inferred from the
        extension when ``None``.
    """
    return read_document(path, format=format)


def write(
    doc: RollDocument,
    path: str | os.PathLike[str],
    format: str | None = None,
) -> None:
    """Write ``doc`` to ``path``.

    Parameters
    ----------
    doc : RollDocument
        Document to serialize.
    path : str or os.PathLike
        Destination file.
    format : str or None, optional
        Explicit format id (``-``/``_`` interchangeable). Inferred from the
        extension when ``None``.
    """
    write_document(doc, path, format=format)
