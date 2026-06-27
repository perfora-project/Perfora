"""In-process format registry and entry-point plugin discovery.

Readers and writers register themselves under a canonical format id (hyphens
normalised from underscores).  External plugins register via the
``perfora.readers`` and ``perfora.writers`` package entry-point groups.
Discovery runs at most once per interpreter lifetime.

Public helpers
--------------
register_writer / register_reader
    Class decorators that insert a class into the in-process registry.
get_writer / get_reader
    Instantiate and return a concrete writer/reader by format id.
available_formats
    Merged view of every known format with read/write flags and extensions.
infer_format_from_path
    Longest-suffix extension match -> canonical format id.
read_document / write_document
    One-call helpers used by the public ``perfora`` API.
"""

from __future__ import annotations

import importlib.metadata
import os
from typing import Any, TypeVar

from perfora.errors import FormatError
from perfora.io.base import Reader, Writer
from perfora.model.document import RollDocument

# --------------------------------------------------------------------------- #
# In-process registries
# --------------------------------------------------------------------------- #
_WRITERS: dict[str, type[Writer]] = {}
_READERS: dict[str, type[Reader]] = {}
_entry_points_loaded: bool = False

_W = TypeVar("_W", bound=Writer)
_R = TypeVar("_R", bound=Reader)


def _canon(fmt: str) -> str:
    """Normalise a format id by replacing underscores with hyphens."""
    return fmt.replace("_", "-")


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
def register_writer(w: type[_W]) -> type[_W]:
    """Register *w* in the writer registry; usable as a class decorator.

    Parameters
    ----------
    w : type[Writer]
        Concrete writer class with ``format_id`` and ``extensions`` defined.

    Returns
    -------
    type[Writer]
        The same class, unchanged (decorator pass-through).
    """
    _WRITERS[_canon(w.format_id)] = w
    return w


def register_reader(r: type[_R]) -> type[_R]:
    """Register *r* in the reader registry; usable as a class decorator.

    Parameters
    ----------
    r : type[Reader]
        Concrete reader class with ``format_id`` and ``extensions`` defined.

    Returns
    -------
    type[Reader]
        The same class, unchanged (decorator pass-through).
    """
    _READERS[_canon(r.format_id)] = r
    return r


# --------------------------------------------------------------------------- #
# Entry-point discovery
# --------------------------------------------------------------------------- #
def _load_entry_points() -> None:
    """Discover and register external plugins via package entry points.

    Runs at most once per interpreter lifetime (guarded by the module-level
    ``_entry_points_loaded`` flag).  Individual plugin load failures are
    silently skipped so one bad plugin cannot break discovery.

    Entry-point groups
    ------------------
    ``perfora.writers``
        Each EP must load to a :class:`~perfora.io.base.Writer` subclass.
    ``perfora.readers``
        Each EP must load to a :class:`~perfora.io.base.Reader` subclass.
    """
    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True

    for ep in importlib.metadata.entry_points(group="perfora.writers"):
        try:
            cls = ep.load()
            register_writer(cls)
        except Exception:  # noqa: BLE001
            pass

    for ep in importlib.metadata.entry_points(group="perfora.readers"):
        try:
            cls = ep.load()
            register_reader(cls)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #
def get_writer(format_id: str) -> Writer:
    """Return an instantiated writer for *format_id*.

    Parameters
    ----------
    format_id : str
        Canonical or underscore-aliased format identifier.

    Returns
    -------
    Writer
        A fresh instance of the registered writer class.

    Raises
    ------
    FormatError
        If no writer is registered for *format_id*.  The message lists all
        available writer ids.
    """
    _load_entry_points()
    key = _canon(format_id)
    if key not in _WRITERS:
        available = ", ".join(sorted(_WRITERS)) or "(none)"
        raise FormatError(
            f"No writer registered for format {format_id!r}. "
            f"Available writer formats: {available}"
        )
    return _WRITERS[key]()


def get_reader(format_id: str) -> Reader:
    """Return an instantiated reader for *format_id*.

    Parameters
    ----------
    format_id : str
        Canonical or underscore-aliased format identifier.

    Returns
    -------
    Reader
        A fresh instance of the registered reader class.

    Raises
    ------
    FormatError
        If no reader is registered for *format_id*.  The message lists all
        available reader ids.
    """
    _load_entry_points()
    key = _canon(format_id)
    if key not in _READERS:
        available = ", ".join(sorted(_READERS)) or "(none)"
        raise FormatError(
            f"No reader registered for format {format_id!r}. "
            f"Available reader formats: {available}"
        )
    return _READERS[key]()


# --------------------------------------------------------------------------- #
# Introspection
# --------------------------------------------------------------------------- #
def available_formats() -> dict[str, dict[str, Any]]:
    """Return a mapping of all known formats and their capabilities.

    Triggers entry-point discovery on the first call.

    Returns
    -------
    dict[str, dict[str, Any]]
        ``{canonical_id: {"read": bool, "write": bool,
        "extensions": tuple[str, ...]}}`` where the extensions set is the
        union of the reader's and writer's extension tuples (no duplicates,
        writer order first).
    """
    _load_entry_points()
    all_ids: set[str] = set(_WRITERS) | set(_READERS)
    result: dict[str, dict[str, Any]] = {}
    for fmt_id in sorted(all_ids):
        writer_cls = _WRITERS.get(fmt_id)
        reader_cls = _READERS.get(fmt_id)
        exts: tuple[str, ...] = ()
        if writer_cls is not None:
            exts = exts + writer_cls.extensions
        if reader_cls is not None:
            for ext in reader_cls.extensions:
                if ext not in exts:
                    exts = exts + (ext,)
        result[fmt_id] = {
            "read": reader_cls is not None,
            "write": writer_cls is not None,
            "extensions": exts,
        }
    return result


def infer_format_from_path(
    path: str | os.PathLike[str],
) -> str:
    """Infer the canonical format id from a file path's extension.

    Uses longest-suffix matching so compound extensions such as
    ``".perfora.json"`` beat plain ``".json"`` when both are registered.
    Both readers and writers are searched; writer registration takes
    precedence for ties (same extension, same length).

    Parameters
    ----------
    path : str or os.PathLike[str]
        File path whose extension is matched.

    Returns
    -------
    str
        Canonical format id.

    Raises
    ------
    FormatError
        If no registered extension matches *path*.
    """
    _load_entry_points()
    path_str = str(path)

    # Build extension -> canonical-id map (writers take precedence)
    all_ext_map: dict[str, str] = {}
    for fmt_id, wcls in _WRITERS.items():
        for ext in wcls.extensions:
            all_ext_map[ext] = fmt_id
    for fmt_id, rcls in _READERS.items():
        for ext in rcls.extensions:
            if ext not in all_ext_map:
                all_ext_map[ext] = fmt_id

    best_ext: str = ""
    best_id: str | None = None
    for ext, fmt_id in all_ext_map.items():
        if path_str.endswith(ext) and len(ext) > len(best_ext):
            best_ext = ext
            best_id = fmt_id

    if best_id is None:
        available = ", ".join(sorted(all_ext_map)) or "(none)"
        raise FormatError(
            f"Cannot infer format from path {path_str!r}. "
            f"Known extensions: {available}"
        )
    return best_id


# --------------------------------------------------------------------------- #
# Top-level helpers
# --------------------------------------------------------------------------- #
def read_document(
    path: str | os.PathLike[str],
    format: str | None = None,
) -> RollDocument:
    """Read a :class:`~perfora.model.document.RollDocument` from *path*.

    Parameters
    ----------
    path : str or os.PathLike[str]
        Source file path.
    format : str or None, optional
        Explicit format id (canonical or underscore-aliased).  If ``None``,
        the format is inferred from *path*'s extension.

    Returns
    -------
    RollDocument
    """
    fmt = format if format is not None else infer_format_from_path(path)
    return get_reader(fmt).read(path)


def write_document(
    doc: RollDocument,
    path: str | os.PathLike[str],
    format: str | None = None,
) -> None:
    """Write *doc* to *path*.

    Parameters
    ----------
    doc : RollDocument
        The document to serialise.
    path : str or os.PathLike[str]
        Destination file path.
    format : str or None, optional
        Explicit format id (canonical or underscore-aliased).  If ``None``,
        the format is inferred from *path*'s extension.
    """
    fmt = format if format is not None else infer_format_from_path(path)
    get_writer(fmt).write(doc, path)
