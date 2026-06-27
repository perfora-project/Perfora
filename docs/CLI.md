# perfora — Command-Line Interface

`perfora` installs a console entry point (`[project.scripts] perfora =
"perfora.cli:main"`), so after `pip install perfora` (or `uv run`) the command is
available. The basic CLI is **argparse-only** and needs no extra dependencies; the
`[cli]` extra (`rich`, `questionary`, `pillow`) only upgrades the interactive
experience, with graceful fallback to plain prompts when absent.

The CLI is a thin shell over the public API and the `Session` (Architecture §12).
It contains no roll logic of its own.

---

## 1. Synopsis

```
perfora [process] -i IN [IN ...] -o OUT [options]   # decode one or more rolls
perfora convert IN OUT --to FORMAT [options]        # re-encode an existing document
perfora formats                                     # list available read/write formats
perfora interactive -i IN [-o OUT] [options]        # guided, step-by-step decode
```

`process` is the **implicit default** subcommand, so the bare form works:

```
uv run perfora --format native_json -o /path/to/output -i /path/to/in1.png /path/to/in2.mp4
```

This decodes `in1.png` (image) and `in2.mp4` (video) and writes one
`native-json` document per input into `/path/to/output`.

---

## 2. `process` (default)

Decode each input into a `RollDocument` and write it in the chosen format.

**Inputs (`-i/--input`)** — one or more paths. Each input's **source type is
inferred from its extension**: image extensions (`.png .jpg .jpeg .tif .tiff
.bmp .webp`) → `ImageSource`; video extensions (`.mp4 .mov .avi .mkv .m4v
.webm`) → `VideoSource`. `--source-type {auto,image,video}` overrides inference
when an extension is unusual.

**Output (`-o/--output`)** — semantics depend on input count:
- one input + `-o FILE` → write that file;
- one input + `-o DIR/` (existing dir or trailing slash) → write
  `DIR/<input-stem>.<ext>`;
- many inputs → `-o` **must be a directory**; each input → `DIR/<stem>.<ext>`.

The output extension comes from the chosen format's first registered extension
(e.g. `native-json` → `.perfora.json`). If a target file already exists, fail
unless `--force`.

**Format (`--format ID`)** — a registered writer id; default `native-json`. Ids
accept `-` and `_` interchangeably (`native_json` == `native-json`).

**Calibration** — `--dpi N` (preferred when the scan DPI is known) or
`--physical-width-mm N` (the roll's true width; combined with the detected width
in pixels). If neither is given, geometry is in assumed units (still round-trips);
the CLI prints a one-line notice.

**Other options**
- `--config FILE` — JSON/TOML of `Config` overrides (thresholds).
- `--preview-dir DIR` — also write a rasterized preview PNG per stage per input
  (useful for eyeballing a batch result without the GUI).
- `--roi X,Y,W,H` / `--travel {auto,up,down}` — video hints (forwarded as overrides).
- `-v/-vv` — progress to stderr (a bar via `[cli]` if installed, else plain
  lines); `--quiet` suppresses it.
- `--review {warn,fail,ignore}` — exit behaviour when the review queue is
  non-empty (default `warn`).

**Exit codes:** `0` success; `2` usage error; `3` no lanes detected / unreadable
input; `4` review queue non-empty **and** `--review fail`.

---

## 3. `convert`

Re-encode an existing document between formats using the registry — no images
involved.

```
perfora convert roll.perfora.json roll.mid --to midi --feed-rate-mm-s 180
```

The reader is resolved from the input extension (or `--from ID`); the writer from
`--to ID`. Lossy conversions warn (e.g. `native-json → midi` drops text and needs
a feed rate to realize timing). `--feed-rate-mm-s` supplies the
length-millimetres → seconds mapping for time-based targets; it is never stored in
the model.

---

## 4. `formats`

```
perfora formats
```

Prints the registry (`available_formats()`): each id, whether it can read and/or
write, and its extensions — including formats contributed by third-party packages
via entry points.

---

## 5. `interactive` — guided decode

`perfora interactive -i IN [-o OUT]` (equivalently `perfora process ...
--interactive`) drives a `Session` one stage at a time in the terminal. It is the
text-mode counterpart of the future GUI and uses the **same** `Session`,
`StagePreview`, `Overrides`, and review queue — so anything learned here transfers
directly to the GUI.

### 5.1 Per-stage loop

For each stage in order (deskew/source → preprocess → holes → lanes → notes →
text):

1. **Run** the stage (`session.step()`), showing a progress bar for long stages
   (video, OCR) that can be cancelled with `Ctrl-C` without losing prior stages.
2. **Summarize** `StageResult.preview.summary` as a status line, e.g.
   `lanes: pitch=3.18 mm · 88 lanes · confidence 0.94`.
3. **Show a preview.** With the `[cli]` extra, render inline (rich/PIL); otherwise
   write `rasterize()` output to `--preview-dir` (or a temp file) and print the
   path for the user to open. A compact Unicode sparkline of the `v`-density
   profile is shown for the lanes stage even in plain mode.
4. **List interaction points** (`session.interaction_points()`) and prompt:

   ```
   [Enter] accept & continue   e edit   r re-run this stage   p reopen preview   q quit
   ```

   - **edit** walks the stage's `InteractionField`s. Scalars/enums are prompted
     directly (e.g. type a new `lane_pitch_mm`, pick a `binarization_mode`).
     Box/text edits iterate items (see 5.2). Each answer becomes
     `session.apply_override(key=value)`, which invalidates downstream results.
   - **re-run** calls `session.rerun_from(stage)` so only the affected stages
     recompute (Architecture §12.6).

### 5.2 Editing detected content in the terminal

Spatial edits that need dragging are deferred to the GUI, but the common
corrections work in text:

- **Text/OCR:** for each flagged `TextRegion` (or all, with `--review all`), show
  the crop preview, the recognized string, the scope, and confidence, then prompt:
  keep / retype text / change scope / mark not-text(remove) / add-missed-box (enter
  a bbox or pick from detector candidates). Edits become `TextEdit` overrides.
- **Lanes:** accept the measured pitch, type a corrected pitch, or nudge `v0`.
- **Notes:** for `SHORT_OR_NOISY_NOTE` items, keep / delete / adjust `u` endpoints.

### 5.3 Review-queue pass

After the last stage, the loop walks `doc.review_queue` (most-uncertain first),
presenting each item with its preview and `suggestions`, and recording the
resolution into `resolved_reviews` / the relevant edit list. The pass is skippable
(`--no-review-pass`).

### 5.4 Save / resume

`--save-session FILE` writes `session.snapshot()` (JSON) at any quit point;
`perfora interactive --resume FILE -i IN` restores it (`Session.restore`) so a long
correction job can be paused and continued. On completion the final document is
written to `-o OUT` exactly as `process` would.

---

## 6. Implementation notes

- Keep all roll logic in the library; `cli.py` only parses args, constructs the
  source/`Session`, renders previews, and maps prompts to `apply_override`.
- A `TerminalProgressReporter` (and a `NullProgressReporter`) implement the
  `ProgressReporter` protocol from Architecture §12.5.
- Detect the `[cli]` extra lazily; if absent, fall back to `input()` and
  file-based previews. Never make `rich`/`questionary` import-time requirements.
- Everything the interactive CLI does is expressible through the public `Session`
  API — that is the contract the GUI will reuse, so do not add private hooks the
  CLI alone can call.
