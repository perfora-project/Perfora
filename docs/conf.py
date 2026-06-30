"""Sphinx configuration for the perfora documentation.

Builds with::

    uv sync --extra docs
    uv run sphinx-build -b html docs docs/_build/html
"""

from __future__ import annotations

import importlib.metadata
import os
import sys

sys.path.insert(0, os.path.abspath(".."))

# -- Project ---------------------------------------------------------------- #
project = "perfora"
author = "RedRem95"
copyright = "2026, RedRem95"  # noqa: A001
try:
    release = importlib.metadata.version("perfora")
except importlib.metadata.PackageNotFoundError:
    release = "0.1.0"
version = ".".join(release.split(".")[:2])

# -- Extensions ------------------------------------------------------------- #
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "myst_parser",
]

# -- Autodoc / napoleon ----------------------------------------------------- #
autosummary_generate = True
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
}
napoleon_numpy_docstring = True
napoleon_google_docstring = False

# Optional backends are imported lazily and are absent from the docs env; mock
# them so importing the package for autodoc never pulls heavy ML dependencies.
autodoc_mock_imports = [
    "torch",
    "transformers",
    "easyocr",
    "pytesseract",
    "doctr",
    "mido",
]

# -- MyST (Markdown) -------------------------------------------------------- #
myst_enable_extensions = ["colon_fence", "deflist", "fieldlist", "attrs_block"]
myst_heading_anchors = 3

# -- Intersphinx ------------------------------------------------------------ #
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
}

# -- General ---------------------------------------------------------------- #
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "assets/README*"]
suppress_warnings = ["myst.header"]

# -- HTML ------------------------------------------------------------------- #
html_theme = "furo"
html_title = "perfora"
html_logo = "assets/perfora-logo.svg"
html_static_path = []
