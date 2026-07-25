# Changelog

All notable changes to perfora are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While perfora is
pre-1.0, the public API may still change between minor versions.

## [Unreleased]

### Added

- **First-run examples.** A bundled synthetic sample roll with known ground
  truth (25 lanes, 3.0 mm pitch, 34 notes, 300 dpi) and a guided quickstart
  notebook, copied out with the new `perfora sample [DIR]` subcommand. The roll
  is regenerated deterministically by `scripts/make_sample_roll.py`.
- **`perfora-notebook`** — starts a local Jupyter server on the quickstart
  notebook, for users who would rather not work in a terminal. Requires the new
  `notebook` extra; without it, it explains how to install it instead of failing
  with a traceback.
- **Container image** (`ghcr.io/perfora-project/perfora`) with the pipeline, the
  examples and Tesseract preinstalled. Its default command is the notebook
  server; every other entry point is available by naming it after the image.
- `perfora --version` / `-V`.
- Documentation: a plain-language [glossary](https://perfora.readthedocs.io/en/latest/glossary.html) and a field-by-field
  [walkthrough of the output file](https://perfora.readthedocs.io/en/latest/output.html).
- Project infrastructure: CI (lint, strict typing, tests on Linux/macOS/Windows
  and Python 3.11–3.13, a core-install-only job, an OCR-extras job, a wheel
  smoke test, and a docs build with warnings as errors), tag-driven GitHub
  releases, container builds, CodeQL, Dependabot, issue and pull-request
  templates, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, and
  `CITATION.cff`.

### Fixed

- **Windows: source-type sniffing no longer risks crashing the interpreter.**
  python-magic needs a `libmagic` DLL it does not ship, and loading an
  incompatible one (Git for Windows installs one) faults the process rather than
  raising `ImportError`, which no `except` can recover from. perfora now skips
  the sniffing path on Windows and uses its documented extension fallback;
  `PERFORA_USE_LIBMAGIC=1` opts back in for anyone who has installed a
  known-good libmagic.

### Changed

- **License is now Apache-2.0** (previously AGPL-3.0), with a `NOTICE` file — a
  permissive license with an explicit patent grant fits research software that is
  meant to be adopted and cited. The project has had a single author, so no
  contributor consent was required.
- Package metadata: PEP 639 license expression, classifiers, keywords, and
  project URLs; the repository now lives at `perfora-project/Perfora` and all
  links point there.

## [0.1.0] — unreleased

The initial pipeline, built phase by phase:

- **Sources** — flat scans and videos normalise to one canonical `RollImage`,
  with content-based type detection (libmagic) and a graceful fallback to
  extension matching. Oversized scans are downscaled before warping, with the
  calibration adjusted so millimetres stay correct.
- **Geometry** — background-keyed segmentation, deskewing, hole detection
  (with optional watershed splitting of touching perforations), *measured* lane
  finding (never an assumed standard), and note assembly with confidence.
- **Known lane count** as ground truth (`--lanes N` / `Config.n_lanes`):
  octave-corrects a mis-locked pitch and anchors exactly N equally-spaced lanes
  between the outermost used lanes.
- **Text** — detector/recognizer protocols with offline backends (contour
  detection, optional Tesseract, TrOCR, EasyOCR), scope classification
  (`global_header`, `global_footer`, `global_margin`, `timeline`) and association
  of timeline text with the notes it spans.
- **Model and I/O** — millimetre-based dataclasses, a `Calibration` recording the
  px↔mm relationship, a review queue for everything uncertain, and a lossless
  `native-json` reader/writer behind a format registry.
- **Pipeline surfaces** — one-shot `perfora.process`, a stepwise `Session` with
  per-stage previews and overrides, and a batch CLI (`process`, `convert`,
  `formats`) with numbered stage previews and verbose narration.

[Unreleased]: https://github.com/perfora-project/Perfora/compare/main...HEAD
