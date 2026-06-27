# perfora — Build Plan

Implement in this order. Do not start a phase until the previous phase's
**Definition of done** is met and its tests pass. Each phase is shippable on its
own. Cross-references: `ARCHITECTURE.md` (interfaces/data model, §12 interactive,
§13 CLI), `ALGORITHMS.md` (the algorithm specs), `CLI.md` (CLI spec).

Two cross-cutting capabilities are built in from the start rather than bolted on:
**(a)** every stage is previewable and overridable so an external UI / interactive
CLI can drive the pipeline (Architecture §12); **(b)** I/O is a plugin layer with
runtime format selection. Do not defer (a) — stages written without `preview()` /
`interaction_points()` / override-handling will have to be rewritten.

---

## Phase 0 — Skeleton, model, I/O, and the session scaffolding

The user's priority: clean interfaces, reversible I/O, and a UI-drivable pipeline
shell — all before any CV work.

**Tasks**
- Update README.md and LICENSE with correct project name, summary and owner as RedRem95
- Package + `pyproject.toml` (hatchling), extras and `[project.scripts] perfora`
  as in Architecture §9, plus `ruff` + `mypy` (strict on `perfora/`) + `pytest`.
- `perfora.model`: `geometry.py`, `calibration.py`, `document.py` with every
  dataclass/enum from Architecture §3; `RollDocument.to_dataframe()`.
- `perfora.config.Config` (all thresholds, defaults) and `perfora.errors`.
- I/O: `Reader`/`Writer` ABCs, `registry.py` (in-process + entry-point discovery +
  `get_reader`/`get_writer`/`available_formats`), the lossless schema-versioned
  `native-json` format, and top-level `perfora.read`/`perfora.write` (explicit id
  or extension inference, `-`/`_` tolerant).
- **Session scaffolding** (Architecture §12): `Stage` protocol with
  `run`/`preview`/`interaction_points`; `PipelineContext` incl. `overrides`;
  `Overrides` + `NoteEdit`/`TextEdit`; `StagePreview`/`Overlay`;
  `InteractionField`; `ProgressReporter`; and the `Session` shell
  (`step`/`run_to`/`run_all`/`apply_override`/`invalidate_from`/`rerun_from`/
  `snapshot`/`restore`). Implement against a couple of no-op test stages.

**Definition of done**
- A hand-built `RollDocument` round-trips through `native-json` (equal ignoring
  `debug`). An out-of-tree writer registered by entry point is discovered.
- With dummy stages: `Session.step()` advances one stage; `apply_override(...)`
  invalidates downstream and moves the cursor back; `rerun_from` recomputes only
  affected stages; `snapshot()`→`restore()` reproduces session state.
- `mypy` + `ruff` clean; `pytest` green.

**Tests**
- `test_model_roundtrip_native_json`, `test_registry_entry_point_discovery`,
  `test_extension_inference`, `test_config_recorded_in_provenance`.
- `test_session_step_and_invalidate`, `test_session_snapshot_restore`.

---

## Phase 1 — Image geometry core (holes → lanes → notes)

The original roll logic, validated entirely on synthetic ground truth. Every
stage here also implements `preview()` + `interaction_points()` and honours its
overrides.

**Tasks**
- **Synthetic roll generator** `tests/fixtures/synth.py`: render an image from a
  spec `(pitch_mm, notes=[(lane,u0,u1)], skew_deg, noise, illumination, dpi)` and
  return image + ground-truth `RollDocument`.
- `ImageSource` deskew/crop/orient/calibrate (Algorithms §1); honour
  `overrides.page_corners_px` / `orientation`.
- `Preprocess` (§2) honouring `overrides.binarization_mode`; `HoleExtraction` (§3).
- `LaneFinding` (§4): `utils/signal.py` (autocorrelation + FFT pitch, comb fit,
  peak-index regression), windowed consensus, assignment with ambiguous-lane
  review; honour `overrides.lane_pitch_mm`/`lane_v0_mm`/`n_lanes` (skip or seed
  the search).
- `NoteAssembly` (§5) with gap bridging + note confidence; apply
  `overrides.note_edits`.
- Per-stage previews: page-quad, hole boxes, `v`-density profile + lane lines +
  pitch, note spans by confidence. `interaction_points` expose pitch/v0/n_lanes
  and binarization mode.
- Wire `default_pipeline()` (no text stage yet); `perfora.process` = `Session.run_all`.

**Definition of done**
- Clean synthetic rolls (no skew): recovered `pitch_mm` within 1% of truth; all
  ground-truth notes matched (lane exact; `u` endpoints within tolerance); no
  spurious notes.
- ≤3° skew + moderate noise: ≥98% of notes recovered, pitch within 2%.
- A pitch sweep (several unknown pitches) is detected with no standard constant.
- Forcing `lane_pitch_mm` via override changes assignment deterministically and
  `rerun_from("lanes")` recomputes notes only.
- Each stage's `preview()` rasterizes without error.

**Tests**
- `test_pitch_recovery_param_sweep` (hypothesis), `test_lane_assignment_clean`,
  `test_lane_assignment_skewed`, `test_note_assembly_bridging`,
  `test_end_to_end_synth_image`, `test_calibration_dpi_vs_physical_width`.
- `test_override_pitch_changes_assignment`, `test_rerun_from_lanes_scope`.

---

## Phase 2 — Text: detect, recognize, scope, associate

**Tasks**
- `text/base.py` protocols + `DetBox`/`RecognitionResult`; `text/engine.py`
  routing (printed vs handwriting) + px→mm.
- Detectors: `ContourDetector` (no extra deps); `EasyOCRDetector` behind `[easyocr]`.
- Recognizers: `TesseractRecognizer` behind `[tesseract]`; `TrocrRecognizer`
  behind `[trocr]` (lazy model load + cache; `MissingBackendError` if absent).
- `scope.py` (§7.1) and `associate.py` (§7.2).
- `review/queue.py` builders + thresholds (§8), integrated across stages.
- `TextStage`: previews (boxes coloured by scope, recognized string, review flag);
  `interaction_points` for editable text/boxes/scope; apply `overrides.text_edits`.

**Definition of done**
- No OCR extras installed: the text stage still emits detection-only
  `TextRegion`s (`needs_review=True`, `DETECTED_NOT_RECOGNIZED`); core import and
  the geometry path are unaffected.
- With Tesseract: printed synthetic labels read and scoped correctly.
- A `TIMELINE` label over a known `u`-range associates to exactly the GT notes.
- A `text_edit` that retypes an OCR string and reassigns scope survives a
  `rerun_from("text")` and lands in the document.

**Tests**
- `test_text_stage_detection_only_no_backends`, `test_scope_classification`,
  `test_timeline_association_u_overlap`, `test_review_queue_dedupe_and_thresholds`,
  `test_text_edit_override_applied`.
- Backend-marked: `test_tesseract_printed_labels` (skipped without `[tesseract]`).

---

## Phase 3 — Video front end (slit-scan)

**Tasks**
- `VideoSource` (Algorithms §6): per-frame `phaseCorrelate` translation,
  optical-flow fallback, travel-direction auto-detect, slice accumulator,
  lateral-drift correction; honour `overrides.roi_px`/`travel`.
- Report progress per frame and poll `cancelled()` (Architecture §12.5); preview
  the reconstructed strip.
- Feed the strip into the **existing** deskew/crop + pipeline.
- Synthetic video generator in `synth.py`: scroll a known roll past a virtual
  camera at variable speed (+ jitter, lateral wobble), ground-truthed.

**Definition of done**
- A synthetic clip reconstructs to a strip whose `process()` output matches the
  same roll's flat-scan output within tolerance.
- Variable scroll speed does not distort `u`-spacing.
- Periodic holes do **not** ghost (regression guard against feature stitching).
- A long reconstruction can be cancelled cleanly via the reporter.

**Tests**
- `test_video_reconstruction_matches_flat`, `test_variable_speed_no_u_distortion`,
  `test_lateral_wobble_corrected`, `test_video_cancellation`.

---

## Phase 4 — CLI (batch)

Thin shell over the library; no roll logic in `cli.py`. Spec: `CLI.md`.

**Tasks**
- `perfora.cli:main` (argparse): implicit-default `process`; `convert`; `formats`.
- `process`: multiple `-i` inputs, per-input source-type inference (+ override),
  `-o` file/dir semantics, `--format` (`-`/`_` tolerant), `--dpi`/
  `--physical-width-mm`, `--config`, `--preview-dir`, `--roi`/`--travel`,
  `-v/--quiet`, `--review {warn,fail,ignore}`, `--force`. Exit codes per CLI.md §2.
- `convert IN OUT --to FORMAT [--from ID] [--feed-rate-mm-s N]`.
- `formats` prints `available_formats()`.
- `TerminalProgressReporter` / `NullProgressReporter`.

**Definition of done**
- The exact command
  `perfora --format native_json -o OUTDIR -i in1.png in2.mp4` writes two
  `native-json` documents into `OUTDIR` (image + video paths both exercised).
- `perfora formats` lists `native-json`; `--preview-dir` emits per-stage PNGs.
- Usage/IO errors return the documented exit codes.

**Tests**
- `test_cli_process_multi_input_dir_output`, `test_cli_format_underscore_alias`,
  `test_cli_output_path_semantics`, `test_cli_formats_lists_registry`,
  `test_cli_exit_codes`.

---

## Phase 5 — Interactive CLI + finalized UI-driving contract

**Tasks**
- `perfora interactive` (and `process --interactive`) driving a `Session` stage by
  stage per CLI.md §5: run → summary → preview (inline with `[cli]`, else PNG to
  `--preview-dir`; Unicode density sparkline for lanes) → prompt
  accept/edit/re-run/preview/quit.
- Map edits to `apply_override` (scalars/enums; `TextEdit`/`NoteEdit` item loops);
  `rerun_from` on change.
- Review-queue pass (most-uncertain first) writing resolutions back.
- `--save-session`/`--resume` via `Session.snapshot`/`restore`.
- `[cli]` extra (`rich`, `questionary`, `pillow`) detected lazily with `input()` /
  file-preview fallback.
- Document the **UI-driving contract**: everything the interactive CLI does is
  expressible through the public `Session` API — that exact surface is what the
  future GUI reuses; no private CLI-only hooks.

**Definition of done**
- A scripted interactive run (answers fed in) on a synth roll applies an override
  (correct a pitch, fix one OCR box), and the final written document reflects both
  edits.
- Works **without** `[cli]` (plain prompts + PNG previews) and **with** it.
- `--save-session` then `--resume` continues a partially-corrected job and produces
  the same final document as an uninterrupted run.

**Tests**
- `test_interactive_scripted_pitch_and_ocr_edit`,
  `test_interactive_plain_fallback_no_cli_extra`,
  `test_interactive_save_resume_equivalence`.

---

## Phase 6 — Second format (MIDI) + polish

**Tasks**
- `formats/midi.py` writer behind `[midi]` (notes only; needs a feed rate; text
  dropped) + minimal MIDI reader → partial document. Wire into `convert`.
- Optional lane→pitch mapping pass (apply a supplied/guessed standard map to fill
  `NoteEvent.pitch`), separate from the lane-finder.
- Example notebooks: image flow, video flow, walking the review queue,
  round-tripping formats, driving a `Session` from code.

**Definition of done**
- `native-json` → `midi` write produces valid MIDI whose note on/off times match
  `length_mm / feed_rate`.

**Tests**
- `test_midi_write_timing`, `test_lane_to_pitch_mapping_optional`.

---

## Phase 7 — Hardening for real scans & GUI-ready surface

**Tasks**
- A few **real** scan/video fixtures; tune defaults; adaptive-threshold paths for
  uneven lighting.
- A documented, tested example of the GUI round-trip via `Session`: read/restore →
  present review items (each has a bbox) → apply edits → re-run → write back.
- Document the recognizer-plugin path (entry-point group `perfora.recognizers`) so
  a third party can register a cloud backend behind `TextRecognizer`.
- API reference from docstrings.

**Definition of done**
- Real-scan smoke tests pass; no regressions on synthetic suites.
- The `Session`-driven edit/persist example is tested.
- API reference builds.

---

## Global "definition of done" (every phase)

- Public API typed and docstringed (units + axis conventions stated).
- Each new `Stage` implements `run` + `preview` + `interaction_points` and honours
  its overrides; new long stages report progress and honour cancellation.
- `ruff` + `mypy` (strict on `perfora/`) clean; `pytest` green.
- Core install (no extras) imports and runs the image→json path **and** the basic
  CLI (`process`, `convert`, `formats`).
- No roll-standard constants and no third-party roll/lane-finding code anywhere in
  `perfora/` — enforced by review and an import-lint test that fails if a forbidden
  package name appears under `perfora/`.
