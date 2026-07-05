# CLAUDE.md — perfora

> Read this first. It is the contract for how this library is built. The deeper
> design lives in `docs/ARCHITECTURE.md`, `docs/ALGORITHMS.md`, and
> `docs/BUILD_PLAN.md`. Follow the build plan phase by phase.

## What perfora is

`perfora` is a Python library that **digitizes scans of player-piano rolls**. It
takes either a flat scan (a photo/scan of an unrolled roll) or a video of a roll
being played, and produces a structured, reversible representation of:

- the **perforations** (which lane is open, from where to where), and
- the **text** on the roll (printed title/composer/label and handwritten
  annotations), each with its position, bounding box, and a *scope* that says
  whether it belongs to the whole roll or to a specific stretch of the music.

perfora is primarily a **library**, and it also ships a **CLI**. It exposes three
coordinated surfaces:

1. a one-shot Python API (`perfora.process`, `perfora.read`, `perfora.write`);
2. a step-by-step **`Session` API** built for an external UI to drive the pipeline
   one stage at a time — run a stage, preview it, adjust its inputs, re-run from
   that point; and
3. a **CLI** (`perfora ...`) with a batch mode and a guided **interactive** mode.

A rich GUI is not in this repo, but the pipeline must be *built so a UI can drive
it*: every stage is previewable and every stage's key decisions are overridable
mid-run (see `docs/ARCHITECTURE.md §12`). The review queue remains the formal hook
for correcting individual low-confidence results.

## Hard constraints (do not violate)

1. **Implement the lane-finding and roll-parsing algorithms from scratch.** The
   periodicity detection, lane assignment, note assembly, text-to-timeline
   association, and video reconstruction must be original code built on generic
   primitives (numpy, scipy, scikit-image, OpenCV). **Do not** add or wrap any
   existing player-piano / piano-roll / music-roll decoding library, and do not
   port another project's lane-finding algorithm. Generic *image processing*
   from libraries is fine and encouraged; the *roll logic* must be ours.
2. **Spacing is auto-detected, never assumed.** Roll standards differ in hole
   pitch. The lane model is *measured* from the scan (see `docs/ALGORITHMS.md`),
   so unknown standards work without configuration.
3. **All spatial quantities in the data model are in millimeters.** Pixels exist
   only inside image-processing code; everything that leaves a stage is mm, with
   a `Calibration` recording the px↔mm relationship. Mapping mm → time/MIDI is
   **derived** (a helper/property or left to the consumer), never baked into the
   stored model.
4. **Recognition is an interface.** Text detection and recognition sit behind
   protocols so backends can be swapped. The first shipped backends are fully
   **offline**. Cloud backends may be added later behind the same interface.
5. **Reader/Writer symmetry.** Every format the library can write, it can read
   back into the identical internal model. IO is a plugin layer with runtime
   format selection.

## Tech stack

- **Python 3.11+**, full type hints, `from __future__ import annotations`.
- Core scientific stack: `numpy`, `scipy`, `pandas`, `scikit-image`,
  `opencv-python` (headless in CI).
- `python-magic` (libmagic) for content-based source-type detection, with a
  graceful, error-free fallback to extension matching when it or the system
  `libmagic` is missing (so it never becomes a hard requirement).
- OCR backends are **optional extras**, never imported by the core:
  - `pytesseract` (printed text) — extra `[tesseract]`
  - `transformers` + `torch` for TrOCR handwriting — extra `[trocr]`
  - `easyocr` (detection + light handwriting) — extra `[easyocr]`
- Tooling: `pytest`, `ruff`, `mypy` (strict on `perfora/`), `hatchling` build
  backend.
- A console entry point `perfora` (`perfora.cli:main`), argparse-based so the
  basic CLI needs no extra dependencies; an optional `[cli]` extra (`rich`,
  `questionary`, `pillow`) only upgrades interactive prompts and inline previews,
  with graceful fallback to plain `input()` when it is absent.

The **core install must stay light**: importing `perfora`, running the image →
holes → lanes → notes path, and reading/writing the native JSON format must work
with only numpy/scipy/pandas/scikit-image/opencv (+ the small `python-magic`)
installed. Heavy ML deps load lazily and only when a backend that needs them is
selected.

## Conventions

- Geometry uses two named axes everywhere: **`u`** = the travel/length axis (the
  direction the roll moves through the player; notes extend along `u`), **`v`** =
  the cross axis (across the roll's width, where pitch/lane lives). Lane index
  increases with `v`. Never use bare "x/y" in the model — use `u`/`v` so code is
  unambiguous about orientation.
- Confidence is always a float in `[0, 1]`. Anything below a stage's threshold is
  added to the review queue rather than dropped.
- Public functions/classes get docstrings (NumPy style) describing units and
  axis conventions. Interfaces are documented as if a third party will implement
  them, because they will.
- No network calls or model downloads at import time. Backends that need a model
  fetch it lazily on first use and cache it.
- Pure functions where practical; stages are explicit and individually testable.

## How to work in this repo

- Implement strictly in the phase order of `docs/BUILD_PLAN.md`. Each phase has a
  "Definition of done" and tests that must pass before moving on.
- Build the **synthetic roll generator** early (Phase 1). It renders rolls with
  known ground truth and is the backbone of deterministic testing for the
  lane-finder and note assembler — do not rely on real scans for unit tests.
- When a design decision is ambiguous, prefer: explicit over implicit, measured
  over assumed, reversible over lossy, and "add to review queue" over "guess
  silently".

## Documentation is part of "done"

Every **validated** change (behaviour, defaults, config, CLI, public API, or
workflow) must propagate to *all* forms of documentation in the same change —
documentation is not a follow-up. A change is not finished until:

1. **`README.md`** — the user-facing guide (install, CLI tutorial, configuration,
   troubleshooting, library usage, works-now/roadmap) reflects the new
   behaviour. Keep examples runnable and honest about what ships today.
2. **`CLAUDE.md`** — this contract is updated if constraints, stack, conventions,
   or workflow changed.
3. **The Sphinx docs in `docs/`** (Sphinx + napoleon + myst-parser, hosted on
   Read the Docs) — these largely auto-generate, so keep the *sources* current:
   - API reference comes from the **NumPy-style docstrings** — update them when
     signatures/behaviour change.
   - The configuration reference comes from the **`#:` attribute comments on
     `Config` fields** in `perfora/config.py` — update the comment when you add,
     remove, or change a field (and the `Config` table in the README).
   - `docs/index.md` includes `README.md`, so narrative changes flow through; the
     design docs (`ARCHITECTURE/ALGORITHMS/CLI/BUILD_PLAN`) are linked from
     `docs/design.md`.
   - Verify it still builds: `uv run sphinx-build -b html docs docs/_build/html`.

If a change touches a default or a `Config` field, the new value/name must be
identical across the code, the README configuration table, and the `#:` comment.

## Repo layout (target)

See `docs/ARCHITECTURE.md` for the full tree and the responsibility of each
module. The top level is:

```
perfora/        # the library
  model/        # internal format (dataclasses), geometry, calibration
  sources/      # ImageSource, VideoSource -> canonical RollImage
  pipeline/     # orchestrator, Session (stepwise/preview/override), stages
  text/         # detector/recognizer protocols + offline backends + scope/associate
  io/           # Reader/Writer ABCs, registry, native JSON (+ later MIDI)
  review/       # uncertainty / review-queue handling
  utils/        # imaging + signal helpers
  cli.py        # batch + interactive command-line interface
tests/
docs/
```
