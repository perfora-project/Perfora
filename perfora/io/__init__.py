"""perfora I/O layer: readers, writers, format registry, and built-in codecs.

Import order matters here: registry symbols are imported first so they are
available as module attributes, then the built-in format modules are imported
as a side effect — their ``@register_writer`` / ``@register_reader``
decorators fire on import and insert the classes into the in-process
registry.
"""

from __future__ import annotations

from perfora.io.base import Reader, Writer
from perfora.io.formats import native_json as _native_json  # noqa: F401
from perfora.io.registry import (
    available_formats,
    get_reader,
    get_writer,
    infer_format_from_path,
    read_document,
    register_reader,
    register_writer,
    write_document,
)

__all__ = [
    "Reader",
    "Writer",
    "register_reader",
    "register_writer",
    "get_reader",
    "get_writer",
    "available_formats",
    "read_document",
    "write_document",
    "infer_format_from_path",
]
