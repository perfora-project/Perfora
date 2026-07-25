"""Bundled example data: a sample roll and the quickstart notebook.

These files exist so that someone who has just installed perfora can run the
whole pipeline immediately, before owning a scan of their own. Copy them into a
working directory with the CLI::

    perfora sample ./my-first-roll

The sample roll is **synthetic** — rendered from a known specification rather
than scanned from a physical roll — so its ground truth is exact and its
provenance is unambiguous.

Sample roll ground truth
------------------------
=========================  ==========
Scan resolution            300 dpi
Lane pitch                 3.0 mm
Lanes                      25
Notes                      34
Roll length                170 mm
=========================  ==========

Decoding it with ``--dpi 300`` should recover 25 lanes, a pitch within a few
hundredths of a millimetre of 3.0, and exactly 34 notes.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

__all__ = [
    "SAMPLE_ROLL_DPI",
    "SAMPLE_ROLL_LANES",
    "SAMPLE_ROLL_LENGTH_MM",
    "SAMPLE_ROLL_NOTES",
    "SAMPLE_ROLL_PITCH_MM",
    "copy_samples",
    "quickstart_notebook_path",
    "sample_roll_path",
]

#: Scan resolution the sample roll was rendered at (dots per inch).
SAMPLE_ROLL_DPI = 300.0
#: True lane pitch of the sample roll, in millimetres.
SAMPLE_ROLL_PITCH_MM = 3.0
#: True number of lanes on the sample roll.
SAMPLE_ROLL_LANES = 25
#: True number of notes punched in the sample roll.
SAMPLE_ROLL_NOTES = 34
#: Length of the sample roll along the travel axis, in millimetres.
SAMPLE_ROLL_LENGTH_MM = 170.0

_SAMPLE_ROLL = "sample_roll.png"
_QUICKSTART = "quickstart.ipynb"


def sample_roll_path() -> Path:
    """Filesystem path of the bundled sample roll image (PNG).

    Returns
    -------
    pathlib.Path
        Path to ``sample_roll.png`` inside the installed package.

    Notes
    -----
    Assumes a normal (unpacked) installation, which is what wheels and editable
    installs produce. Use :func:`copy_samples` if you need the bytes regardless
    of how the package was installed.
    """
    return Path(str(files(__package__) / _SAMPLE_ROLL))


def quickstart_notebook_path() -> Path:
    """Filesystem path of the bundled quickstart Jupyter notebook.

    Returns
    -------
    pathlib.Path
        Path to ``quickstart.ipynb`` inside the installed package.
    """
    return Path(str(files(__package__) / _QUICKSTART))


def copy_samples(
    dest: str | Path,
    *,
    notebook: bool = True,
    overwrite: bool = False,
) -> list[Path]:
    """Copy the bundled examples into ``dest``, creating it if needed.

    Parameters
    ----------
    dest : str or pathlib.Path
        Destination directory. Created (including parents) when missing.
    notebook : bool, optional
        Also copy the quickstart notebook. Default ``True``.
    overwrite : bool, optional
        Replace files that already exist in ``dest``. When ``False`` (the
        default) existing files are left untouched and still reported.

    Returns
    -------
    list of pathlib.Path
        The destination paths of every example file, whether freshly written or
        already present.
    """
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)

    wanted = [_SAMPLE_ROLL] + ([_QUICKSTART] if notebook else [])
    written: list[Path] = []
    for name in wanted:
        target = out / name
        if overwrite or not target.exists():
            src = files(__package__) / name
            # read_bytes() works for zipped installs too, unlike shutil.copy.
            target.write_bytes(src.read_bytes())
        written.append(target)
    return written
