"""Abstract base classes for perfora I/O readers and writers.

All concrete format implementations subclass :class:`Writer` or :class:`Reader`,
declare ``format_id`` and ``extensions`` as class-level attributes, implement the
single abstract method, and register themselves via the decorators exposed by
:mod:`perfora.io.registry`.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import ClassVar

from perfora.model.document import RollDocument


class Writer(ABC):
    """Abstract base for format writers.

    Concrete subclasses must declare :attr:`format_id` and
    :attr:`extensions` as class variables and implement :meth:`write`.
    Register a concrete writer with
    :func:`perfora.io.registry.register_writer` (usable as a decorator).

    Parameters
    ----------
    format_id : str
        Canonical format identifier, e.g. ``"native-json"``. Use hyphens,
        not underscores (the registry normalises either form).
    extensions : tuple[str, ...]
        File extensions this writer owns, e.g. ``(".perfora.json",)``.
        Compound extensions are supported and preferred over simple ones
        during format inference (longest match wins).
    """

    format_id: ClassVar[str]
    extensions: ClassVar[tuple[str, ...]]

    @abstractmethod
    def write(
        self, doc: RollDocument, path: str | os.PathLike[str]
    ) -> None:
        """Serialise *doc* and write it to *path*.

        Parameters
        ----------
        doc : RollDocument
            The document to serialise.
        path : str or os.PathLike[str]
            Destination file path. The file is created or overwritten.
        """
        ...


class Reader(ABC):
    """Abstract base for format readers.

    Concrete subclasses must declare :attr:`format_id` and
    :attr:`extensions` as class variables and implement :meth:`read`.
    Register a concrete reader with
    :func:`perfora.io.registry.register_reader` (usable as a decorator).

    Parameters
    ----------
    format_id : str
        Canonical format identifier, e.g. ``"native-json"``.
    extensions : tuple[str, ...]
        File extensions this reader handles, e.g. ``(".perfora.json",)``.
    """

    format_id: ClassVar[str]
    extensions: ClassVar[tuple[str, ...]]

    @abstractmethod
    def read(self, path: str | os.PathLike[str]) -> RollDocument:
        """Read a document from *path* and return the reconstructed model.

        Parameters
        ----------
        path : str or os.PathLike[str]
            Source file path.

        Returns
        -------
        RollDocument
            The fully reconstructed document.
        """
        ...
