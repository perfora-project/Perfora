"""perfora — digitize player-piano roll scans and videos.

The public API (``ImageSource``, ``VideoSource``, ``process``, ``read``,
``write``, ``Session``, ``register_*``) is wired up in Phase 0 once the
underlying modules exist. Importing this package must stay light: only the core
scientific stack (numpy/scipy/pandas/scikit-image/opencv) is touched here.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
