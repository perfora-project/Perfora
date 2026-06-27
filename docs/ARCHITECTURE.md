# perfora — Architecture

This document defines the modules, the internal data model, and the interfaces.
It is the reference Claude Code implements against. Algorithms are specified
separately in `ALGORITHMS.md`; the order of work is in `BUILD_PLAN.md`.

---

## 1. Design principles

1. **One canonical image.** Every input (flat scan, video) is normalized to a
   single `RollImage` (deskewed, cropped, calibrated). Nothing downstream of the
   source knows or cares where the data came from.
2. **Stages over a monolith.** The pipeline is an ordered list of small,
   independently testable stages that read from and write to a shared
   `PipelineContext`. Stages can be reordered, replaced, or run in isolation.
3. **Measured, not assumed.** The lane model (hole pitch and offset) is derived
   from the data. No roll-standard constants are hard-coded into the core path.
4. **Physical units in, derived units out.** The model stores millimetres along
   `u` (length) and `v` (width). Time/MIDI mapping is a derived convenience.
5. **Interfaces for the swappable parts.** Text detection, text recognition, and
   format I/O are defined as protocols/ABCs with registries, so backends and
   formats can be added without touching the core.
6. **Never silently guess.** Low-confidence results go to a review queue that a
   future UI can consume; the data model is the contract with that UI.

---

## 2. Package tree

```
perfora/
  __init__.py            # public API: ImageSource, VideoSource, process, read, write, Session, register_*
  config.py              # default thresholds/params as a frozen dataclass
  cli.py                 # batch + interactive CLI (console entry point perfora.cli:main)

  model/
    __init__.py
    geometry.py          # Axis conventions, BBox (u/v, mm), helpers
    calibration.py       # Calibration (px<->mm), DPI handling
    document.py          # RollDocument, NoteEvent, TextRegion, LaneModel, ReviewItem, Provenance, enums

  sources/
    base.py              # Source protocol, RollImage
    image_source.py      # flat scan -> RollImage (deskew, crop, calibrate)
    video_source.py      # video -> reconstructed strip -> RollImage (slit-scan)

  pipeline/
    context.py           # PipelineContext (intermediate + final results + user overrides)
    pipeline.py          # Pipeline orchestrator; default_pipeline()
    session.py           # Session: stepwise run, preview, apply_override, rerun_from, snapshot/restore
    overrides.py         # Overrides + NoteEdit/TextEdit (user corrections; serializable)
    preview.py           # StagePreview, Overlay, rasterize()
    progress.py          # ProgressReporter protocol + cooperative cancellation
    stages/
      base.py            # Stage protocol (run + preview + interaction_points)
      preprocess.py      # binarize / denoise / normalize
      holes.py           # connected-component hole extraction -> Hole list
      lanes.py           # CUSTOM: spacing auto-detection + lane assignment -> LaneModel
      notes.py           # per-lane run merging -> NoteEvent list
      text.py            # orchestrates detect -> recognize -> scope -> associate

  text/
    base.py              # TextDetector, TextRecognizer protocols; BBox, RecognitionResult
    engine.py            # TextEngine: pairs a detector + recognizer(s), routes printed vs handwriting
    detectors/
      __init__.py
      contour.py         # dependency-free fallback detector (MSER/contours via OpenCV)
      easyocr_detector.py# optional [easyocr]
      doctr_detector.py  # optional [doctr]
    recognizers/
      __init__.py
      tesseract.py       # optional [tesseract], printed
      trocr.py           # optional [trocr], handwriting
    scope.py             # classify a region as GLOBAL_* or TIMELINE by position
    associate.py         # join TIMELINE text to NoteEvents by u-span overlap

  io/
    base.py              # Reader, Writer ABCs
    registry.py          # register + discover (entry points) + runtime selection
    formats/
      __init__.py
      native_json.py     # first concrete format; lossless round-trip
      midi.py            # later; write-mostly, lossy (notes only)

  review/
    queue.py             # ReviewItem builders, thresholds, dedupe

  utils/
    imaging.py           # OpenCV helpers: page-quad detection, perspective warp, threshold
    signal.py            # autocorrelation / FFT peak finding for periodic spacing
    logging.py

tests/
  fixtures/
    synth.py             # synthetic roll generator (ground-truth images)
  ...
docs/
```

---

## 3. The internal data model (`perfora.model`)

All dataclasses are `@dataclass(slots=True)`, frozen where they are values.
Coordinates are floats in **millimetres** unless a name ends in `_px`.

### 3.1 Geometry and calibration

```python
# geometry.py
class Axis(enum.Enum):
    U = "u"   # travel / length axis (notes extend along u)
    V = "v"   # cross axis / width (pitch / lane lives along v)

@dataclass(frozen=True, slots=True)
class BBox:
    """Axis-aligned box in millimetres on the (u, v) plane."""
    u0: float; v0: float; u1: float; v1: float
    @property
    def u_span(self) -> tuple[float, float]: ...
    @property
    def v_center(self) -> float: ...
    def overlaps_u(self, u0: float, u1: float) -> bool: ...

# calibration.py
@dataclass(frozen=True, slots=True)
class Calibration:
    """Maps pixels to millimetres for the canonical RollImage."""
    mm_per_px_u: float
    mm_per_px_v: float
    dpi: float | None = None          # if derived from a known scan resolution
    source: str = "unknown"           # "dpi" | "physical_width" | "assumed"
    def px_to_mm(self, u_px: float, v_px: float) -> tuple[float, float]: ...
    def mm_to_px(self, u_mm: float, v_mm: float) -> tuple[float, float]: ...
```

Calibration is established by the **source** (Section 5). If the scan DPI is
known, use it. Otherwise, if the operator supplies the roll's physical width, the
detected roll width in pixels yields `mm_per_px_v`; `mm_per_px_u` is assumed
equal (square pixels) unless told otherwise. If neither is available, default to
`mm_per_px = 1.0` with `source="assumed"` — the geometry is then in "roll units"
but everything still round-trips.

### 3.2 Lane model (output of the custom lane-finder)

```python
@dataclass(frozen=True, slots=True)
class LaneModel:
    pitch_mm: float                 # measured spacing between adjacent lane centres
    v0_mm: float                    # v-position of lane index 0
    n_lanes: int
    confidence: float               # [0,1], how periodic/clean the model is
    method: str                     # "autocorr" | "fft" | "comb-fit"
    def v_center(self, lane: int) -> float:   # v0_mm + lane * pitch_mm
        ...
    def nearest_lane(self, v_mm: float) -> tuple[int, float]:  # (lane, residual_mm)
        ...
```

### 3.3 Notes

```python
@dataclass(frozen=True, slots=True)
class NoteEvent:
    lane: int                       # lane index from the LaneModel
    v_center_mm: float              # measured centre (LaneModel.v_center(lane) nominal)
    u_start_mm: float               # leading edge of the perforation along u
    u_end_mm: float                 # trailing edge
    confidence: float               # [0,1]
    pitch: int | None = None        # optional MIDI note number, assigned by a standard map
    @property
    def length_mm(self) -> float: ...
    def duration_seconds(self, feed_rate_mm_per_s: float) -> float:
        """Derived timing. Not stored; computed on demand."""
        return self.length_mm / feed_rate_mm_per_s
```

`pitch` is intentionally optional and *not* produced by the core path. A separate
optional mapping (lane index → MIDI note) can be applied once a standard is
guessed or supplied; keep that out of the lane-finder.

### 3.4 Text

```python
class TextScope(enum.Enum):
    GLOBAL_HEADER = "global_header"   # leading margin block (title area, etc.)
    GLOBAL_FOOTER = "global_footer"   # trailing margin block
    GLOBAL_MARGIN = "global_margin"   # side margins outside the play area
    TIMELINE      = "timeline"        # inside the play area, tied to a u-range

class TextKind(enum.Enum):
    PRINTED = "printed"
    HANDWRITTEN = "handwritten"
    UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True)
class TextRegion:
    text: str
    bbox_mm: BBox
    scope: TextScope
    kind: TextKind
    confidence: float                  # recognition confidence [0,1]
    recognized_by: str                 # backend id, e.g. "tesseract" | "trocr"
    needs_review: bool                 # confidence < threshold OR detector-only
    # For TIMELINE scope, the notes this text annotates (by index into RollDocument.notes):
    associated_note_ids: tuple[int, ...] = ()
    # Optional shallow category guess (title/composer/arranger/dynamic/annotation):
    category: str | None = None
```

### 3.5 Review queue

```python
class ReviewReason(enum.Enum):
    LOW_OCR_CONFIDENCE = "low_ocr_confidence"
    DETECTED_NOT_RECOGNIZED = "detected_not_recognized"   # box found, no backend read it
    AMBIGUOUS_LANE = "ambiguous_lane"                     # hole between two lane centres
    SHORT_OR_NOISY_NOTE = "short_or_noisy_note"
    UNCERTAIN_SCOPE = "uncertain_scope"

@dataclass(frozen=True, slots=True)
class ReviewItem:
    reason: ReviewReason
    ref_kind: str                    # "text" | "note"
    ref_id: int                      # index into the corresponding list
    confidence: float
    message: str
    suggestions: tuple[str, ...] = ()   # e.g. alternative OCR readings
```

The review queue is the **explicit hook for a future interactive UI**. The UI
walks `review_queue`, shows the referenced region (it has the bbox), lets a human
fix it, and writes back into the model. The core never blocks on review.

### 3.6 Provenance and the document root

```python
@dataclass(frozen=True, slots=True)
class Provenance:
    source_type: str                 # "image" | "video"
    source_name: str
    perfora_version: str
    created_utc: str                 # ISO-8601
    params: dict[str, float | int | str | bool]   # effective config used

@dataclass(slots=True)
class RollDocument:
    provenance: Provenance
    calibration: Calibration
    lane_model: LaneModel
    notes: list[NoteEvent]
    texts: list[TextRegion]
    review_queue: list[ReviewItem]
    standard_guess: str | None = None   # best-effort, never required
    # Optional debug layers (binary mask, density profile) excluded from serialization
    debug: dict[str, object] = field(default_factory=dict, compare=False)

    def to_dataframe(self) -> "pandas.DataFrame":
        """Notes as a tidy DataFrame for analysis (lane, v, u_start, u_end, conf, pitch)."""
```

`notes` and `texts` are plain lists; their **index is the stable id** referenced
by `ReviewItem.ref_id` and `TextRegion.associated_note_ids`. Provide
`to_dataframe()` for pandas-based analysis without forcing pandas into the hot
path.

---

## 4. Pipeline (`perfora.pipeline`)

```python
# stages/base.py
class Stage(Protocol):
    name: str
    def run(self, ctx: PipelineContext) -> None: ...                      # compute; honour ctx.overrides first
    def preview(self, ctx: PipelineContext) -> StagePreview | None: ...   # render-agnostic preview of its result
    def interaction_points(self, ctx: PipelineContext) -> list[InteractionField]: ...  # what a UI/CLI may edit

# context.py
@dataclass(slots=True)
class PipelineContext:
    image: RollImage
    config: Config
    overrides: Overrides = field(default_factory=Overrides)   # user corrections, consumed by stages
    mask: np.ndarray | None = None          # binarized holes
    holes: list[Hole] = field(default_factory=list)
    lane_model: LaneModel | None = None
    notes: list[NoteEvent] = field(default_factory=list)
    texts: list[TextRegion] = field(default_factory=list)
    review: list[ReviewItem] = field(default_factory=list)
    def to_document(self) -> RollDocument: ...
```

Each stage reads the overrides that concern it **before** computing: if the user
has seeded or forced a result (e.g. page corners, lane pitch), the stage uses it
instead of — or as a strong prior to — its own search. See §12 for how a UI or
the interactive CLI feeds those overrides between stages.

```python
# pipeline.py
class Pipeline:
    def __init__(self, stages: list[Stage]): ...
    def run(self, source: Source, config: Config | None = None) -> RollDocument:
        image = source.to_roll_image()
        ctx = PipelineContext(image=image, config=config or Config())
        for stage in self.stages:
            stage.run(ctx)
        return ctx.to_document()

def default_pipeline(text_engine: TextEngine | None = None) -> Pipeline:
    return Pipeline([
        Preprocess(), HoleExtraction(), LaneFinding(),
        NoteAssembly(), TextStage(text_engine),
    ])
```

`perfora.process(source, config=None, text_engine=None)` is a thin wrapper around
`default_pipeline(...).run(...)`. `Hole` is an internal intermediate
(`bbox_px`, `centroid_px`, `area_px`) defined in `stages/holes.py`; it never
appears in `RollDocument`.

---

## 5. Sources (`perfora.sources`)

```python
# base.py
@dataclass(slots=True)
class RollImage:
    gray: np.ndarray                 # deskewed, cropped, single-channel
    calibration: Calibration
    provenance: Provenance
    # Optional: the original colour image kept for OCR if needed
    color: np.ndarray | None = None

class Source(Protocol):
    def to_roll_image(self) -> RollImage: ...
```

- **`ImageSource(path | ndarray, *, dpi=None, physical_width_mm=None)`** —
  detect the page quadrilateral, perspective-correct it, crop, orient so `u` is
  the long axis, and build `Calibration` from `dpi`/`physical_width_mm`. See
  `ALGORITHMS.md §1`.
- **`VideoSource(path, *, roi=None, travel="auto")`** — reconstruct a single flat
  strip from the moving roll via slit-scan, then run the *same* deskew/crop as
  `ImageSource` on the result. See `ALGORITHMS.md §5`. Because piano rolls are
  highly periodic, this must **not** use feature-based panorama stitching.

Both return a `RollImage`, so the pipeline is identical from there on.

---

## 6. Text subsystem (`perfora.text`)

Detection and recognition are split because the strong offline handwriting model
(TrOCR) is recognition-only and expects a cropped line; detectors find the boxes.

```python
# base.py
@dataclass(frozen=True, slots=True)
class DetBox:
    bbox_px: tuple[int, int, int, int]      # x, y, w, h in the RollImage
    kind_hint: TextKind = TextKind.UNKNOWN

@dataclass(frozen=True, slots=True)
class RecognitionResult:
    text: str
    confidence: float

class TextDetector(Protocol):
    id: str
    def detect(self, image: RollImage) -> list[DetBox]: ...

class TextRecognizer(Protocol):
    id: str
    handles: TextKind                       # PRINTED | HANDWRITTEN | UNKNOWN(any)
    def recognize(self, crop: np.ndarray) -> RecognitionResult: ...
```

```python
# engine.py
class TextEngine:
    """Pairs one detector with one or more recognizers and routes crops."""
    def __init__(self, detector: TextDetector,
                 recognizers: list[TextRecognizer]): ...
    def run(self, image: RollImage, lane_model: LaneModel,
            notes: list[NoteEvent], config: Config
            ) -> tuple[list[TextRegion], list[ReviewItem]]:
        # detect -> for each box: crop, recognize (route by kind), convert px->mm,
        # classify scope (scope.py), associate if TIMELINE (associate.py),
        # set needs_review by confidence threshold, build review items.
```

Default offline wiring (all optional, chosen by what is installed):
`detector = ContourDetector()` (no extra deps) or `EasyOCRDetector` if
`[easyocr]`; `recognizers = [TesseractRecognizer(), TrocrRecognizer()]` if those
extras are present. If no recognizer is available, boxes are still emitted as
`TextRegion`s with empty text and `needs_review=True`
(`DETECTED_NOT_RECOGNIZED`) — detection alone is useful to a UI.

`scope.py` and `associate.py` are **our** logic (see `ALGORITHMS.md §6`), not a
library.

---

## 7. I/O layer (`perfora.io`)

```python
# base.py
class Writer(ABC):
    format_id: ClassVar[str]
    extensions: ClassVar[tuple[str, ...]]
    @abstractmethod
    def write(self, doc: RollDocument, path: str | os.PathLike) -> None: ...

class Reader(ABC):
    format_id: ClassVar[str]
    extensions: ClassVar[tuple[str, ...]]
    @abstractmethod
    def read(self, path: str | os.PathLike) -> RollDocument: ...
```

```python
# registry.py
def register_writer(w: type[Writer]) -> type[Writer]: ...   # usable as a decorator
def register_reader(r: type[Reader]) -> type[Reader]: ...
def get_writer(format_id: str) -> Writer: ...
def get_reader(format_id: str) -> Reader: ...
def available_formats() -> dict[str, dict]: ...             # id -> {read, write, extensions}

# Third-party packages register via entry points:
#   [project.entry-points."perfora.writers"]
#   my_fmt = "my_pkg.io:MyWriter"
# Discovery uses importlib.metadata.entry_points(group="perfora.writers"/"perfora.readers").
```

Top-level helpers resolve the format explicitly or by extension:

```python
perfora.write(doc, path, format="native-json")   # explicit id
perfora.write(doc, path)                          # inferred from extension
doc = perfora.read(path, format=None)             # inferred, then validated
```

**First format — `native-json`** (`formats/native_json.py`): a lossless,
human-diffable JSON encoding of `RollDocument` (schema-versioned). It is the
reference for round-trip tests: `read(write(doc)) == doc` for everything except
the non-serialized `debug` field.

**Later — `midi`** (`formats/midi.py`): write-mostly and lossy (notes only, text
dropped; timing requires a feed rate). May use `mido`/`pretty_midi` *as a MIDI
encoder only* — that is a file-format library, not a roll decoder, so it does not
violate the no-piggybacking rule. Reading MIDI back yields a partial document
with `texts=[]`.

---

## 8. Configuration (`perfora.config`)

A single frozen `Config` dataclass carries every threshold (binarization method,
min hole area in mm², lane-residual tolerance as a fraction of pitch, note
gap-bridging distance, OCR confidence cutoff, slit-scan slice width, etc.) with
sensible defaults. Stages read from `ctx.config`. No magic numbers inside stage
bodies — every tunable lives in `Config` and is recorded into
`Provenance.params`.

---

## 9. Dependency & extras strategy

```toml
[project]
dependencies = ["numpy", "scipy", "pandas", "scikit-image", "opencv-python-headless"]

[project.scripts]
perfora = "perfora.cli:main"

[project.optional-dependencies]
tesseract = ["pytesseract"]
trocr     = ["transformers", "torch", "pillow"]
easyocr   = ["easyocr"]
doctr     = ["python-doctr"]
midi      = ["mido"]
cli       = ["rich", "questionary", "pillow"]   # nicer interactive prompts + inline previews
all       = ["perfora[tesseract,trocr,easyocr,doctr,midi,cli]"]
dev       = ["pytest", "ruff", "mypy", "hypothesis"]
```

Backends import their heavy deps **inside** `__init__`/first call and raise a
clear `MissingBackendError` (with the `pip install perfora[...]` hint) if absent.
The core never imports them.

---

## 10. Error handling

- `perfora.errors` defines `PerforaError` and subclasses: `CalibrationError`,
  `LaneDetectionError` (raised only when periodicity is undetectable, not for
  routine low confidence), `MissingBackendError`, `FormatError`,
  `VideoReconstructionError`.
- Routine uncertainty is **data** (review queue), not exceptions. Exceptions are
  for genuinely unrecoverable states (unreadable file, no lanes at all).

---

## 11. Testing overview

- **Synthetic-first.** `tests/fixtures/synth.py` renders rolls from a ground-
  truth spec (lane pitch, list of notes as `(lane, u_start, u_end)`, optional
  skew, noise, text blocks). Every geometry stage is tested by recovering the
  spec from the rendered image within tolerance.
- **Stage unit tests** for preprocess/holes/lanes/notes against synth fixtures.
- **Round-trip I/O tests** for `native-json`.
- **Property-based tests** (`hypothesis`) for `signal.py` periodicity recovery
  across random pitch/offset/noise.
- **Backend tests** are marked and skipped when the extra is not installed.
- A small set of **real-scan smoke tests** (a couple of fixtures) guard against
  synthetic over-fitting but are not the primary correctness signal.

Detailed acceptance criteria per phase are in `BUILD_PLAN.md`.

---

## 12. Interactive, UI-ready execution (`perfora.pipeline.session`)

The pipeline is built so an external UI — or the interactive CLI (§13) — can drive
it one stage at a time: run a stage, **preview** it, **adjust** its inputs,
**re-run** from that point, repeat. This is not bolted on: every `Stage`
implements `preview()` and `interaction_points()`, every stage honours
`ctx.overrides`, and `Session` ties it together. The one-shot `perfora.process()`
is just `Session(source, ...).run_all()`.

### 12.1 Session — the object a UI drives

```python
class Session:
    def __init__(self, source: Source, *, config: Config | None = None,
                 overrides: Overrides | None = None,
                 progress: ProgressReporter | None = None): ...
    stages: list[Stage]
    ctx: PipelineContext
    cursor: int                                   # index of the next stage to run

    def step(self) -> StageResult: ...            # run exactly one stage
    def run_to(self, stage: str) -> None: ...     # run up to and including a named stage
    def run_all(self) -> RollDocument: ...        # run remaining stages, return the document

    def preview(self, stage: str | None = None) -> StagePreview | None: ...
    def interaction_points(self, stage: str | None = None) -> list[InteractionField]: ...

    def apply_override(self, **changes) -> None:  # record into ctx.overrides + invalidate downstream
        ...
    def invalidate_from(self, stage: str) -> None: ...   # drop results from this stage on; move cursor back
    def rerun_from(self, stage: str) -> None: ...        # invalidate_from + run_to(last stage)

    def snapshot(self) -> dict: ...                      # serializable session state (save / resume)
    @classmethod
    def restore(cls, snapshot: dict, source: Source) -> "Session": ...

@dataclass(slots=True)
class StageResult:
    stage: str
    preview: StagePreview | None
    interaction: list[InteractionField]
    new_reviews: list[ReviewItem]
```

### 12.2 Overrides — where the user "comes in"

```python
# overrides.py
@dataclass(slots=True)
class Overrides:
    # geometry / source
    page_corners_px: list[tuple[float, float]] | None = None
    orientation: str | None = None               # "auto" | "as_is" | "rot90" | ...
    binarization_mode: str | None = None         # force "bright_holes" | "dark_holes" | "adaptive"
    # lanes — skip or seed auto-detection
    lane_pitch_mm: float | None = None
    lane_v0_mm: float | None = None
    n_lanes: int | None = None
    # video
    roi_px: tuple[int, int, int, int] | None = None
    travel: str | None = None                    # "auto" | "up" | "down" | ...
    # content edits (applied after the relevant stage)
    note_edits: list[NoteEdit] = field(default_factory=list)
    text_edits: list[TextEdit] = field(default_factory=list)
    resolved_reviews: set[tuple[str, int]] = field(default_factory=set)   # (ref_kind, ref_id)
```

`NoteEdit` / `TextEdit` are small tagged records (add / remove / move a note; fix
OCR `text`, add / remove a box, reassign `scope`, set `kind`). Each stage reads
the overrides that concern it: `ImageSource` uses `page_corners_px` instead of
auto-detecting corners; `LaneFinding` treats `lane_pitch_mm` as fixed (or a strong
prior) and skips/narrows the search; `NoteAssembly` applies `note_edits`; the text
stage applies `text_edits`. Overrides live in the context, so they serialize with
the session and round-trip.

### 12.3 Previews — render-agnostic

```python
# preview.py
@dataclass(frozen=True, slots=True)
class Overlay:
    kind: str          # "quad" | "polyline" | "boxes" | "profile" | "lanes" | "spans" | "labels"
    data: object       # geometry payload (points / boxes / 1-D profile / spans)
    space: str         # "px" | "mm"
    style: dict        # colour / label / opacity hints

@dataclass(frozen=True, slots=True)
class StagePreview:
    base: str                                  # image to draw on: "color"|"gray"|"mask"|"strip"|"none"
    overlays: tuple[Overlay, ...]
    summary: dict[str, str | float | int]      # short facts for a status line
    def rasterize(self, image: RollImage) -> "np.ndarray": ...   # convenience: bake overlays (OpenCV)
```

Previews are **data**, so a web UI, a desktop UI, and the terminal consume the
same thing; `rasterize()` is an optional convenience (it uses OpenCV, already a
core dep) for quick display or writing a PNG. Per-stage examples: deskew →
page-quad overlay; holes → hole boxes; lanes → the `v`-density profile + lane
centre-lines + captured pitch; notes → note spans coloured by confidence; text →
boxes coloured by scope with the recognized string and a review flag.

### 12.4 Interaction points — what a generic UI can edit

```python
class InteractionField(TypedDict):
    key: str               # maps to an Overrides field or an edit list
    type: str              # "float"|"int"|"enum"|"bool"|"points"|"boxes"|"text"
    label: str
    current: object
    options: list | None   # for enum
    constraints: dict | None
```

A stage advertises its editable decisions so a UI builds controls without
hard-coding each stage. `LaneFinding.interaction_points()` returns e.g.
`{key:"lane_pitch_mm", type:"float", current:3.18, constraints:{min:..,max:..}}`
and a `binarization_mode` enum. The UI collects a value and calls
`session.apply_override(lane_pitch_mm=...)`.

### 12.5 Progress and cancellation

```python
# progress.py
class ProgressReporter(Protocol):
    def on_stage_start(self, stage: str, total: int | None = None) -> None: ...
    def on_progress(self, stage: str, done: int, total: int) -> None: ...
    def on_stage_end(self, stage: str, result: StageResult) -> None: ...
    def cancelled(self) -> bool: ...           # cooperative; long stages poll this
```

The long stages — video reconstruction (per frame) and OCR (per box) — report
progress and poll `cancelled()`, so a UI can show a bar and stop a run cleanly.

### 12.6 Re-run semantics

Stages are linearly ordered, so editing the output of stage *K* invalidates *K+1 …
end*. `apply_override` / `invalidate_from` reset the cursor and clear downstream
results (including the review items those stages produced); `rerun_from` then
recomputes only what changed. Fixing a lane pitch re-runs lanes → notes → text,
never the whole image decode — interactive editing stays cheap.

---

## 13. Command-line interface (`perfora.cli`)

perfora installs a console entry point. Full spec in `docs/CLI.md`; in brief:

- **Batch:** `perfora [process] -i IN [IN ...] -o OUT [--format ID] [--dpi N]
  [--physical-width-mm N] [--config FILE] [--preview-dir DIR]`. Source type
  (image vs video) is inferred per input from its extension; format ids accept
  `-`/`_` interchangeably; `-o` may be a file (single input) or a directory (one
  output per input). `process` is the implicit default, so the bare
  `perfora -i ... -o ... --format ...` form works.
- **Convert:** `perfora convert IN OUT --to FORMAT` — any registered reader →
  writer (e.g. native-json → midi).
- **List:** `perfora formats`.
- **Interactive:** `perfora interactive -i IN [-o OUT]` (or `--interactive` on
  `process`) drives a `Session` stage by stage, refreshing a preview per stage and
  prompting to accept / edit / re-run / quit, then walking the review queue. The
  basic flow uses argparse + `input()`; the `[cli]` extra (`rich`, `questionary`,
  `pillow`) upgrades prompts and inline previews, with graceful fallback when it
  is absent.
