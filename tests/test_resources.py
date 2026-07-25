"""The bundled sample roll, the quickstart notebook, and ``perfora sample``.

These guard the first-run experience: a fresh install must be able to copy the
examples out and decode the sample roll to its known ground truth. If the
pipeline regresses on the sample, the tutorial in the README is wrong too.
"""

from __future__ import annotations

import json
from pathlib import Path

import perfora
import pytest
from perfora import notebook as nb_launcher
from perfora.cli import main as cli_main
from perfora.resources import (
    SAMPLE_ROLL_DPI,
    SAMPLE_ROLL_LANES,
    SAMPLE_ROLL_NOTES,
    SAMPLE_ROLL_PITCH_MM,
    copy_samples,
    quickstart_notebook_path,
    sample_roll_path,
)


# --------------------------------------------------------------------------- #
# The sample roll
# --------------------------------------------------------------------------- #
def test_sample_roll_is_bundled() -> None:
    path = sample_roll_path()
    assert path.is_file()
    assert path.suffix == ".png"
    # Small enough to live in git; big enough to be a real roll.
    assert 1_000 < path.stat().st_size < 500_000


def test_sample_roll_decodes_to_its_ground_truth() -> None:
    """The shipped sample must decode to exactly the documented numbers."""
    doc = perfora.process(
        perfora.ImageSource(sample_roll_path(), dpi=SAMPLE_ROLL_DPI)
    )

    assert doc.lane_model.n_lanes == SAMPLE_ROLL_LANES
    assert doc.lane_model.pitch_mm == pytest.approx(SAMPLE_ROLL_PITCH_MM, abs=0.05)
    assert len(doc.notes) == SAMPLE_ROLL_NOTES
    # A clean synthetic roll should leave nothing for a human to check.
    assert doc.review_queue == []


def test_sample_roll_round_trips(tmp_path: Path) -> None:
    doc = perfora.process(
        perfora.ImageSource(sample_roll_path(), dpi=SAMPLE_ROLL_DPI)
    )
    out = tmp_path / "sample.perfora.json"
    perfora.write(doc, out)
    assert perfora.read(out) == doc


# --------------------------------------------------------------------------- #
# copy_samples()
# --------------------------------------------------------------------------- #
def test_copy_samples_writes_both_files(tmp_path: Path) -> None:
    written = copy_samples(tmp_path / "new-dir")
    names = {p.name for p in written}
    assert names == {"sample_roll.png", "quickstart.ipynb"}
    assert all(p.is_file() for p in written)


def test_copy_samples_skips_notebook_when_asked(tmp_path: Path) -> None:
    written = copy_samples(tmp_path, notebook=False)
    assert [p.name for p in written] == ["sample_roll.png"]
    assert not (tmp_path / "quickstart.ipynb").exists()


def test_copy_samples_preserves_edits_unless_overwriting(tmp_path: Path) -> None:
    target = tmp_path / "sample_roll.png"
    target.write_bytes(b"my own edit")

    copy_samples(tmp_path)
    assert target.read_bytes() == b"my own edit"

    copy_samples(tmp_path, overwrite=True)
    assert target.read_bytes() == sample_roll_path().read_bytes()


# --------------------------------------------------------------------------- #
# The `sample` subcommand
# --------------------------------------------------------------------------- #
def test_cli_sample_copies_and_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dest = tmp_path / "out"
    assert cli_main(["sample", str(dest)]) == 0

    captured = capsys.readouterr()
    assert str(dest / "sample_roll.png") in captured.out
    # The suggested next command belongs on stderr, so `perfora sample` can be
    # piped without the prose getting in the way.
    assert "--dpi 300" in captured.err

    assert (dest / "sample_roll.png").is_file()
    assert (dest / "quickstart.ipynb").is_file()


def test_cli_sample_decodes_end_to_end(tmp_path: Path) -> None:
    """`perfora sample` then `perfora process` — the README's first two steps."""
    dest = tmp_path / "roll"
    assert cli_main(["sample", str(dest), "--no-notebook"]) == 0

    out = tmp_path / "out.perfora.json"
    code = cli_main(
        [
            "-i",
            str(dest / "sample_roll.png"),
            "-o",
            str(out),
            "--dpi",
            str(int(SAMPLE_ROLL_DPI)),
            "--quiet",
        ]
    )
    assert code == 0
    doc = perfora.read(out)
    assert len(doc.notes) == SAMPLE_ROLL_NOTES


# --------------------------------------------------------------------------- #
# The quickstart notebook
# --------------------------------------------------------------------------- #
def test_quickstart_notebook_is_valid_and_compiles() -> None:
    path = quickstart_notebook_path()
    assert path.is_file()

    nb = json.loads(path.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    cells = nb["cells"]
    assert [c["cell_type"] for c in cells].count("code") >= 5

    for i, cell in enumerate(cells):
        assert isinstance(cell["source"], list), f"cell {i} source must be a list"
        if cell["cell_type"] != "code":
            continue
        # Cleared outputs keep diffs readable and the wheel small.
        assert cell["outputs"] == [], f"code cell {i} ships with outputs"
        assert cell["execution_count"] is None
        source = "".join(cell["source"])
        compile(source, f"<quickstart cell {i}>", "exec")


def test_notebook_launcher_defaults() -> None:
    """Defaults must be safe: loopback only, and no surprise overwrites."""
    args = nb_launcher._build_parser().parse_args([])
    assert args.ip == "127.0.0.1"
    assert args.port == 8888
    assert args.refresh is False
    assert "perfora" in args.dir


def test_notebook_launcher_explains_missing_extra() -> None:
    assert "notebook" in nb_launcher._MISSING_JUPYTER
    assert "uv sync --extra notebook" in nb_launcher._MISSING_JUPYTER
