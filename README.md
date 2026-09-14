<div align="center">
  <img src="docs/assets/perfora-logo.svg" alt="perfora" width="420"/>
</div>

<!-- sphinx-docs-start -->

# perfora

perfora reads a scan (or a video) of a player-piano roll and turns it into data:
every perforation as a note with a lane and a start/end position, plus the
printed and handwritten text on the roll with its position and what it refers to.
All positions come out in millimetres of paper.

[![CI](https://github.com/perfora-project/Perfora/actions/workflows/ci.yml/badge.svg)](https://github.com/perfora-project/Perfora/actions/workflows/ci.yml)
[![Documentation](https://readthedocs.org/projects/perfora/badge/?version=latest)](https://perfora.readthedocs.io)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/perfora-project/Perfora/blob/main/LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

---

## What perfora is for

Photographing a roll is easy. Getting music out of the photo is the hard part. A
scan is a picture of a paper strip with holes in it, and to read it you need the
lane grid: which column of holes belongs to which key. That grid isn't printed
anywhere on the roll, it differs between manufacturers and standards, and old
paper has usually shrunk, so you can't just hardcode a pitch and hope. perfora
measures the grid from the holes in the scan in front of it.

A few decisions that shape everything else:

- **Lane spacing is measured, not assumed.** Rare, house-specific or unknown roll
  formats work with no configuration. If you do know the lane count, pass
  `--lanes N` and perfora treats your number as ground truth.
- **Positions are millimetres, not pixels and not seconds.** A roll played faster
  is a different performance, so perfora stores the measurement and leaves timing
  to you: pick a feed rate and convert when you need to.
- **Uncertain results are recorded, not dropped.** Every note and text region has
  a confidence, and anything below a threshold lands in a *review queue* with a
  reason attached, so you can check it instead of just trusting it.
- **Text is read along with the holes.** Titles, labels and handwritten
  annotations, each with its position. Text sitting beside the music is linked
  to the notes it spans, so a pencilled "slower here" stays attached to that
  passage.
- **The output format is lossless.** Reading a file back gives the same data, and
  the file records the settings that produced it.

perfora doesn't decide what the music means. It won't map lanes to MIDI pitches,
guess a tempo, or "clean up" a roll to make it sound better. Those are
interpretive calls, and putting them in the archive file would throw away
information you can't get back.

### Who this is for

- **Researchers and archivists** who want measurable data out of a roll
  collection (hole positions, note lengths, annotations) without committing to
  one playback interpretation. The standard path needs no programming: one
  command, or a notebook with a Run button.
- **Digitization projects** that need something scriptable and reproducible:
  batch processing, a record of every setting used, and a list of the cases a
  human should look at.
- **Developers** who want a typed Python library with every stage previewable and
  overridable, to build a correction UI or a different export on top of.

### Where it stands today

Image and video decoding into notes works, text detection works (recognition is
optional, see [Reading text](#reading-text-ocr)), and the native format round-trips.
All of it is covered by a deterministic test suite built on synthetic rolls with
known ground truth. MIDI export, lane→pitch mapping and a correction GUI aren't
done yet; see [What works today / roadmap](#what-works-today--roadmap).

Real-world scans will still hit rough edges. If a roll comes out wrong, please
[report it](https://github.com/perfora-project/Perfora/issues/new?template=01-roll-decoded-wrong.yml);
those reports are what the algorithms improve from.

---

## Contents

- [Quick start](#quick-start) — install, then decode a roll
- [Work in a notebook instead](#work-in-a-notebook-instead) — a browser, no terminal
- [Run it without installing anything](#run-it-without-installing-anything) — Docker
- [Getting good results](#getting-good-results)
- [Configuration (`--config`)](#configuration---config)
- [Reading text (OCR)](#reading-text-ocr)
- [Understanding the output file](#understanding-the-output-file)
- [Using perfora as a Python library](#using-perfora-as-a-python-library)
- [Troubleshooting](#troubleshooting)
- [What works today / roadmap](#what-works-today--roadmap)
- [Contributing](#contributing)
- [Citing perfora](#citing-perfora)
- [License](#license)

---

## Quick start

### 1. Install

You need [Python 3.11 or newer](https://www.python.org/downloads/). The project
is managed with [uv](https://docs.astral.sh/uv/), which handles the Python
version and the dependencies for you. Install uv once:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then:

```bash
git clone https://github.com/perfora-project/Perfora.git
cd Perfora
uv sync
uv run perfora --version
```

If that prints a version number, you're set.

> The examples below all use `uv run perfora ...`. If you installed perfora into
> your own environment, drop the `uv run`.

### 2. Decode the sample roll

perfora ships a small example roll so you can see a complete result before
scanning anything:

```bash
uv run perfora sample ./my-first-roll
uv run perfora -i ./my-first-roll/sample_roll.png -o ./my-first-roll/out.perfora.json --dpi 300 -v
```

It walks through its five stages and ends with something like:

```
[perfora] lanes: done — pitch_mm=2.9974, n_lanes=25, confidence=0.997, method=comb-fit
[perfora] notes: done — n_notes=34, lanes_used=25, lanes_unused=0
```

The sample really does have 25 lanes at 3.0 mm spacing and 34 notes, and the only
thing perfora was told is the scan resolution. `out.perfora.json` holds the
result.

### 3. Decode your own scan

```bash
uv run perfora -i my_roll.tif -o my_roll.perfora.json --dpi 600
```

- `-i` — your scan (`.png .jpg .tif .bmp .webp`) or a video of the roll moving
  past a camera (`.mp4 .mov .avi .mkv .webm`).
- `-o` — where to write the result.
- `--dpi 600` — the resolution your scanner was set to. This is the one setting
  worth getting right; without it perfora can't report real millimetres. If you
  don't know it, see [Getting good results](#getting-good-results).

That's the standard path. Two things that help when it doesn't go smoothly:

**Look at what it did.** Ask for a picture of every stage:

```bash
uv run perfora -i my_roll.tif -o my_roll.perfora.json --dpi 600 --preview-dir ./previews
```

`./previews/` then contains, in order:

```
my_roll__00_input.png        the image perfora actually works on (deskewed,
                             and downscaled if the scan was very large)
my_roll__01_preprocess.png   perforations isolated as a black/white mask
my_roll__02_holes.png        each perforation boxed
my_roll__03_lanes.png        the measured lane lines + density profile
my_roll__04_notes.png        assembled notes, coloured by confidence
my_roll__05_text.png         text regions, labelled by scope
```

Open `__03_lanes.png` first. If the vertical lines sit on the columns of holes,
the lane model is right and the rest will follow.

**Do a whole folder at once.** Pass several inputs and a directory as output:

```bash
uv run perfora -o ./decoded/ --dpi 600 -i scans/*.tif
# -> decoded/<each-scan-name>.perfora.json
```

Images and videos can be mixed in one command. perfora identifies each file by
sniffing its content (via `libmagic`/`python-magic`), so a wrong or missing
extension is still handled correctly. If python-magic or the system `libmagic`
isn't available it falls back to matching the extension, without an error. Use
`--source-type {image,video}` to force it.

> **On Windows, extension matching is the default.** python-magic needs a
> `libmagic` DLL it doesn't ship, and an incompatible one on `PATH` can take down
> the interpreter, so perfora doesn't try it there. Name your files with the
> right extension (or pass `--source-type`) and everything works. If you've
> installed a libmagic you trust, set `PERFORA_USE_LIBMAGIC=1` to switch sniffing
> back on.

### 4. Read the result

The output is plain JSON, so any editor will do. `notes`, `texts` and
`review_queue` are the interesting parts, and every number is in millimetres. See
[Understanding the output file](#understanding-the-output-file), or the
field-by-field walkthrough in
[Output format](https://perfora.readthedocs.io/en/latest/output.html). The
[Glossary](https://perfora.readthedocs.io/en/latest/glossary.html) defines the
terms perfora uses, without assuming you write code.

---

## Work in a notebook instead

If you'd rather not work in a terminal, there's a guided notebook. It loads a
roll, shows each stage as a picture, draws the result as a piano roll, and saves
the data, one cell at a time with an explanation next to each step.

```bash
uv sync --extra notebook       # once
uv run perfora-notebook
```

Your browser opens on `quickstart.ipynb` with the sample roll next to it. Run
cells with **Shift+Enter**. Normally the only cell you edit is the first one
(which file, which resolution, how many lanes). Drag your own scan into the file
list on the left to use it instead.

The notebook and sample are copied into `./perfora-notebooks/` (change it with
`--dir`), so your edits survive an upgrade. `perfora-notebook --help` lists the
rest of the options (port, bind address, `--refresh` to restore the original
notebook).

---

## Run it without installing anything

The container image has the pipeline, the examples and the Tesseract OCR engine
in it, so Docker is the only thing you need locally.

```bash
# Build it from a clone (works today, also while the repository is private)
docker build -t perfora .

# Guided notebook — open the URL it prints, http://127.0.0.1:8888/...
docker run --rm -p 8888:8888 -v "$PWD:/data" perfora

# Or run the command-line tool, on files from the current folder
docker run --rm -v "$PWD:/data" perfora \
    perfora -i /data/my_roll.tif -o /data/my_roll.perfora.json --dpi 600
```

The default command is the notebook server. Naming any other command after the
image runs that instead (`perfora`, `perfora sample`, `perfora formats`, a shell,
…). `/data` is where it reads and writes, so mount the folder with your scans
there.

> **"Permission denied" writing to `/data`?** The container runs as an
> unprivileged user (uid 1000). If your host folder belongs to a different user
> id, add `--user "$(id -u):$(id -g)"` to the `docker run` line so it writes as
> you.

Prebuilt images go to `ghcr.io/perfora-project/perfora` on every change to `main`
and on every release tag. While the repository is private you have to
authenticate to GHCR to pull them (`docker login ghcr.io`); building locally
always works.

> Handwriting recognition (TrOCR) is **not** in the image, because it would drag
> in PyTorch and multiply the download size. Add it in a derived image if you
> need it: `FROM perfora` plus `RUN pip install 'perfora[trocr]'`.

---

## Getting good results

Calibration is the thing to get right. perfora reports millimetres, so it needs
the pixel-to-mm scale:

- `--dpi N` — best, if you know the scanner resolution.
- `--physical-width-mm N` — if you don't know the DPI but can measure the roll's
  width with a ruler. perfora divides that by the detected pixel width.
- With neither, it still runs, but positions are in "pixel units" (1 mm = 1 px)
  and you get a one-line notice. Pitches and relative timing are still correct;
  only the absolute scale is arbitrary.

Other things that help:

- **Scan on a plain, contrasting background** (a clean sheet works well). perfora
  isolates the roll by keying on that background, so a roll of any colour, an
  uneven material or an irregular shape (a narrowing leader at the top, say) is
  fine. It straightens and crops to the roll automatically, including skew on
  very long rolls.
- A perforation is detected as "a spot that looks like the background, inside the
  roll". That works whether the holes show a bright scanner bed or a dark backing
  through them, and the background itself can never be mistaken for a hole.
- Very large scans are downscaled before processing (longest side capped at
  32000 px). The calibration is adjusted with them, so your millimetres stay
  correct.
- **If you know the lane count**, pass `--lanes N`. perfora then treats it as
  ground truth: it forces the count and octave-corrects the pitch. See
  [Known lane count](#known-lane-count).
- Use `--review fail` in batch scripts to get a non-zero exit when anything was
  uncertain, so rolls that need a human can't slip past.
- `-v` narrates each stage on stderr, `-vv` adds per-unit progress bars for the
  slow stages (video reconstruction, OCR). `--quiet` suppresses everything,
  including the calibration notice.

---

## Configuration (`--config`)

Every tunable threshold lives in one `perfora.config.Config`. From the command
line you override any of them with a small JSON file:

```bash
echo '{"bridge_gap_mm": 0.0, "binarization_mode": "bright_holes"}' > cfg.json
uv run perfora -i roll.tif -o roll.perfora.json --dpi 600 --config cfg.json
```

List only the fields you want to change; the rest keep their defaults. The ones
you're most likely to touch:

| Option | Default | What it does |
|--------|---------|--------------|
| `bridge_gap_mm` | `0.5` | Max gap **along the roll** (mm) between two perforations in a lane that still merges into one note. Lower it (or set `0.0`) if distinct notes get merged; raise it (e.g. `1.5`) for chain-perforated rolls whose notes are dotted columns of holes. |
| `binarization_mode` | `"auto"` | `auto`, `bright_holes`, `dark_holes`, or `adaptive`. Force the hole polarity if `auto` gets it wrong. |
| `min_note_len_mm` | `1.0` | Notes shorter than this are flagged for review. |
| `note_conf_min` | `0.5` | Notes below this confidence are flagged for review. |
| `n_lanes` | `0` | Known number of lanes (keyboard keys). `0` auto-detects. Set it to the real count (or use `--lanes N`) to treat it as ground truth: the count is forced and exactly that many equally-spaced lanes are fit across the roll, octave-correcting the pitch and removing far-edge drift. See [Known lane count](#known-lane-count). |
| `lane_tol_frac` | `0.25` | How far (as a fraction of lane pitch) a hole may sit from a lane centre before it's flagged `ambiguous_lane`. |
| `max_image_px` | `32000` | Longest side a scan is downscaled to before processing (see [Resolution](#resolution-and-hole-detection)). Keep it under 32767 (an OpenCV limit); lower it if you hit memory pressure. |
| `opening_kernel_px` | `3` | Morphological-opening kernel that **detaches touching perforations**. Increase to `4`–`5` to split adjacent holes that merge into one blob; too large erodes small holes. |
| `speckle_min_area_px` | `9` | Connected components smaller than this (px) are dropped as speckle. Lower it if genuinely small holes are being removed. |
| `min_hole_area_mm2` / `max_hole_area_mm2` | `0.5` / `200` | Size gates (mm²) that reject speckle and tears. |
| `min_solidity` | `0.7` | Minimum blob solidity. Two holes joined by a thin bridge form a low-solidity "dumbbell"; raise this to reject them. |
| `hole_split_watershed` | `false` | Split **touching** perforations with a distance-transform watershed. Good for round holes that merge side-by-side; leave off for slot-shaped perforations, it can over-split them. |
| `hole_split_min_distance_px` | `4` | Minimum separation (px) between hole centres for the watershed — roughly the smallest hole spacing to resolve. |
| `ocr_conf_min` | `0.5` | Recognised text below this confidence is flagged for review. |

### Resolution and hole detection

perfora works at the scan's native resolution and only downscales if the longest
side exceeds `max_image_px` (32000 px). So to process at a higher resolution:
scan at a higher DPI (holes need to be several pixels wide to resolve, so aim
for a lane pitch of ≥ 6–8 px), and make sure `max_image_px` is at least the
scan's longest side, but under 32767.

If **small perforations that sit close together merge into one big hole**, they
were joined in the binary mask. In order of effect:

1. **Scan/keep more resolution.** Merging is most common when holes are only a
   few pixels apart. Higher DPI and a larger `max_image_px` separate them.
2. **Raise `opening_kernel_px`** (e.g. `4`). The morphological opening breaks
   thin connections between touching blobs. Don't overdo it or small holes
   vanish.
3. **Raise `min_solidity`** to reject merged "dumbbell" blobs outright.
4. **Enable watershed splitting** for perforations that genuinely touch, with no
   gap at all: `hole_split_watershed: true`. It cuts touching blobs apart at
   their necks using a distance-transform watershed, seeded by hole centres kept
   `hole_split_min_distance_px` apart. Best for round holes; it can over-split
   long slot-shaped perforations, so leave it off for slot rolls.
5. Merging *along the roll* (a column of holes fused into one note) is a
   different knob: `bridge_gap_mm`, set lower or to `0.0`.

```bash
echo '{"hole_split_watershed": true, "hole_split_min_distance_px": 5}' > cfg.json
uv run perfora -i scan.tif -o out.perfora.json --dpi 600 --config cfg.json
```

### Known lane count

By default perfora measures how many lanes a roll has; it never assumes a
standard. If you already know the count (an 88-key roll, say), tell it, and the
number is treated as ground truth:

```bash
uv run perfora -i roll.tif -o roll.perfora.json --dpi 600 --lanes 88
```

(or `{"n_lanes": 88}` in `--config`). When set, perfora:

1. **forces the reported lane count** to exactly that number.
2. **octave-corrects the measured pitch** against the roll width. If the
   detector latched onto twice or half the true spacing, which is the classic
   periodicity failure, the known count snaps it back.
3. **anchors exactly N equally-spaced lanes between the outermost used lanes**:
   lane 0 through the leftmost hole, lane N-1 through the rightmost, instead of
   laying down a locally-measured pitch. Anchoring both ends is what guarantees
   the grid reaches every hole. Otherwise a tiny pitch error compounds across a
   wide many-lane roll into a full lane of drift, and the far-side holes get no
   lane at all.

The spacing still comes from *your* holes (the outermost used lanes set it) and
the lanes stay equally spaced. Leave it at the default `0` to auto-detect.
`--lanes` wins over an `n_lanes` in `--config`.

The full list (binarization, hole, lane, note, video, scope and review
thresholds) is the `Config` dataclass in
[`perfora/config.py`](https://github.com/perfora-project/Perfora/blob/main/perfora/config.py).
Each field is documented there and rendered in the
[Configuration reference](https://perfora.readthedocs.io/en/latest/configuration.html);
the same names are used in the JSON file and in the Python API
(`perfora.config.Config(...)`).

---

## Reading text (OCR)

With no extras installed, perfora still finds text regions and records where
they are, it just doesn't read them (each is flagged `needs_review`). Install an
extra to get the text read:

| Extra | Adds | Install |
|-------|------|---------|
| `tesseract` | printed-text recognition (Tesseract) | `uv sync --extra tesseract` |
| `trocr` | handwriting recognition (TrOCR; downloads a model on first use) | `uv sync --extra trocr` |
| `easyocr` | alternative text detector/recognizer | `uv sync --extra easyocr` |
| `notebook` | the guided `perfora-notebook` | `uv sync --extra notebook` |
| `cli` | nicer prompts and inline previews | `uv sync --extra cli` |
| `all` | everything above | `uv sync --extra all` |

> **Tesseract needs a system package too.** The `tesseract` extra installs the
> Python bindings; the engine itself comes from `apt install tesseract-ocr`
> (Debian/Ubuntu), `brew install tesseract` (macOS), or the Windows installer.
> Without it, detection still runs but printed text is left for review instead of
> being read. The Docker image includes it.

Each text region gets a **scope** saying what it refers to:

- `global_header` / `global_footer` — title/label blocks at the ends of the roll.
- `global_margin` — notes written in the side margins.
- `timeline` — text next to the music; perfora links it to the notes it spans, so
  a handwritten "louder" attaches to that passage.

The core install stays light on purpose: numpy, scipy, pandas, scikit-image,
OpenCV and the small python-magic. Machine-learning dependencies are only
imported when you select a backend that needs them.

---

## Understanding the output file

A `.perfora.json` file is plain JSON. Everything lives under a `document` key:

- `notes` — each has `lane`, `u_start_mm`, `u_end_mm` (position along the roll),
  `v_center_mm` (across the roll), and `confidence` (0–1).
- `texts` — the recognised `text`, its `scope`, `bbox_mm`, `confidence`, and
  `associated_note_ids` for timeline text.
- `review_queue` — everything uncertain, with a `reason` (`low_ocr_confidence`,
  `ambiguous_lane`, `short_or_noisy_note`, …) and a pointer to the note or text
  it concerns. Nothing is dropped silently, so these are results you can act on.
- `lane_model` — the measured `pitch_mm`, `v0_mm`, `n_lanes` and a `confidence`.
- `calibration` / `provenance` — how pixels map to mm, and how the file was made,
  including every configuration value in force during the run.

Reading a file back gives the exact same model, which is what makes it safe to
archive. Full field-by-field reference:
[Output format](https://perfora.readthedocs.io/en/latest/output.html).

```bash
uv run perfora formats     # what file formats can be read/written
```

`perfora convert IN OUT --to FORMAT` re-encodes an existing document between
registered formats. Today the native JSON format is the only one that ships; more
are on the [roadmap](#what-works-today--roadmap).

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

# Whatever the pipeline was unsure about.
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

The bundled example is available programmatically, which makes it a convenient
fixture for your own experiments:

```python
from perfora.resources import SAMPLE_ROLL_DPI, sample_roll_path

doc = perfora.process(perfora.ImageSource(sample_roll_path(), dpi=SAMPLE_ROLL_DPI))
assert len(doc.notes) == 34          # its ground truth is known exactly
```

### Driving the pipeline stage by stage

Every stage can be previewed and its key decisions overridden, through a
`Session`. This is the surface a correction UI would build on:

```python
from perfora import Session

s = Session(perfora.ImageSource("my_roll.tif", dpi=600))
s.run_all()

# Disagree with the measured pitch? Force it and re-run only what changed.
s.apply_override(lane_pitch_mm=3.0)
s.rerun_from("lanes")          # recomputes lanes -> notes -> text, not the decode
doc = s.ctx.to_document()
```

Thresholds live in a single `perfora.config.Config`; pass one to
`process(..., config=...)` or use `--config file.json` on the command line (see
[Configuration](#configuration---config)). The full API is documented at
[perfora.readthedocs.io](https://perfora.readthedocs.io/en/latest/api.html).

---

## Troubleshooting

**"no lanes detected / unreadable input" (exit code 3).** perfora couldn't find a
periodic hole pattern. Usually the scan is too low-resolution, too noisy, or the
holes didn't threshold cleanly. Try a better scan, pass the correct `--dpi`, or
save `--preview-dir` and look at `__01_preprocess.png`. If the holes aren't
white-on-black there, force the polarity with a config file:
`{"binarization_mode": "bright_holes"}` (or `"dark_holes"`).

**The lane lines drift away from the holes** across the width of the roll. Pass
the true lane count with `--lanes N`, which anchors the grid at both edges
instead of extrapolating a measured pitch. See
[Known lane count](#known-lane-count).

**Notes are merged that should be separate** (or, less often, one note comes out
in fragments). perfora bridges only tiny gaps between perforations. If distinct
notes are being fused, lower or disable the bridge:

```bash
echo '{"bridge_gap_mm": 0.0}' > cfg.json    # never merge: one note per perforation
uv run perfora -i roll.tif -o roll.perfora.json --dpi 600 --config cfg.json
```

If instead a chain-perforated note comes out fragmented, raise it (e.g.
`{"bridge_gap_mm": 1.5}`). See [Configuration](#configuration---config).

**A very large scan is downscaled.** Scans whose longest side exceeds 32000 px
are shrunk before processing, because OpenCV can't warp an image with a dimension
≥ 32767. Millimetre numbers stay correct. Lower `max_image_px` if you hit memory
pressure; otherwise you rarely need to touch it.

**Printed text isn't being read** even though detection works. Install the
`tesseract` extra *and* the system Tesseract engine (see
[Reading text](#reading-text-ocr)). Without the engine, text regions are detected
but left in the review queue.

**`perfora-notebook` says Jupyter isn't installed.** Run
`uv sync --extra notebook` (or `pip install 'perfora[notebook]'`). The plain
command-line tool doesn't need it.

**Exit codes:** `0` success · `2` usage error · `3` no lanes / unreadable input ·
`4` the review queue was non-empty and you passed `--review fail`.

Still stuck? Open a
[question issue](https://github.com/perfora-project/Perfora/issues/new?template=04-question.yml)
(non-technical questions are welcome), or, if a roll decodes badly, use the
[roll report form](https://github.com/perfora-project/Perfora/issues/new?template=01-roll-decoded-wrong.yml).

---

## What works today / roadmap

**Available now:** image and video decoding (holes → lanes → notes), offline text
detection with optional Tesseract/TrOCR/EasyOCR recognition, the lossless
`native-json` format, the batch CLI (`process`, `convert`, `formats`, `sample`),
the guided notebook (`perfora-notebook`), and a container image.

**Planned:**

- A guided **interactive** CLI (`perfora interactive`) to step through a roll,
  preview each stage, and fix OCR/lane decisions in the terminal.
- A **MIDI** export (`perfora convert roll.perfora.json roll.mid --to midi`).
- A lane→pitch mapping pass to fill in MIDI note numbers.
- Hardening against real-world scans, and an interactive correction GUI.

The design behind all of this is in
[`docs/`](https://github.com/perfora-project/Perfora/tree/main/docs):
`ARCHITECTURE.md`, `ALGORITHMS.md`, `CLI.md`, and `BUILD_PLAN.md`.

---

## Contributing

Contributions are welcome from programmers and from people who work with rolls.
A careful report of a roll perfora got wrong is as useful as a patch. See
[CONTRIBUTING.md](https://github.com/perfora-project/Perfora/blob/main/CONTRIBUTING.md)
for the development setup, the checks that have to pass, and the project rules
(measured spacing, millimetres out of every stage, nothing uncertain discarded).
Participation is governed by the
[Code of Conduct](https://github.com/perfora-project/Perfora/blob/main/CODE_OF_CONDUCT.md).
Security reports go through
[SECURITY.md](https://github.com/perfora-project/Perfora/blob/main/SECURITY.md).

---

## Citing perfora

If perfora contributes to published work, please cite it. GitHub's "Cite this
repository" button (in the sidebar) generates APA and BibTeX from
[`CITATION.cff`](https://github.com/perfora-project/Perfora/blob/main/CITATION.cff);
a BibTeX entry for the current state is:

```bibtex
@software{perfora,
  author  = {Vollmer, Alexander},
  title   = {{perfora}: digitizing player-piano rolls into a reversible,
             millimetre-based model},
  url     = {https://github.com/perfora-project/Perfora},
  version = {0.1.0},
  year    = {2026}
}
```

Please also state which version you used (`perfora --version`) and the settings
behind your results. You don't have to track those by hand: every output file
records its full configuration under `provenance.params`, which is what a methods
section needs.

An archived release with a DOI and a paper describing the method are planned.
This section and `CITATION.cff` will be updated with both, and the DOI takes
precedence once it exists.

---

## License

perfora is released under the
[Apache License 2.0](https://github.com/perfora-project/Perfora/blob/main/LICENSE):
permissive, with an explicit patent grant, so academic, archival and commercial
projects can all use it. Attribution notices must be kept; see
[`NOTICE`](https://github.com/perfora-project/Perfora/blob/main/NOTICE).
