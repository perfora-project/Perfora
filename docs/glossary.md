# Glossary

Plain-language definitions of every term perfora uses in its output, its options
and its messages. No programming knowledge assumed.

```{glossary}
roll
  A long strip of paper whose punched holes drive a player piano. It travels
  through the instrument lengthwise; a tracker bar reads across its width.

perforation
  One punched hole in the roll. Depending on the standard it may be a round hole
  or a long slot. A perforation is the *physical* thing perfora detects; a
  {term}`note` is what it means.

note
  A sounding event assembled from one or more perforations in the same
  {term}`lane`: which lane it is in, where it starts and where it ends. perfora
  merges a chain of closely-spaced perforations into one note when the gap
  between them is smaller than `bridge_gap_mm`.

lane
  One channel across the width of the roll, corresponding to one key (or one
  control function) of the instrument. Lane numbering starts at 0 and increases
  with {term}`v`, i.e. across the roll. A lane with no perforations is silent,
  but still exists in the {term}`lane model`.

lane pitch
  The centre-to-centre distance between neighbouring lanes, in millimetres. Get
  the pitch right and every note lands in the right lane, so it's the
  measurement everything else depends on. Roll standards use different pitches,
  so perfora measures it instead of assuming one.

lane model
  The measured description of the lane grid: the pitch, the position of lane 0
  (`v0_mm`), how many lanes there are, how the grid was found (`method`), and a
  {term}`confidence`. Everything downstream depends on it.

u
  The **travel axis**: the direction the roll moves through the player, i.e.
  along its length. Notes extend along `u`. Positions are `u_start_mm` and
  `u_end_mm`, measured from the start of the roll.

v
  The **cross axis**: across the roll's width, where lanes live. A note's
  position across the roll is `v_center_mm`. Lane index increases with `v`.

  perfora never uses bare "x" and "y", because which one is which depends on how
  the scan happens to be oriented. `u` and `v` are defined by the roll itself.

calibration
  The relationship between pixels in your scan and real millimetres. perfora
  needs it to report physical measurements, and takes it from `--dpi` (your
  scanner's resolution) or from `--physical-width-mm` (the roll's measured
  width). Given neither, it still works, but the millimetre scale is arbitrary
  (1 mm = 1 px) — relative spacing and timing remain correct.

dpi
  Dots per inch: the resolution a scan was made at. 600 dpi means 600 pixels per
  inch of roll. Higher resolution separates perforations that sit close together.

deskew
  Straightening a scan that was placed slightly crooked, so that the roll's long
  edge lines up with the {term}`u` axis. perfora finds the roll against its
  background, straightens it, and crops to it, before anything else happens.

binarization
  Reducing the image to two values — "this is a perforation" and "this is not" —
  as the first step of detection. `binarization_mode` controls whether
  perforations appear bright (a scanner bed showing through) or dark (a dark
  backing behind the roll); `auto` decides for itself.

confidence
  A number from 0 to 1 saying how sure perfora is about a result. Anything below
  a stage's threshold is not discarded — it is added to the {term}`review queue`.

review queue
  The list of results perfora was unsure about, each with a reason
  (`ambiguous_lane`, `short_or_noisy_note`, `low_ocr_confidence`, …) and a
  pointer to the note or text it concerns. Nothing uncertain is dropped
  silently. An empty queue means perfora was confident about everything it
  produced.

scope
  What a piece of text on the roll refers to. `global_header` and
  `global_footer` are the title/label blocks at the roll's ends;
  `global_margin` is writing in the side margins; `timeline` text sits beside
  the music and is linked to the exact notes it spans (a handwritten "louder"
  attaches to that passage).

OCR
  Optical character recognition — reading text in an image. In perfora it is
  optional and pluggable: with no extra installed, text regions are still
  *found* and recorded, just not read.

stage
  One step of the pipeline: `preprocess` → `holes` → `lanes` → `notes` →
  `text`. Each stage can be previewed as a picture and re-run on its own, which
  is how you find out *where* a bad result came from.

preview
  A rendered picture of what a stage decided, saved by `--preview-dir` (or shown
  inline in the notebook). The `lanes` preview is the one to check first: if its
  vertical lines sit on the columns of holes, the rest will be right.

feed rate
  How fast the roll was meant to travel through the instrument, in millimetres
  per second. perfora stores positions in millimetres and does **not** store
  time, because the same roll played at a different feed rate is a different
  performance. Supply a feed rate to convert:
  `note.duration_seconds(feed_rate_mm_per_s=180.0)`.

document (`.perfora.json`)
  The output file: the lane model, the notes, the text regions, the review
  queue, the calibration, and a record of how the file was made. It is plain
  text, and lossless — reading it back gives exactly the same data. See
  [Output format](output.md).

ground truth
  What is actually true, as opposed to what a program inferred. perfora's tests
  use *synthetic* rolls rendered from a specification, so the ground truth is
  known exactly and results can be checked against it. The bundled sample roll
  works the same way.
```
