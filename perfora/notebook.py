"""``perfora-notebook`` — a browser-based way into the pipeline.

Starts a local Jupyter server on a copy of the bundled quickstart notebook, so
someone who has never used a terminal beyond one command can load a roll, look
at every stage, and adjust it. This is the intended default entry point of the
perfora Docker image.

Requires the ``notebook`` extra (``pip install 'perfora[notebook]'`` /
``uv sync --extra notebook``). Nothing here is imported by the core library, and
Jupyter is imported lazily so a missing extra produces a helpful message instead
of a traceback.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from perfora.resources import copy_samples

_MISSING_JUPYTER = """\
perfora-notebook needs Jupyter, which is not installed.

Install the notebook extra:

    uv sync --extra notebook          # working from a clone of the repository
    pip install 'perfora[notebook]'   # working from an installed perfora

Then run `perfora-notebook` again. (The plain `perfora` command-line tool works
without it.)
"""


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="perfora-notebook",
        description=(
            "Start a local Jupyter server on the perfora quickstart notebook. "
            "The notebook and a sample roll are copied into the working "
            "directory on first run, so your edits are never lost when perfora "
            "is upgraded."
        ),
    )
    p.add_argument(
        "-d",
        "--dir",
        default="./perfora-notebooks",
        metavar="DIR",
        help=(
            "Working directory for the notebook and sample roll "
            "(default: ./perfora-notebooks). Created if missing."
        ),
    )
    p.add_argument(
        "--port",
        type=int,
        default=8888,
        help="Port the Jupyter server listens on (default: 8888).",
    )
    p.add_argument(
        "--ip",
        default="127.0.0.1",
        help=(
            "Address to bind. Default 127.0.0.1 (this machine only). Use "
            "0.0.0.0 to accept connections from elsewhere — e.g. inside a "
            "container. Only do that on a network you trust."
        ),
    )
    p.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a web browser; just print the URL.",
    )
    p.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Overwrite an existing quickstart notebook and sample roll in DIR "
            "with the bundled versions (discards your edits to them)."
        ),
    )
    p.add_argument(
        "--token",
        default=None,
        metavar="TOKEN",
        help=(
            "Fixed authentication token for the server. By default Jupyter "
            "generates a random one and prints the URL containing it."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Copy the examples into place and hand control to the Jupyter server.

    Parameters
    ----------
    argv : list of str or None, optional
        Argument vector; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Exit code: ``0`` on a clean server shutdown, ``2`` on a usage error,
        ``3`` when Jupyter is not installed.
    """
    args = _build_parser().parse_args(sys.argv[1:] if argv is None else argv)

    workdir = Path(args.dir).expanduser().resolve()
    try:
        copied = copy_samples(workdir, notebook=True, overwrite=args.refresh)
    except OSError as exc:
        print(f"perfora-notebook: cannot prepare {workdir}: {exc}", file=sys.stderr)
        return 2

    print(f"[perfora] notebook directory: {workdir}")
    for path in copied:
        print(f"[perfora]   {path.name}")

    try:
        from jupyterlab.labapp import LabApp  # type: ignore[import-not-found]
    except ImportError:
        print(_MISSING_JUPYTER, file=sys.stderr)
        return 3

    jupyter_argv = [
        f"--ServerApp.root_dir={workdir}",
        f"--ServerApp.ip={args.ip}",
        f"--ServerApp.port={args.port}",
        "--LabApp.default_url=/lab/tree/quickstart.ipynb",
    ]
    if args.no_browser:
        jupyter_argv.append("--ServerApp.open_browser=False")
    if args.token is not None:
        jupyter_argv.append(f"--ServerApp.token={args.token}")

    # launch_instance() blocks until the server is shut down and may raise
    # SystemExit; translate that into our own return code.
    try:
        LabApp.launch_instance(argv=jupyter_argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else 0
    except KeyboardInterrupt:
        return 0
    return 0


def jupyter_executable() -> str | None:
    """Path of the ``jupyter`` executable, if one is on ``PATH``.

    Returns
    -------
    str or None
        Absolute path, or ``None`` when Jupyter is not installed.
    """
    return shutil.which("jupyter")


if __name__ == "__main__":
    raise SystemExit(main())
