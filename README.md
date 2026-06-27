<div align="center">
  <img src="docs/assets/perfora-logo.svg" alt="perfora" width="420"/>
</div>

# perfora

**Digitize player-piano roll scans into a structured, reversible representation
of holes and text.**

perfora reads a flat scan or a video of a piano roll and extracts (1) the
perforations as note events positioned in physical units along the roll, and
(2) the text on the roll — printed labels and handwritten annotations — each
with a bounding box and a *scope* connecting it either to the whole roll or to a
specific stretch of the music. It is a library with clean, documented interfaces
and a pluggable I/O layer, designed so analysis tools and (later) interactive
correction UIs can build on top of it.

perfora implements its own lane-finding and roll-parsing from generic image and
signal processing primitives; it does not depend on any existing piano-roll
decoder.

## Status

Pre-implementation. This repository currently contains the design handover for
building the library. See the docs below.

## Documentation

- [`CLAUDE.md`](CLAUDE.md) — mission, hard constraints, stack, conventions.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — modules, data model,
  interfaces, the I/O plugin layer, the UI-drivable session (previews,
  overrides, step-by-step execution), package tree.
- [`docs/ALGORITHMS.md`](docs/ALGORITHMS.md) — the original algorithms
  (deskew, hole extraction, spacing auto-detection & lane assignment, note
  assembly, slit-scan video reconstruction, text scope & timeline association).
- [`docs/CLI.md`](docs/CLI.md) — command-line interface: batch decode, convert,
  and the guided interactive mode.
- [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) — phased implementation plan with
  per-phase definitions of done and tests.

## Intended usage (vision)

```python
import perfora

# 1. Pick a source; both normalize to the same canonical RollImage.
src = perfora.ImageSource("roll_scan.tif")          # or perfora.VideoSource("roll.mp4")

# 2. Run the pipeline -> internal model (everything in millimetres).
doc = perfora.process(src)                            # returns a RollDocument

# 3. Inspect results.
for note in doc.notes:
    print(note.lane, note.u_start_mm, note.u_end_mm, note.confidence)

for text in doc.texts:
    print(text.scope, text.text, text.bbox_mm)

# 4. Anything the recognizer was unsure about is queued, not lost.
for item in doc.review_queue:
    print(item.reason, item.ref)

# 5. Reversible I/O with runtime format selection.
perfora.write(doc, "roll.perfora.json", format="native-json")
doc2 = perfora.read("roll.perfora.json")             # round-trips to an identical model

# 6. Time is derived, never stored.
seconds = doc.notes[0].duration_seconds(feed_rate_mm_per_s=180.0)
```

## Command line

```bash
# Decode one or more rolls (image and/or video) in one go.
uv run perfora --format native_json -o ./out -i scan.png play.mp4

# Re-encode an existing document.
perfora convert roll.perfora.json roll.mid --to midi --feed-rate-mm-s 180

# List available read/write formats (including third-party plugins).
perfora formats

# Guided, step-by-step decode: preview each stage, adjust, re-run, fix OCR.
perfora interactive -i scan.png -o roll.perfora.json
```

The interactive mode drives the same `Session` a future GUI uses, so corrections
made in the terminal exercise exactly the surface the GUI will build on.

## License

TBD by the project owner.
