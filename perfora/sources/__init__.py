"""Input sources: everything normalizes to a canonical :class:`RollImage`.

``ImageSource`` (flat scans) and ``VideoSource`` (slit-scan) arrive in Phase 1
and Phase 3; the container and protocol live in :mod:`perfora.sources.base`.
"""

from __future__ import annotations

from perfora.sources.base import RollImage, Source
from perfora.sources.image_source import ImageSource

__all__ = ["ImageSource", "RollImage", "Source"]
