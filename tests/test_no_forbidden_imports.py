"""Guard for hard-constraint #1 (AGENTS.md): the roll logic must be ours.

`perfora/` may use generic image-processing / scientific libraries freely, but it
must never import (and therefore never wrap or piggyback on) an existing
player-piano / piano-roll / music-roll *decoding* library, nor port another
project's lane-finding algorithm. This test fails if any module under `perfora/`
imports a name on the denylist.

Note: MIDI *encoder* libraries (`mido`, `pretty_midi`) are explicitly allowed by
the architecture for the optional MIDI format — they are file-format codecs, not
roll decoders — so they are not on the denylist.
"""

from __future__ import annotations

import ast
from pathlib import Path

PERFORA_ROOT = Path(__file__).resolve().parent.parent / "perfora"

# Top-level import names that would mean we are leaning on someone else's roll
# decoder / lane-finder instead of implementing it ourselves. Matched against the
# first dotted component of every import.
FORBIDDEN_IMPORTS = frozenset(
    {
        "pianoroll",
        "piano_roll",
        "pypianoroll",
        "musicroll",
        "music_roll",
        "playerpiano",
        "player_piano",
        "rollscan",
        "roll_scan",
        "pyrollscan",
        "pianorollscan",
        "rolldecode",
        "roll_decoder",
        "perfodecode",
    }
)


def _iter_python_files() -> list[Path]:
    return sorted(PERFORA_ROOT.rglob("*.py"))


def _imported_top_level_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_no_forbidden_roll_library_imports() -> None:
    offenders: dict[str, set[str]] = {}
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = _imported_top_level_names(tree) & FORBIDDEN_IMPORTS
        if hits:
            offenders[str(path.relative_to(PERFORA_ROOT.parent))] = hits
    assert not offenders, (
        "Forbidden roll/lane-finding library imports found under perfora/ "
        f"(hard-constraint #1): {offenders}"
    )


def test_denylist_actually_runs_against_some_files() -> None:
    # Sanity: the scanner sees the package, so a green result is meaningful.
    assert _iter_python_files(), "no perfora/*.py files were scanned"
