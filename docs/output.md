# Output format

perfora writes a `.perfora.json` file. It's plain text you can open in any
editor, and it's lossless: reading it back gives exactly the same data, which is
what makes it safe to archive. This page goes through a real file field by field.

Every spatial number is in millimetres and every confidence is a number from 0 to
1. No time values are stored anywhere, see
[Why there are no seconds](#why-there-are-no-seconds).

## The shape of the file

Three keys at the top level; everything of interest lives under `document`.

```json
{
  "format": "native-json",
  "schema_version": 1,
  "document": {
    "provenance": { "...": "how this file was made" },
    "calibration": { "...": "how pixels map to millimetres" },
    "lane_model": { "...": "the measured lane grid" },
    "notes": [ "..." ],
    "texts": [ "..." ],
    "review_queue": [ "..." ],
    "standard_guess": null
  }
}
```

`format` and `schema_version` are there so a future reader can recognise an older
file and still load it correctly.

## `calibration` — pixels to millimetres

```json
"calibration": {
  "mm_per_px_u": 0.08466666666666667,
  "mm_per_px_v": 0.08466666666666667,
  "dpi": 300.0,
  "source": "dpi"
}
```

| Field | Meaning |
|---|---|
| `mm_per_px_u`, `mm_per_px_v` | How many millimetres one pixel covers, along the roll and across it. |
| `dpi` | The scan resolution this was derived from, when known. |
| `source` | Where the scale came from: `"dpi"`, `"physical_width"`, or `"assumed"`. |

Watch for `"source": "assumed"`. It means you gave neither `--dpi` nor
`--physical-width-mm`, so 1 mm was taken to equal 1 px. Relative spacing and
proportions are still correct; the absolute millimetre scale isn't.

## `lane_model` — the measured grid

```json
"lane_model": {
  "pitch_mm": 2.997395384615384,
  "v0_mm": 6.042855384615385,
  "n_lanes": 25,
  "confidence": 0.9965689573307395,
  "method": "comb-fit"
}
```

| Field | Meaning |
|---|---|
| `pitch_mm` | Centre-to-centre distance between neighbouring lanes. Everything downstream depends on this one. |
| `v0_mm` | Where lane 0 sits across the roll. |
| `n_lanes` | How many lanes the grid has (silent lanes included). |
| `confidence` | How well the grid fits the holes that were found. |
| `method` | How it was obtained: `comb-fit` (measured from the holes) or `fixed-count` (you supplied `--lanes N`, treated as ground truth). |

This roll was measured at 2.9974 mm and was generated at exactly 3.0 mm. A pitch
that comes out exactly double or half what you expect is the classic failure
mode; fix it by passing the true lane count with `--lanes N`.

## `notes` — one entry per note

```json
{
  "lane": 0,
  "v_center_mm": 6.042855384615385,
  "u_start_mm": 30.05666666666667,
  "u_end_mm": 36.068,
  "confidence": 0.9825456515978961,
  "pitch": null
}
```

| Field | Meaning |
|---|---|
| `lane` | Which lane, counting from 0 across the roll. |
| `v_center_mm` | Position **across** the roll. |
| `u_start_mm`, `u_end_mm` | Where the note begins and ends **along** the roll, measured from the start. |
| `confidence` | How sure perfora is about this note. |
| `pitch` | MIDI note number, when a lane→pitch mapping is known. `null` today — mapping lanes to pitches is on the roadmap, and depends on the roll standard. |

The note's length is `u_end_mm - u_start_mm` (the Python model exposes it as
`note.length_mm`). Notes aren't guaranteed to be sorted, so sort by `u_start_mm`
if order matters to you.

Careful with the word *pitch*: `lane_model.pitch_mm` is a distance (lane
spacing), `notes[].pitch` is a musical pitch. They're unrelated.

## `texts` — labels and annotations

```json
{
  "text": "Frühlingsrauschen",
  "bbox_mm": { "u0": 4.1, "v0": 12.0, "u1": 22.6, "v1": 61.3 },
  "scope": "global_header",
  "kind": "printed",
  "confidence": 0.91,
  "recognized_by": "tesseract",
  "needs_review": false,
  "associated_note_ids": [],
  "category": "title"
}
```

| Field | Meaning |
|---|---|
| `text` | What was read. **Empty** when the region was found but not read (no OCR backend installed, or none could read it). |
| `bbox_mm` | The region's box in millimetres: `u0`/`u1` along the roll, `v0`/`v1` across it. |
| `scope` | What the text refers to: `global_header`, `global_footer`, `global_margin`, or `timeline`. |
| `kind` | `printed`, `handwritten`, or `unknown`. |
| `confidence` | Recognition confidence. |
| `recognized_by` | Which backend read it (`""` when only detected). |
| `needs_review` | `true` when it was not read, or read with low confidence. |
| `associated_note_ids` | For `timeline` text: indices into `notes` of the notes this text sits beside. This is how a handwritten "louder" is tied to the passage it marks. |
| `category` | A shallow guess: `title`, `composer`, `arranger`, `dynamic`, `annotation`, or absent. |

An empty `texts` list means no text regions were detected: either a plain roll,
or a scan whose contrast is too low for detection.

## `review_queue` — what perfora was unsure about

```json
{
  "reason": "ambiguous_lane",
  "ref_kind": "note",
  "ref_id": 41,
  "confidence": 0.42,
  "message": "hole centre sits 0.9 mm from the nearest lane centre",
  "suggestions": []
}
```

| Field | Meaning |
|---|---|
| `reason` | Why it was queued (see the table below). |
| `ref_kind` | `"note"` or `"text"` — which list `ref_id` points into. |
| `ref_id` | Index into `notes` or `texts`. |
| `confidence` | The confidence that triggered the flag. |
| `message` | A human-readable explanation. |
| `suggestions` | Alternatives, e.g. other possible OCR readings. |

| `reason` | What it means |
|---|---|
| `ambiguous_lane` | A perforation sits between two lane centres. Usually a sign the lane pitch or the grid position is slightly off. |
| `short_or_noisy_note` | A note shorter than `min_note_len_mm`, or with low confidence. Often dirt, a pinhole, or a tear. |
| `low_ocr_confidence` | Text was read, but the backend was not confident. |
| `detected_not_recognized` | A text region was found and no backend read it (typically no OCR extra installed). |
| `uncertain_scope` | Text could not be confidently assigned to a scope. |

An empty queue means perfora was confident about everything it produced. A long
queue isn't a failure, it's the list of things a human should look at. Use
`--review fail` in a batch script to exit non-zero when the queue isn't empty, so
rolls that need attention don't slip past.

## `provenance` — how the file was made

Records the source type and name, the perfora version, the creation timestamp,
and every configuration value in force during the run (`params`). That last part
is what makes a result reproducible: the file states the thresholds that produced
it, so the run can be repeated years later.

```json
"provenance": {
  "source_type": "image",
  "source_name": "sample_roll.png",
  "perfora_version": "0.1.0",
  "created_utc": "2026-07-25T14:19:13.245325+00:00",
  "params": { "binarization_mode": "auto", "bridge_gap_mm": 0.5, "...": "..." }
}
```

## `standard_guess`

A guess at which roll standard this is, or `null`. Nothing in perfora relies on
it — the lane model is measured — so it's informational only.

## Why there are no seconds

The same roll played at a different feed rate is a different performance, so
storing time in the file would bake one interpretation into the archive. perfora
stores millimetres and lets you derive time when you need it:

```python
seconds = note.duration_seconds(feed_rate_mm_per_s=180.0)
start_s = note.u_start_mm / 180.0
```

Same reasoning for MIDI note numbers: mapping lane → pitch depends on the roll
standard and belongs to the consumer, not to the archive file.

## Reading it without perfora

It's ordinary JSON, so any tool can read it:

```python
import json

with open("my_roll.perfora.json") as fh:
    doc = json.load(fh)["document"]

for note in doc["notes"]:
    print(note["lane"], note["u_start_mm"], note["u_end_mm"])
```

With perfora installed you get the typed model instead, plus a tidy table:

```python
import perfora

doc = perfora.read("my_roll.perfora.json")
df = doc.to_dataframe()          # lane, v_center_mm, u_start_mm, u_end_mm, ...
df.to_csv("notes.csv", index=False)
```
