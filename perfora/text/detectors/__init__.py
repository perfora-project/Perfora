"""Text detector backends for perfora.

Only :class:`ContourDetector` is re-exported here because it has no optional
dependencies.  Optional backends (``EasyOCRDetector``) must be imported
explicitly to avoid pulling in heavy ML libraries at package import time.
"""

from __future__ import annotations

from perfora.text.detectors.contour import ContourDetector

__all__ = ["ContourDetector"]
