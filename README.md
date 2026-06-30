<div align="center">
  <img src="docs/assets/perfora-logo.svg" alt="perfora" width="420"/>
</div>

# perfora

**Turn a scan or video of a player-piano roll into structured, reversible data:
every perforation as a note positioned in millimetres, and every printed or
handwritten label with its location and meaning.**

perfora measures the roll itself — it does not assume a roll standard. It finds
the lane spacing from the holes, assembles notes, reads the text, and writes
everything to a plain, human-readable file you can analyse, archive, or load
back without losing anything.

- **Inputs:** a flat scan (`.png .jpg .tif .bmp .webp`) or a video of the roll
  moving past a camera (`.mp4 .mov .avi .mkv .webm`).
- **Output:** a `.perfora.json` document — notes (lane, start/end in mm,
  confidence), text regions (with scope and bounding box), and a *review queue*
  of anything the system was unsure about.
- **Units:** everything is millimetres. Turning millimetres into seconds or MIDI
  is left to you (a one-line helper is provided), because that depends on how
  fast the roll was meant to play.

---

## Table of contents

- [Installation](#installation)
- [Tutorial: decode your first roll (command line)](#tutorial-decode-your-first-roll-command-line)
- [Getting good results](#getting-good-results)
- [Configuration (`--config`)](#configuration---config)
- [Reading text (OCR)](#reading-text-ocr)
- [Understanding the output file](#understanding-the-output-file)
- [Using perfora as a Python library](#using-perfora-as-a-python-library)
- [Troubleshooting](#troubleshooting)
- [What works today / roadmap](#what-works-today--roadmap)
- [License](#license)

---

## Installation

perfora is managed with [uv](https://docs.astral.sh/uv/). From a clone of this
repository:

```bash
# core install — enough to decode rolls and read/write the native format
uv sync

# run the command-line tool
uv run perfora --help
```

The core install is intentionally light: it only needs numpy, scipy, pandas,
scikit-image and OpenCV. Reading the **text** on a roll is optional and lives
behind *extras* you add only if you want them:

| Extra | Adds | Install |
|-------|------|---------|
| `tesseract` | printed-text recognition (Tesseract) | `uv sync --extra tesseract` |
| `trocr` | handwriting recognition (TrOCR, downloads a model on first use) | `uv sync --extra trocr` |
| `easyocr` | alternative text detector/recognizer | `uv sync --extra easyocr` |
| `cli` | nicer interactive prompts and inline previews | `uv sync --extra cli` |
| `all` | everything above | `uv sync --extra all` |

> **Tesseract needs a system package too.** The `tesseract` extra installs the
> Python bindings, but you also need the Tesseract engine itself:
> `apt install tesseract-ocr` (Debian/Ubuntu), `brew install tesseract` (macOS),
> or the Windows installer. Without it, text detection still runs but printed
> text is left for review instead of being read.

Everything below assumes you run the tool as `uv run perfora ...`. If you have
installed perfora into an active environment, you can drop the `uv run` prefix.

---

## Tutorial: decode your first roll (command line)

This walks through digitising a single scan. No programming required.

### 1. Decode a scan

```bash
uv run perfora -i my_roll.tif -o my_roll.perfora.json --dpi 600
```

- `-i` is the input scan.
- `-o` is where to write the result.
- `--dpi 600` tells perfora the scan resolution so it can report positions in
  **real millimetres**. Use the DPI your scanner was set to. (See
  [Getting good results](#getting-good-results) if you don't know it.)

That's it. You now have `my_roll.perfora.json` describing the holes and text.

### 2. Decode a whole folder at once

Give several inputs and a directory as the output; you get one file per input,
named after the input:

```bash
uv run perfora -o ./decoded/ --dpi 600 -i scans/*.tif
# -> decoded/<each-scan-name>.perfora.json
```

Images and videos can be mixed in the same command — perfora picks the right
reader from the file extension.

### 3. See what each step did (previews)

If a result looks wrong, ask perfora to save a picture of every stage:

```bash
uv run perfora -i my_roll.tif -o my_roll.perfora.json --dpi 600 \
    --preview-dir ./previews
```

`./previews/` then contains, in order:

```
my_roll__00_input.png        the image perfora actually works on (deskewed,
                             and downscaled if the scan was very large)
my_roll__01_preprocess.png   holes detected as a black/white mask
my_roll__02_holes.png        each hole boxed
my_roll__03_lanes.png        the measured lane lines + density profile
my_roll__04_notes.png        assembled notes, coloured by confidence
my_roll__05_text.png         text regions, labelled by scope
```

Open `__03_lanes.png` first: if the vertical lines sit on the columns of holes,
the lane model is good and the notes will be good.

### 4. List and convert formats

```bash
uv run perfora formats     # what file formats can be read/written
```

`perfora convert IN OUT --to FORMAT` re-encodes an existing document between
registered formats (today the native JSON format is the one that ships; more are
on the [roadmap](#what-works-today--roadmap)).

---

## Getting good results

**Calibration is the one thing worth getting right.** perfora reports positions
in millimetres, and it needs to know the pixel-to-mm scale:

- `--dpi N` — best, if you know the scanner resolution.
- `--physical-width-mm N` — if you don't know the DPI but you can measure the
  roll's physical width (in mm) with a ruler. perfora divides that by the
  detected pixel width.
- If you give neither, perfora still works but positions are in "pixel units"
  (1 mm = 1 px) and it prints a one-line notice. Pitches and relative timing are
  still correct; only the absolute millimetre scale is arbitrary.

**Other tips:**

- **Scan on a plain, contrasting background** (a clean sheet works well). perfora
  isolates the roll by keying on that background — so it copes with a roll of any
  colour, a non-uniform material, and an irregular shape (e.g. a narrowing
  leader at the top). It then straightens and crops to the roll automatically
  (skew is corrected, even on very long rolls).
- A **perforation is read as "a spot that looks like the background, inside the
  roll"** — so it works whether the holes show a bright scanner bed or a dark
  backing through them, and the background itself can never be mistaken for a
  hole.
- Very large scans are downscaled automatically before processing (longest side
  capped at 32000 px); the millimetre calibration is adjusted so your numbers
  stay correct.
- Use `--review fail` in batch scripts to make perfora exit non-zero when it was
  unsure about anything, so you can catch rolls that need a human look.

---

## Configuration (`--config`)

Every tunable threshold lives in a single `perfora.config.Config`. From the
command line you override any of them with a small JSON file:

```bash
echo '{"bridge_gap_mm": 0.0, "binarization_mode": "bright_holes"}' > cfg.json
uv run perfora -i roll.tif -o roll.perfora.json --dpi 600 --config cfg.json
```

You only list the fields you want to change; everything else keeps its default.
The options you are most likely to touch:

| Option | Default | What it does |
|--------|---------|--------------|
| `bridge_gap_mm` | `0.5` | Max gap **along the roll** (mm) between two perforations in a lane that is merged into one note. Lower it (or set `0.0`) if distinct notes get merged; raise it (e.g. `1.5`) for chain-perforated rolls whose notes are dotted columns of holes. |
| `binarization_mode` | `"auto"` | `auto`, `bright_holes`, `dark_holes`, or `adaptive`. Force the hole polarity if `auto` guesses wrong. |
| `min_note_len_mm` | `1.0` | Notes shorter than this are flagged for review. |
| `note_conf_min` | `0.5` | Notes below this confidence are flagged for review. |
| `lane_tol_frac` | `0.25` | How far (as a fraction of lane pitch) a hole may sit from a lane centre before it's flagged `ambiguous_lane`. |
| `max_image_px` | `32000` | Longest side a scan is downscaled to before processing. Keep it under 32767 (an OpenCV limit); lower it if you hit memory pressure. |
| `min_hole_area_mm2` / `max_hole_area_mm2` | `0.5` / `200` | Size gates that reject speckle and tears. |
| `ocr_conf_min` | `0.5` | Recognised text below this confidence is flagged for review. |

The full list (binarization, hole, lane, note, video, scope, and review
thresholds) is the `Config` dataclass in
[`perfora/config.py`](perfora/config.py) — each field is documented there, and
the same names are used in the JSON file and in the Python API
(`perfora.config.Config(...)`).

---

## Reading text (OCR)

With no extras installed, perfora still **finds** text regions and records where
they are — it just leaves the actual reading to you (each is flagged
`needs_review`). Install an extra to have the text read automatically:

- `tesseract` for **printed** labels (titles, composer, dynamics).
- `trocr` for **handwritten** annotations.

```bash
uv sync --extra tesseract        # plus the system Tesseract engine (see Install)
uv run perfora -i my_roll.tif -o my_roll.perfora.json --dpi 600
```

Each text region is given a **scope** that says what it refers to:

- `global_header` / `global_footer` — title/label blocks at the ends of the roll.
- `global_margin` — notes written in the side margins.
- `timeline` — text sitting next to the music; perfora links it to the exact
  notes it spans (e.g. a handwritten "louder" attaches to that passage).

---

## Understanding the output file

A `.perfora.json` file is plain JSON; open it in any editor. The important parts:

- `notes` — a list; each has `lane`, `u_start_mm`, `u_end_mm` (position along the
  roll), `v_center_mm` (across the roll), and `confidence` (0–1).
- `texts` — each has the recognised `text`, its `scope`, `bbox_mm`, `confidence`,
  and `associated_note_ids` (for timeline text).
- `review_queue` — everything uncertain, with a `reason` (e.g.
  `low_ocr_confidence`, `ambiguous_lane`, `short_or_noisy_note`) and a pointer to
  the note or text it concerns. **Nothing is silently dropped** — uncertain
  results are data you can act on, not lost.
- `lane_model` — the measured `pitch_mm`, `v0_mm`, `n_lanes` and a `confidence`.
- `calibration` / `provenance` — how pixels map to mm, and how the file was made.

The format is **lossless and reversible**: reading a file back yields the exact
same model, so it is safe for archiving.

---

## Using perfora as a Python library

The command line is a thin shell over the library. For analysis you can drive it
directly:

```python
import perfora

# Decode (both sources normalise to the same internal model).
doc = perfora.process(perfora.ImageSource("my_roll.tif", dpi=600))
# or:  perfora.process(perfora.VideoSource("my_roll.mp4", dpi=600))

# Notes are in millimetres.
for note in doc.notes:
    print(note.lane, note.u_start_mm, note.u_end_mm, note.confidence)

# Text, with scope and the notes it annotates.
for text in doc.texts:
    print(text.scope, repr(text.text), text.associated_note_ids)

# Whatever the system was unsure about — review, don't lose.
for item in doc.review_queue:
    print(item.reason, item.ref_kind, item.ref_id)

# Tidy notes as a pandas DataFrame for analysis.
df = doc.to_dataframe()

# Reversible I/O with runtime format selection.
perfora.write(doc, "my_roll.perfora.json")
doc2 = perfora.read("my_roll.perfora.json")    # == doc

# Millimetres -> seconds is derived, never stored: supply a feed rate.
seconds = doc.notes[0].duration_seconds(feed_rate_mm_per_s=180.0)
```

### Driving the pipeline stage by stage

Every stage is previewable and its key decisions are overridable, via a
`Session`. This is the surface a correction UI builds on:

```python
from perfora import Session

s = Session(perfora.ImageSource("my_roll.tif", dpi=600))
s.run_all()

# Disagree with the measured pitch? Force it and re-run only what changed.
s.apply_override(lane_pitch_mm=3.0)
s.rerun_from("lanes")          # recomputes lanes -> notes -> text, not the decode
doc = s.ctx.to_document()
```

Tunable thresholds live in a single `perfora.config.Config`; pass one to
`process(..., config=...)` or via `--config file.json` on the command line (see
[Configuration](#configuration---config)).

---

## Troubleshooting

**"no lanes detected / unreadable input" (exit code 3).** perfora could not find
a periodic hole pattern. Usually the scan is too low-resolution, too noisy, or
the holes did not threshold cleanly. Try a higher-quality scan, pass the correct
`--dpi`, or save `--preview-dir` and check `__01_preprocess.png` — if the holes
are not white-on-black there, force the polarity with a config file:
`{"binarization_mode": "bright_holes"}` (or `"dark_holes"`).

**Notes are merged that should be separate** (or, rarely, one note is split into
fragments). perfora bridges only tiny gaps between perforations into a single
note. If distinct notes are being fused, lower or disable the bridge:

```bash
echo '{"bridge_gap_mm": 0.0}' > cfg.json    # never merge: one note per perforation
uv run perfora -i roll.tif -o roll.perfora.json --dpi 600 --config cfg.json
```

If instead a chain-perforated note comes out fragmented, raise it (e.g.
`{"bridge_gap_mm": 1.5}`). See [Configuration](#configuration---config).

**A very large scan is downscaled.** Scans whose longest side exceeds 32000 px
are shrunk before processing (millimetre numbers stay correct), because OpenCV
cannot warp an image with a dimension ≥ 32767. Lower `max_image_px` if you hit
memory pressure; you rarely need to change it otherwise.

**Printed text is not being read** even though detection works. Install the
`tesseract` extra **and** the system Tesseract engine (see
[Installation](#installation)). Without the engine, text regions are detected
but left in the review queue.

**Exit codes:** `0` success · `2` usage error · `3` no lanes / unreadable input ·
`4` the review queue was non-empty and you passed `--review fail`.

---

## What works today / roadmap

**Available now:** image and video decoding (holes → lanes → notes), offline text
detection with optional Tesseract/TrOCR/EasyOCR recognition, the lossless
`native-json` format, and the batch CLI (`process`, `convert`, `formats`).

**Planned:**

- A guided **interactive** CLI (`perfora interactive`) to step through a roll,
  preview each stage, and fix OCR/lane decisions in the terminal.
- A **MIDI** export (`perfora convert roll.perfora.json roll.mid --to midi`).
- A lane→pitch mapping pass to fill in MIDI note numbers.
- Hardening on real-world scans and an interactive correction GUI.

The design behind all of this lives in [`docs/`](docs/): `ARCHITECTURE.md`,
`ALGORITHMS.md`, `CLI.md`, and `BUILD_PLAN.md`.

## License

See [`LICENSE`](LICENSE).
