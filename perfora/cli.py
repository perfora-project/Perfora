"""Batch command-line interface for perfora.

Three subcommands
-----------------
``process`` (the default when no subcommand word is given)
    Decode one or more scan images / videos into the internal document format.
``convert``
    Transcode an already-decoded document between registered formats.
``formats``
    List all registered reader/writer formats with their file extensions.

Exit codes
----------
0   Success.
2   Usage error (bad arguments or bad ``-o`` semantics).
3   No lanes detected or unreadable input.
4   Review queue non-empty and ``--review fail`` was requested.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from perfora.config import Config
from perfora.errors import FormatError, LaneDetectionError, PerforaError

if TYPE_CHECKING:
    from perfora.model.document import RollDocument
    from perfora.pipeline.session import Session
    from perfora.sources.base import Source

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_IMAGE_EXTS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
)
_VIDEO_EXTS: frozenset[str] = frozenset(
    {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm"}
)
_SUBCOMMANDS: frozenset[str] = frozenset({"process", "convert", "formats"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _canon(fmt: str) -> str:
    """Normalise a format id: underscores → hyphens (mirrors registry._canon)."""
    return fmt.replace("_", "-")


def _infer_source_type(path: str) -> str:
    """Return ``'image'`` or ``'video'`` for a path.

    Prefers content sniffing via ``python-magic`` (libmagic); if python-magic or
    the system libmagic is unavailable, or the MIME type is inconclusive, falls
    back — without error — to matching the file extension.
    """
    kind = _sniff_source_type(path)
    if kind is not None:
        return kind
    return _source_type_by_extension(path)


def _source_type_by_extension(path: str) -> str:
    """Extension-based fallback: video extensions -> ``'video'``, else image."""
    ext = Path(path).suffix.lower()
    return "video" if ext in _VIDEO_EXTS else "image"


def _sniff_source_type(path: str) -> str | None:
    """Content-sniff ``'image'``/``'video'`` via libmagic, or ``None``.

    Returns ``None`` (never raises) when python-magic or libmagic is missing, the
    file can't be read, or the MIME type is neither image nor video.
    """
    try:
        import magic
    except ImportError:
        return None
    try:
        mime = magic.from_file(str(path), mime=True)
    except Exception:  # noqa: BLE001 - libmagic missing / unreadable file, etc.
        return None
    if isinstance(mime, str):
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("image/"):
            return "image"
    return None


def _writer_extension(format_id: str) -> str:
    """Return the first extension registered for the writer of *format_id*.

    Falls back to ``'.bin'`` if the format is unknown (a subsequent write call
    will surface the proper error).
    """
    from perfora.io.registry import available_formats

    fmts = available_formats()
    key = _canon(format_id)
    info = fmts.get(key, {})
    exts: tuple[str, ...] = info.get("extensions", ())
    return exts[0] if exts else ".bin"


# ---------------------------------------------------------------------------
# _Exit: a BaseException that bypasses except-Exception handlers
# ---------------------------------------------------------------------------
class _Exit(BaseException):
    """Raised instead of sys.exit so main() can return an int exit code."""

    def __init__(self, code: int) -> None:
        self.code = code


def _die(code: int, msg: str) -> NoReturn:
    """Write *msg* to stderr and raise :class:`_Exit`(*code*)."""
    sys.stderr.write(f"perfora: {msg}\n")
    raise _Exit(code)


def _check_overwrite(path: Path, force: bool) -> None:
    """Raise :class:`_Exit`(2) if *path* exists and *force* is ``False``."""
    if path.exists() and not force:
        _die(2, f"output already exists (use --force to overwrite): {path}")


# ---------------------------------------------------------------------------
# Argparse parser that never calls sys.exit
# ---------------------------------------------------------------------------
class _Parser(argparse.ArgumentParser):
    """ArgumentParser that raises :class:`_Exit` instead of calling sys.exit."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        raise _Exit(2)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        if message:
            sys.stderr.write(message)
        raise _Exit(status)


# ---------------------------------------------------------------------------
# Output-path resolution
# ---------------------------------------------------------------------------
def _resolve_output(
    inputs: list[str],
    output_arg: str,
    format_id: str,
    force: bool,
) -> list[Path]:
    """Return one output :class:`Path` per input entry.

    Raises :class:`_Exit`(2) on usage errors.
    """
    ext = _writer_extension(format_id)
    trailing_slash = output_arg.endswith("/") or output_arg.endswith(os.sep)
    out = Path(output_arg)

    if len(inputs) > 1:
        if out.exists() and not out.is_dir():
            _die(2, f"-o must be a directory for multiple inputs: {output_arg!r}")
        out.mkdir(parents=True, exist_ok=True)
        return [out / (Path(inp).stem + ext) for inp in inputs]

    # Single input
    if trailing_slash or (out.exists() and out.is_dir()):
        out.mkdir(parents=True, exist_ok=True)
        return [out / (Path(inputs[0]).stem + ext)]

    return [out]


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
def _load_config(config_file: str | None) -> Config:
    """Load :class:`Config` from a JSON file, or return the default."""
    if config_file is None:
        return Config()
    try:
        with open(config_file) as fh:
            raw = json.load(fh)
        return Config(**raw)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        _die(2, f"cannot load --config {config_file!r}: {exc}")


# ---------------------------------------------------------------------------
# ROI parsing
# ---------------------------------------------------------------------------
def _parse_roi(roi_str: str | None) -> tuple[int, int, int, int] | None:
    """Parse ``'X,Y,W,H'`` into ``(X, Y, W, H)`` integers."""
    if roi_str is None:
        return None
    parts = roi_str.split(",")
    if len(parts) != 4:
        _die(2, f"--roi must be X,Y,W,H (four integers): {roi_str!r}")
    try:
        return (
            int(parts[0].strip()),
            int(parts[1].strip()),
            int(parts[2].strip()),
            int(parts[3].strip()),
        )
    except ValueError:
        _die(2, f"--roi values must be integers: {roi_str!r}")


# ---------------------------------------------------------------------------
# Source construction
# ---------------------------------------------------------------------------
def _make_source(
    inp: str,
    source_type: str,
    dpi: float | None,
    physical_width_mm: float | None,
    roi: tuple[int, int, int, int] | None,
    travel: str,
    config: Config,
) -> Source:
    """Instantiate an :class:`ImageSource` or :class:`VideoSource`."""
    kind = source_type if source_type != "auto" else _infer_source_type(inp)
    if kind == "video":
        from perfora.sources.video_source import VideoSource

        return VideoSource(
            inp,
            roi=roi,
            travel=travel,
            dpi=dpi,
            physical_width_mm=physical_width_mm,
            config=config,
        )
    from perfora.sources.image_source import ImageSource

    return ImageSource(
        inp,
        dpi=dpi,
        physical_width_mm=physical_width_mm,
        config=config,
    )


# ---------------------------------------------------------------------------
# Core: process one input file
# ---------------------------------------------------------------------------
def _process_one(
    inp: str,
    out: Path,
    *,
    format_id: str,
    source_type: str,
    dpi: float | None,
    physical_width_mm: float | None,
    roi: tuple[int, int, int, int] | None,
    travel: str,
    config: Config,
    preview_dir: Path | None,
    verbosity: int,
    quiet: bool,
) -> RollDocument:
    """Run the pipeline on one input file and write the result.

    Returns the decoded :class:`~perfora.model.document.RollDocument`.

    Raises
    ------
    PerforaError
        Including :class:`~perfora.errors.LaneDetectionError`, on any pipeline
        or I/O failure.
    """
    import cv2

    from perfora.io.registry import write_document
    from perfora.pipeline.progress import (
        NullProgressReporter,
        TerminalProgressReporter,
    )
    from perfora.pipeline.session import Session

    reporter: NullProgressReporter | TerminalProgressReporter
    if quiet or verbosity == 0:
        reporter = NullProgressReporter()
    else:
        reporter = TerminalProgressReporter(verbosity=verbosity)

    source = _make_source(
        inp, source_type, dpi, physical_width_mm, roi, travel, config
    )
    session = Session(source, config=config, progress=reporter)
    doc = session.run_all()

    out.parent.mkdir(parents=True, exist_ok=True)
    write_document(doc, out, format=format_id)

    if preview_dir is not None:
        _write_stage_previews(session, inp, preview_dir, cv2)

    return doc


def _write_stage_previews(
    session: Session, inp: str, preview_dir: Path, cv2: Any
) -> None:
    """Write one numbered PNG per stage (plus the input the system uses).

    Files are prefixed with a zero-padded index so a file browser lists them in
    pipeline order: ``00_input`` is the canonical image the pipeline actually
    works on (deskewed and, for large scans, downscaled), then ``01_preprocess``,
    ``02_holes``, and so on.
    """
    preview_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(inp).stem
    ctx_image = session.ctx.image

    # Stage 0: the input image as the pipeline uses it.
    base = ctx_image.color if ctx_image.color is not None else ctx_image.gray
    cv2.imwrite(str(preview_dir / f"{stem}__00_input.png"), base)

    for i, stage in enumerate(session.stages, start=1):
        prev = session.preview(stage.name)
        if prev is not None:
            canvas = prev.rasterize(ctx_image)
            fname = preview_dir / f"{stem}__{i:02d}_{stage.name}.png"
            cv2.imwrite(str(fname), canvas)


# ---------------------------------------------------------------------------
# Subcommand: process
# ---------------------------------------------------------------------------
def _cmd_process(args: argparse.Namespace) -> int:
    """Handle the ``process`` subcommand."""
    inputs: list[str] = args.input
    output_arg: str = args.output
    format_id: str = _canon(args.format)
    force: bool = bool(args.force)
    dpi: float | None = args.dpi
    physical_width_mm: float | None = args.physical_width_mm
    source_type: str = str(args.source_type)
    roi_str: str | None = args.roi
    travel: str = str(args.travel)
    review_mode: str = str(args.review)
    preview_raw: str | None = args.preview_dir
    verbosity: int = int(args.verbosity) if args.verbosity is not None else 0
    quiet: bool = bool(args.quiet)
    config_file: str | None = args.config

    preview_dir: Path | None = Path(preview_raw) if preview_raw else None
    roi = _parse_roi(roi_str)
    config = _load_config(config_file)

    if not quiet and dpi is None and physical_width_mm is None:
        sys.stderr.write(
            "perfora: notice: no --dpi or --physical-width-mm given; "
            "geometry will be in assumed pixel units (1 mm = 1 px)\n"
        )

    # Validate format has a writer before touching the filesystem
    from perfora.io.registry import available_formats

    fmts = available_formats()
    if format_id not in fmts or not fmts[format_id].get("write"):
        _die(2, f"unknown or non-writable format: {args.format!r}")

    out_paths = _resolve_output(inputs, output_arg, format_id, force)
    for op in out_paths:
        _check_overwrite(op, force)

    for inp, out in zip(inputs, out_paths, strict=True):
        try:
            doc = _process_one(
                inp,
                out,
                format_id=format_id,
                source_type=source_type,
                dpi=dpi,
                physical_width_mm=physical_width_mm,
                roi=roi,
                travel=travel,
                config=config,
                preview_dir=preview_dir,
                verbosity=verbosity,
                quiet=quiet,
            )
        except (LaneDetectionError, PerforaError) as exc:
            sys.stderr.write(f"perfora: error processing {inp!r}: {exc}\n")
            return 3

        if review_mode != "ignore" and doc.review_queue:
            n = len(doc.review_queue)
            msg = (
                f"perfora: {n} item(s) in review queue for {inp!r}\n"
            )
            if review_mode == "fail":
                sys.stderr.write(msg)
                return 4
            else:  # warn
                sys.stderr.write(msg)

    return 0


# ---------------------------------------------------------------------------
# Subcommand: convert
# ---------------------------------------------------------------------------
def _cmd_convert(args: argparse.Namespace) -> int:
    """Handle the ``convert`` subcommand."""
    in_path: str = args.input
    out_path: str = args.output
    to_fmt: str = _canon(args.to)
    from_fmt: str | None = (
        _canon(args.from_fmt) if args.from_fmt is not None else None
    )

    try:
        import perfora

        doc = perfora.read(in_path, format=from_fmt)
        perfora.write(doc, out_path, format=to_fmt)
    except FormatError as exc:
        sys.stderr.write(f"perfora convert: format error: {exc}\n")
        return 2
    except (PerforaError, OSError) as exc:
        sys.stderr.write(f"perfora convert: error: {exc}\n")
        return 3

    return 0


# ---------------------------------------------------------------------------
# Subcommand: formats
# ---------------------------------------------------------------------------
def _cmd_formats(_args: argparse.Namespace) -> int:
    """Handle the ``formats`` subcommand."""
    import perfora

    fmts = perfora.available_formats()
    for fmt_id, info in sorted(fmts.items()):
        can_read = "R" if info.get("read") else " "
        can_write = "W" if info.get("write") else " "
        exts_raw: tuple[str, ...] = info.get("extensions", ())
        exts = "  ".join(exts_raw) if exts_raw else "(none)"
        print(f"{fmt_id:<24s}  {can_read}{can_write}  {exts}")
    return 0


# ---------------------------------------------------------------------------
# Argparse parser construction
# ---------------------------------------------------------------------------
def _build_parser() -> _Parser:
    """Construct the top-level parser with all subcommands."""
    p = _Parser(
        prog="perfora",
        description="Digitize player-piano roll scans and videos.",
    )
    subs = p.add_subparsers(dest="subcommand", parser_class=_Parser)

    # ---- process -------------------------------------------------------- #
    pp = subs.add_parser(
        "process",
        help="Decode one or more scans / videos into the document format.",
    )
    pp.add_argument(
        "-i",
        "--input",
        nargs="+",
        required=True,
        metavar="IN",
        help="Input file(s): images or videos.",
    )
    pp.add_argument(
        "-o",
        "--output",
        required=True,
        metavar="OUT",
        help=(
            "Output file (single input) or directory (multiple inputs or "
            "trailing slash)."
        ),
    )
    pp.add_argument(
        "--format",
        default="native-json",
        metavar="ID",
        help="Writer format id (default: native-json).",
    )
    pp.add_argument(
        "--dpi",
        type=float,
        default=None,
        metavar="N",
        help="Scan resolution in DPI.",
    )
    pp.add_argument(
        "--physical-width-mm",
        dest="physical_width_mm",
        type=float,
        default=None,
        metavar="N",
        help="Physical roll width in mm (alternative calibration to --dpi).",
    )
    pp.add_argument(
        "--source-type",
        dest="source_type",
        choices=["auto", "image", "video"],
        default="auto",
        help="Override automatic source-type inference (default: auto).",
    )
    pp.add_argument(
        "--roi",
        default=None,
        metavar="X,Y,W,H",
        help="Video ROI crop as X,Y,W,H integers.",
    )
    pp.add_argument(
        "--travel",
        choices=["auto", "up", "down"],
        default="auto",
        help="Video travel direction (default: auto).",
    )
    pp.add_argument(
        "--config",
        default=None,
        metavar="FILE",
        help="JSON file of Config field overrides.",
    )
    pp.add_argument(
        "--preview-dir",
        dest="preview_dir",
        default=None,
        metavar="DIR",
        help="Write one rasterized preview PNG per stage to DIR.",
    )
    pp.add_argument(
        "--review",
        choices=["warn", "fail", "ignore"],
        default="warn",
        help=(
            "Behaviour when the review queue is non-empty: "
            "warn (default), fail (exit 4), or ignore."
        ),
    )
    pp.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output files.",
    )
    pp.add_argument(
        "-v",
        "--verbose",
        dest="verbosity",
        action="count",
        default=0,
        help="Increase verbosity (repeat for more: -v, -vv).",
    )
    pp.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress all progress output and notices.",
    )

    # ---- convert -------------------------------------------------------- #
    cp = subs.add_parser(
        "convert",
        help="Transcode a document between registered formats.",
    )
    cp.add_argument("input", metavar="IN", help="Source document file.")
    cp.add_argument("output", metavar="OUT", help="Destination file.")
    cp.add_argument(
        "--to",
        required=True,
        metavar="FORMAT",
        help="Destination format id.",
    )
    cp.add_argument(
        "--from",
        dest="from_fmt",
        default=None,
        metavar="FORMAT",
        help="Source format id (inferred from extension when omitted).",
    )
    cp.add_argument(
        "--feed-rate-mm-s",
        dest="feed_rate_mm_s",
        type=float,
        default=None,
        metavar="N",
        help="Feed rate mm/s (stored for future time-based writers; ignored now).",
    )

    # ---- formats -------------------------------------------------------- #
    subs.add_parser("formats", help="List all registered formats.")

    return p


# ---------------------------------------------------------------------------
# Default-subcommand injection
# ---------------------------------------------------------------------------
def _inject_default_subcommand(argv: list[str]) -> list[str]:
    """Prepend ``'process'`` when no subcommand word is present in argv."""
    if not argv:
        return argv
    first = argv[0]
    if first in _SUBCOMMANDS:
        return argv
    if first in ("-h", "--help"):
        return argv
    return ["process"] + argv


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """Parse *argv* (defaults to ``sys.argv[1:]``) and dispatch.

    Returns
    -------
    int
        An exit code: 0 success, 2 usage, 3 pipeline/read error, 4 review.
    """
    if argv is None:
        raw: list[str] = sys.argv[1:]
    else:
        raw = list(argv)

    raw = _inject_default_subcommand(raw)

    parser = _build_parser()
    try:
        args = parser.parse_args(raw)
        sub: str | None = args.subcommand
        if sub == "process":
            return _cmd_process(args)
        if sub == "convert":
            return _cmd_convert(args)
        if sub == "formats":
            return _cmd_formats(args)
        # No subcommand (empty argv): show help and return 2
        parser.print_help(sys.stderr)
        return 2
    except _Exit as exc:
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
