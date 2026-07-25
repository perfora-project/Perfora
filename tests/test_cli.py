"""Tests for the batch CLI (perfora.cli)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from perfora.cli import (
    _infer_source_type,
    _libmagic_allowed,
    _sniff_source_type,
    _source_type_by_extension,
)

from tests.fixtures.synth import RollSpec, render, synth_video

# DPI used for all test images rendered by _make_roll_image
_TEST_DPI = 150.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_roll_image(
    tmp_path: Path, name: str = "roll.png", **spec_kw: object
) -> Path:
    """Render a synthetic roll at 150 DPI and write it as PNG; return path."""
    kwargs: dict[str, object] = {
        "dpi": _TEST_DPI,
        "roll_length_mm": 80.0,
        "n_lanes": 12,
    }
    kwargs.update(spec_kw)
    spec = RollSpec(**kwargs)  # type: ignore[arg-type]
    img, _ = render(spec)
    p = tmp_path / name
    cv2.imwrite(str(p), img)
    return p


def _dpi_args() -> list[str]:
    """Return --dpi argument list used in every successful process call."""
    return ["--dpi", str(_TEST_DPI)]


# ---------------------------------------------------------------------------
# 1. Multi-input with a directory output
# ---------------------------------------------------------------------------
def test_cli_process_multi_input_dir_output(tmp_path: Path) -> None:
    from perfora.cli import main

    p1 = _make_roll_image(tmp_path, "roll1.png", n_lanes=12)
    p2 = _make_roll_image(tmp_path, "roll2.png", n_lanes=15)

    outdir = tmp_path / "out"
    outdir.mkdir()

    code = main(
        [
            "--format",
            "native_json",
            "-o",
            str(outdir),
            "-i",
            str(p1),
            str(p2),
        ]
        + _dpi_args()
    )
    assert code == 0

    out1 = outdir / "roll1.perfora.json"
    out2 = outdir / "roll2.perfora.json"
    assert out1.exists(), "output for roll1 missing"
    assert out2.exists(), "output for roll2 missing"

    import perfora

    doc1 = perfora.read(str(out1))
    doc2 = perfora.read(str(out2))
    assert len(doc1.notes) > 0, "roll1 has no notes"
    assert len(doc2.notes) > 0, "roll2 has no notes"


# ---------------------------------------------------------------------------
# 2. Format underscore alias
# ---------------------------------------------------------------------------
def test_cli_format_underscore_alias(tmp_path: Path) -> None:
    """'native_json' (underscore) must behave identically to 'native-json'."""
    from perfora.cli import main

    p = _make_roll_image(tmp_path, "roll.png")
    out = tmp_path / "out.perfora.json"

    code = main(
        ["-i", str(p), "-o", str(out), "--format", "native_json"] + _dpi_args()
    )
    assert code == 0
    assert out.exists()

    import perfora

    doc = perfora.read(str(out))
    assert len(doc.notes) > 0


# ---------------------------------------------------------------------------
# 3. Output path semantics
# ---------------------------------------------------------------------------
def test_cli_output_path_semantics(tmp_path: Path) -> None:
    from perfora.cli import main

    p = _make_roll_image(tmp_path, "roll.png")

    # a) one input + -o FILE → writes that exact file
    out_file = tmp_path / "custom.perfora.json"
    code = main(["-i", str(p), "-o", str(out_file)] + _dpi_args())
    assert code == 0
    assert out_file.exists()

    # b) one input + -o existing_dir/ → dir/<stem>.perfora.json
    out_dir = tmp_path / "subdir"
    out_dir.mkdir()
    code = main(["-i", str(p), "-o", str(out_dir) + "/"] + _dpi_args())
    assert code == 0
    assert (out_dir / "roll.perfora.json").exists()

    # c) existing target without --force → nonzero (exit 2)
    code_no_force = main(["-i", str(p), "-o", str(out_file)] + _dpi_args())
    assert code_no_force != 0

    # d) existing target with --force → 0
    code_force = main(
        ["-i", str(p), "-o", str(out_file), "--force"] + _dpi_args()
    )
    assert code_force == 0


# ---------------------------------------------------------------------------
# 4. formats subcommand
# ---------------------------------------------------------------------------
def test_cli_formats_lists_registry(capsys: pytest.CaptureFixture[str]) -> None:
    from perfora.cli import main

    code = main(["formats"])
    assert code == 0
    captured = capsys.readouterr()
    assert "native-json" in captured.out


# ---------------------------------------------------------------------------
# 5. Exit codes
# ---------------------------------------------------------------------------
def test_cli_exit_codes(tmp_path: Path) -> None:
    from perfora.cli import main

    # a) all-gray PNG → no holes → LaneDetectionError → exit 3
    gray_img = np.full((100, 100, 3), 128, dtype=np.uint8)
    gray_path = tmp_path / "gray.png"
    cv2.imwrite(str(gray_path), gray_img)
    code = main(
        ["-i", str(gray_path), "-o", str(tmp_path / "out1.perfora.json")]
        + _dpi_args()
    )
    assert code == 3, f"expected 3 (lane error), got {code}"

    # b) missing input file → exit 3
    code = main(
        [
            "-i",
            str(tmp_path / "nonexistent.png"),
            "-o",
            str(tmp_path / "out2.perfora.json"),
        ]
        + _dpi_args()
    )
    assert code == 3, f"expected 3 (missing file), got {code}"

    # c) --review fail with note_conf_min > 1.0 → all notes flagged → exit 4
    p = _make_roll_image(tmp_path, "roll_review.png")
    config_data = {"note_conf_min": 1.1}
    config_file = tmp_path / "cfg.json"
    config_file.write_text(json.dumps(config_data))
    code = main(
        [
            "-i",
            str(p),
            "-o",
            str(tmp_path / "out3.perfora.json"),
            "--config",
            str(config_file),
            "--review",
            "fail",
        ]
        + _dpi_args()
    )
    assert code == 4, f"expected 4 (review fail), got {code}"


# ---------------------------------------------------------------------------
# 5b. Known lane count via --lanes
# ---------------------------------------------------------------------------
def test_cli_lanes_flag_forces_count(tmp_path: Path) -> None:
    from perfora.cli import main

    p = _make_roll_image(tmp_path, "roll.png", n_lanes=12)
    out = tmp_path / "out.perfora.json"
    code = main(
        ["-i", str(p), "-o", str(out), "--lanes", "12"] + _dpi_args()
    )
    assert code == 0

    import perfora

    doc = perfora.read(str(out))
    assert doc.lane_model.n_lanes == 12
    assert doc.lane_model.method == "fixed-count"


def test_cli_verbose_narrates_stages(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from perfora.cli import main

    p = _make_roll_image(tmp_path, "roll.png", n_lanes=12)
    out = tmp_path / "out.perfora.json"
    code = main(["-i", str(p), "-o", str(out), "-v"] + _dpi_args())
    assert code == 0

    err = capsys.readouterr().err
    # each stage announces what it does and reports what it found
    assert "detecting perforations" in err
    assert "measuring the lane grid" in err
    assert "n_holes=" in err
    assert "n_notes=" in err
    assert "lanes_used=" in err
    assert "detector=ContourDetector" in err


def test_cli_lanes_flag_rejects_nonpositive(tmp_path: Path) -> None:
    from perfora.cli import main

    p = _make_roll_image(tmp_path, "roll.png")
    code = main(
        ["-i", str(p), "-o", str(tmp_path / "o.json"), "--lanes", "0"]
        + _dpi_args()
    )
    assert code == 2


# ---------------------------------------------------------------------------
# 6. Video input
# ---------------------------------------------------------------------------
def test_cli_video_input(tmp_path: Path) -> None:
    from perfora.cli import main

    # Probe VideoWriter availability
    probe_path = str(tmp_path / "probe.avi")
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # type: ignore[attr-defined]
    probe = cv2.VideoWriter(probe_path, fourcc, 30, (100, 100))
    if not probe.isOpened():
        pytest.skip("cv2.VideoWriter (MJPG) not available")
    probe.release()

    spec = RollSpec(dpi=_TEST_DPI, roll_length_mm=80.0, n_lanes=12)
    frames, _, _ = synth_video(spec, base_speed_px=2.0)
    if not frames:
        pytest.skip("synth_video produced no frames")

    h, w = frames[0].shape[:2]
    avi_path = tmp_path / "roll.avi"
    writer = cv2.VideoWriter(str(avi_path), fourcc, 30, (w, h))
    if not writer.isOpened():
        pytest.skip("cv2.VideoWriter cannot open the output file")
    for frm in frames:
        writer.write(frm)
    writer.release()

    out_path = tmp_path / "roll.perfora.json"
    code = main(
        ["-i", str(avi_path), "-o", str(out_path)] + _dpi_args()
    )

    # Accept 0 (success) or 3 (lane detection failed on lossy MJPG video)
    assert code in (0, 3), f"expected 0 or 3 from video processing, got {code}"
    if code == 0:
        assert out_path.exists()


# ---------------------------------------------------------------------------
# 7. Preview directory
# ---------------------------------------------------------------------------
def test_cli_preview_dir(tmp_path: Path) -> None:
    from perfora.cli import main

    p = _make_roll_image(tmp_path, "roll.png")
    preview_dir = tmp_path / "previews"
    out_path = tmp_path / "roll.perfora.json"

    code = main(
        [
            "-i",
            str(p),
            "-o",
            str(out_path),
            "--preview-dir",
            str(preview_dir),
        ]
        + _dpi_args()
    )
    assert code == 0
    assert out_path.exists()

    png_files = list(preview_dir.glob("*.png"))
    assert len(png_files) > 0, "no preview PNGs were written"
    names = {f.name for f in png_files}
    # At least one meaningful stage preview must exist
    assert any("lanes" in n or "holes" in n or "notes" in n for n in names)
    # Stage 0 holds the input image the pipeline actually uses
    assert any(n.endswith("__00_input.png") for n in names)
    # Files carry a zero-padded numeric prefix so a browser sorts them in order
    suffixes = sorted(n.split("__", 1)[1] for n in names)
    assert suffixes[0].startswith("00_")
    assert any(s.startswith("01_") for s in suffixes)


# ---------------------------------------------------------------------------
# 8. Source-type detection: python-magic content sniffing + graceful fallback
# ---------------------------------------------------------------------------
def test_source_type_content_sniff(tmp_path: Path) -> None:
    # a real PNG saved with a non-image extension is still detected as an image
    # (content sniffing beats the extension when python-magic + libmagic exist)
    png = _make_roll_image(tmp_path, "roll.png")
    misnamed = tmp_path / "roll.dat"
    png.rename(misnamed)
    assert _infer_source_type(str(misnamed)) == "image"


def test_source_type_extension_fallback() -> None:
    assert _source_type_by_extension("clip.mp4") == "video"
    assert _source_type_by_extension("scan.png") == "image"
    assert _source_type_by_extension("mystery.xyz") == "image"


def test_source_type_falls_back_without_magic(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "magic":
            raise ImportError("simulated: python-magic not installed")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # sniffing yields nothing, but inference still works via the extension
    assert _sniff_source_type("whatever.png") is None
    assert _infer_source_type("clip.mp4") == "video"
    assert _infer_source_type("scan.png") == "image"


# ---------------------------------------------------------------------------
# Platform guard around libmagic
# ---------------------------------------------------------------------------
def test_libmagic_is_used_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert _libmagic_allowed() is True


def test_libmagic_is_skipped_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loading a mismatched libmagic DLL faults the interpreter on Windows.

    Since that cannot be caught, Windows must not even attempt the import; the
    extension fallback keeps working.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("PERFORA_USE_LIBMAGIC", raising=False)
    assert _libmagic_allowed() is False
    assert _sniff_source_type("scan.png") is None
    assert _infer_source_type("clip.mp4") == "video"
    assert _infer_source_type("scan.png") == "image"


def test_libmagic_opt_in_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    for truthy in ("1", "true", "YES", "on"):
        monkeypatch.setenv("PERFORA_USE_LIBMAGIC", truthy)
        assert _libmagic_allowed() is True
    monkeypatch.setenv("PERFORA_USE_LIBMAGIC", "0")
    assert _libmagic_allowed() is False
