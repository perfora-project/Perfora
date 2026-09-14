# AGENTS.md — perfora

> Read this first. It is the contract for how this library is built, and it
> applies to every coding agent working in this repo (and to humans too). The
> deeper design lives in `docs/ARCHITECTURE.md`, `docs/ALGORITHMS.md`, and
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
  `libmagic` is missing (so it never becomes a hard requirement). **On Windows
  the sniffing path is not even attempted** (`cli._libmagic_allowed`): the DLL is
  not shipped, and an incompatible one on `PATH` faults the interpreter, which no
  `except` can catch. `PERFORA_USE_LIBMAGIC=1` opts back in.
- OCR backends are **optional extras**, never imported by the core:
  - `pytesseract` (printed text) — extra `[tesseract]`
  - `transformers` + `torch` for TrOCR handwriting — extra `[trocr]`
  - `easyocr` (detection + light handwriting) — extra `[easyocr]`
- Tooling: `pytest`, `ruff`, `mypy` (strict on `perfora/`), `hatchling` build
  backend. CI runs `ruff check` but **not** `ruff format` — do not reformat files
  wholesale.
- Two console entry points:
  - `perfora` (`perfora.cli:main`), argparse-based so the basic CLI needs no
    extra dependencies; an optional `[cli]` extra (`rich`, `questionary`,
    `pillow`) only upgrades interactive prompts and inline previews, with
    graceful fallback to plain `input()` when it is absent. Subcommands:
    `process` (default), `convert`, `formats`, `sample`.
  - `perfora-notebook` (`perfora.notebook:main`), which copies the bundled
    examples into a working directory and starts a JupyterLab server on the
    quickstart notebook. Needs the `[notebook]` extra (`jupyterlab`,
    `matplotlib`, `pillow`); without it, it prints how to install it and exits
    `3` rather than raising.
- Bundled example data lives in `perfora/resources/` (a package, shipped as
  wheel data): `sample_roll.png` — a *synthetic* roll with exact ground truth
  (25 lanes, 3.0 mm pitch, 34 notes, 300 dpi), regenerated deterministically by
  `scripts/make_sample_roll.py` — and `quickstart.ipynb`. Never commit scans of
  real rolls (rights, provenance, size). `tests/test_resources.py` asserts the
  sample still decodes to its ground truth, so it doubles as a regression test
  for the whole pipeline.
- A `Dockerfile` builds an image whose **default command is the notebook
  server**; every other entry point is reachable by naming it after the image.
  It includes Tesseract but deliberately not TrOCR/EasyOCR (PyTorch bulk).

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

- **Never commit to `main` directly.** Every change goes on a branch
  (`feat/…`, `fix/…`, `docs/…`, `ci/…`, `refactor/…`, `test/…`) and lands through
  a pull request, so CI has run on the exact commit that merges. Squash-merge by
  default; a merge commit when the individual commits carry meaning. A local
  `pre-push` hook enforces this (`./scripts/install-git-hooks.sh`); GitHub cannot,
  while the repository is private on a Free plan — that is a plan limit, not a
  decision, and the workflow is unchanged once it can.
- Releases are tags: `v<version>` matching `project.version`, pushed after the
  changelog entry moves under that version. `release.yml` refuses a mismatch.
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
2. **`AGENTS.md`** — this contract is updated if constraints, stack, conventions,
   or workflow changed. (`CLAUDE.md` only points here; it needs no edit unless
   something Claude Code-specific changed.)
3. **The Sphinx docs in `docs/`** (Sphinx + napoleon + myst-parser, hosted on
   Read the Docs) — these largely auto-generate, so keep the *sources* current:
   - API reference comes from the **NumPy-style docstrings** — update them when
     signatures/behaviour change.
   - The configuration reference comes from the **`#:` attribute comments on
     `Config` fields** in `perfora/config.py` — update the comment when you add,
     remove, or change a field (and the `Config` table in the README).
   - `docs/index.md` includes `README.md`, so narrative changes flow through; the
     design docs (`ARCHITECTURE/ALGORITHMS/CLI/BUILD_PLAN`) are linked from
     `docs/design.md`; `docs/changelog.md` and `docs/contributing.md` include
     the root files of the same name.
   - `docs/glossary.md` (plain-language definitions, `{glossary}` directive) and
     `docs/output.md` (field-by-field walkthrough of `.perfora.json`) are the
     non-technical entry points — a new output field or review reason must be
     added there too.
   - Verify it still builds **warning-free**, because CI and Read the Docs treat
     warnings as errors:
     `uv run sphinx-build -b html -W docs docs/_build/html`.
4. **`CHANGELOG.md`** — an entry under *Unreleased* (Keep a Changelog format).
5. **The quickstart notebook** (`perfora/resources/quickstart.ipynb`) if the
   library surface it demonstrates changed. Ship it with cleared outputs and
   line-list `source` values; `tests/test_resources.py` enforces both and
   compiles every code cell.

If a change touches a default or a `Config` field, the new value/name must be
identical across the code, the README configuration table, and the `#:` comment.

## How to write the human-facing docs

This applies to `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`,
the pages under `docs/`, and issue/PR templates. Write like a developer who
maintains the project, not like a launch post. The text should read as natural,
technical and slightly imperfect.

**Avoid:**

- AI/marketing filler: "the real cost is…", "this is where X comes in", "more
  than just…", "not only X, but also Y", "at its core", "in today's world",
  "seamlessly", "powerful yet simple", "unlock", "leverage", "streamline".
- Dramatic openings, exaggerated claims, rhetorical questions, fake contrasts,
  manufactured punchlines.
- Explaining the obvious to pad length, or turning a plain technical fact into a
  story.
- Marketing language, unless the project genuinely needs it.
- Overusing em dashes, repeating the same paragraph shape, and forcing a
  concluding sentence at the end of every section.
- Anything that sounds like a blog post, product launch or LinkedIn post.

**Prefer:**

- Short, direct sentences. Concrete technical detail. Normal developer
  vocabulary.
- Contractions where they sound natural; "I"/"we" instead of impersonal
  corporate phrasing.
- Saying it plainly, even when the sentence is less elegant.
- Explaining *why* something exists when that context actually helps.
- A slightly informal tone, like docs maintained by a small team.

The test before committing a doc change: *would a developer who actually works on
this repo write it this way?* If a sentence sounds clever, polished or profound,
rewrite it plainer. Don't mention these rules in the docs themselves.

## Repository infrastructure

- **License: Apache-2.0** (`LICENSE` + `NOTICE`), declared as a PEP 639
  expression in `pyproject.toml`. Chosen over copyleft so research and archive
  institutions can adopt it and cite it; contributions come in under the same
  license (no CLA).
- **Citation:** `CITATION.cff` (validated with `uvx cffconvert --validate`), plus
  the README's *Citing perfora* section. A Zenodo DOI and a method paper are
  pending; both are marked TODO in the file.
- **CI** (`.github/workflows/ci.yml`) gates: `ruff check`, `mypy`, pytest on
  Linux/macOS/Windows × Python 3.11–3.13, a **core-install-only** job that fails
  if the light dependency set stops being sufficient, a Tesseract-extras job, a
  wheel smoke test that decodes the bundled sample, and a `-W` docs build. CI
  runs with `UV_LOCKED=1`, so commit a refreshed `uv.lock` whenever
  `pyproject.toml` changes.
- **Releases** are tag-driven (`v*` → `.github/workflows/release.yml`): the tag
  must equal `project.version`, the wheel is smoke-tested, and the artifacts are
  attached to a GitHub release. PyPI publishing is prepared but commented out.
- Also present: container builds to GHCR, CodeQL, Dependabot (uv + actions +
  docker), issue forms (including a non-technical "a roll came out wrong" form),
  a PR template mirroring these rules, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`.

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
  resources/    # bundled sample roll + quickstart notebook (wheel data)
  cli.py        # batch + interactive command-line interface
  notebook.py   # `perfora-notebook` launcher (needs the [notebook] extra)
tests/
docs/
scripts/        # maintenance scripts (sample-roll generator, probes)
.github/        # CI, release, docker, CodeQL, dependabot, issue/PR templates
```
