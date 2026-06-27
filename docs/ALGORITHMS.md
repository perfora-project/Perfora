# perfora — Algorithms

These are the original algorithms perfora must implement. They use only generic
numpy / scipy / scikit-image / OpenCV primitives. **No piano-roll-specific
library is permitted for any of this logic.** Pseudocode is illustrative; match
the behaviour, not the exact lines. Every numeric threshold named here lives in
`Config` (Architecture §8), not inline.

Axis convention throughout: **`u`** = travel/length axis (notes extend along
`u`); **`v`** = cross/width axis (lanes are spaced along `v`). After the source
stage, the image is oriented so `u` is the vertical (row) axis and `v` is the
horizontal (column) axis — pick one and keep it consistent; the rest of this doc
assumes **rows = u, columns = v**.

---

## 1. Deskew, crop, orient, calibrate (ImageSource)

Goal: from a raw scan that may be rotated, skewed, and surrounded by background,
produce a tight, axis-aligned `RollImage` plus a `Calibration`.

```
function deskew_and_crop(raw_bgr, dpi, physical_width_mm):
    gray = to_gray(raw_bgr)
    # 1. Separate roll paper from background.
    #    Roll paper is a large, brighter, fairly uniform region.
    blur  = gaussian(gray, sigma≈2)
    edges = canny(blur, low, high)                 # or adaptive-threshold + close
    closed = morphological_close(edges, kernel)    # join the border into a loop

    # 2. Find the page quadrilateral = largest 4-corner contour by area.
    contours = find_contours(closed)
    quad = None
    for c in sort_by_area_desc(contours):
        approx = approx_poly_dp(c, eps=0.02*perimeter(c))
        if len(approx) == 4 and area(approx) > min_page_area_frac * image_area:
            quad = order_corners(approx)           # TL, TR, BR, BL
            break
    if quad is None:
        # Fallback: minAreaRect of the largest contour (handles rounded corners).
        quad = box_points(min_area_rect(largest_contour))

    # 3. Perspective-correct to a rectangle.
    w, h = estimate_rect_size(quad)                # from corner distances
    dst  = [[0,0],[w,0],[w,h],[0,h]]
    M    = get_perspective_transform(quad, dst)
    flat = warp_perspective(raw_bgr, M, (w, h))

    # 4. Orient so u is the long axis (rolls are long).
    if w > h: flat = rotate_90(flat)               # make rows=u the longer side
    gray_flat = to_gray(flat)

    # 5. Calibration.
    if dpi is not None:
        mm_per_px = 25.4 / dpi
        cal = Calibration(mm_per_px, mm_per_px, dpi, source="dpi")
    elif physical_width_mm is not None:
        mm_per_px_v = physical_width_mm / flat.width_px
        cal = Calibration(mm_per_px_v, mm_per_px_v, None, source="physical_width")
    else:
        cal = Calibration(1.0, 1.0, None, source="assumed")

    return RollImage(gray_flat, cal, provenance), color=flat
```

Notes:
- `order_corners` sorts the four points into a canonical TL/TR/BR/BL ordering
  (sum/diff-of-coordinates trick) so the warp is stable.
- Skew that is *not* a clean perspective (paper curl, slight barrelling) is left
  to the lane-finder's windowed estimation (§4), which tolerates gentle drift.

---

## 2. Preprocess / binarize (stage: preprocess)

Produce a clean binary `mask` where **True = perforation**.

Two illumination regimes exist and must both work:
- **Backlit / transmissive scans:** holes are *bright* (light passes through).
- **Reflective scans:** holes are *dark* (shadow / show-through of dark backing).

```
function binarize(gray, mode="auto"):
    if mode == "auto":
        mode = "bright_holes" if median(border_region) < median(center_region)
                              else "dark_holes"
    if mode == "bright_holes":
        thr = threshold_otsu(gray); mask = gray > thr
    else:
        thr = threshold_otsu(gray); mask = gray < thr
    mask = remove_small_objects(mask, min_area_px)         # speckle
    mask = binary_opening(mask, small_kernel)              # detach touching holes
    return mask
```

Adaptive thresholding (`threshold_sauvola`/local Otsu) is the fallback when the
scan has uneven lighting. Expose the choice via `Config`.

---

## 3. Hole extraction (stage: holes)

```
function extract_holes(mask, calibration, config):
    labels = label(mask)                                   # skimage.measure.label
    holes = []
    for r in regionprops(labels):
        area_mm2 = r.area * cal.mm_per_px_u * cal.mm_per_px_v
        if area_mm2 < config.min_hole_area_mm2: continue   # noise
        if area_mm2 > config.max_hole_area_mm2: continue   # tears / margins
        # Aspect / solidity gates reject torn edges and text strokes:
        if r.solidity < config.min_solidity: continue
        holes.append(Hole(bbox_px=r.bbox, centroid_px=r.centroid, area_px=r.area))
    return holes
```

Hole centroids feed the lane-finder; hole bounding boxes (in `u`) feed note
assembly. Keep everything in pixels here; convert to mm only when leaving the
geometry stages.

---

## 4. Lane-finding: spacing auto-detection + assignment (stage: lanes) — CORE

This is the heart of perfora. We do **not** assume a roll standard; we measure
the lane pitch from the holes themselves.

### 4.1 Cross-axis density profile

Project hole presence onto the `v` (column) axis to expose the periodic lane
structure. Use centroids (robust to hole length) rather than raw pixels.

```
function v_density(holes, n_cols, config):
    d = zeros(n_cols)
    for h in holes:
        v = round(h.centroid_px.col)
        d[v] += 1                              # or += weight by hole u-length
    d = gaussian_smooth(d, sigma = config.density_sigma_px)
    return d                                   # 1-D signal with peaks at lane centres
```

### 4.2 Estimate the pitch (period of the comb)

Recover the fundamental spacing with two independent methods and cross-check.

```
function estimate_pitch(d, config):
    # (a) Autocorrelation: first strong peak at non-zero lag = pitch.
    ac = autocorrelate(d - mean(d))            # scipy.signal.correlate, 'full', take >=0 lags
    ac[0:config.min_pitch_px] = -inf           # ignore trivial small lags
    lag_ac = argmax_local(ac[:config.max_pitch_px])

    # (b) FFT: dominant non-DC frequency -> period.
    P = abs(rfft(d - mean(d)))**2
    P[0:config.min_freq_bin] = 0
    k = argmax(P)
    lag_fft = len(d) / k

    # Agreement check; if they disagree badly, lower confidence / try comb-fit.
    if relative_diff(lag_ac, lag_fft) < config.pitch_agree_tol:
        pitch = mean(lag_ac, lag_fft); conf = high
    else:
        pitch, conf = refine_by_comb_fit(d, [lag_ac, lag_fft])   # §4.3
    return pitch, conf
```

### 4.3 Phase / offset and a refined comb fit

Given a pitch, find the offset `v0` that best aligns a comb (regular grid of
positions) to the density peaks, then refine pitch+offset jointly.

```
function comb_fit(d, pitch0):
    best = None
    for phase in range(0, round(pitch0)):                 # try all offsets within one period
        centres = arange(phase, len(d), pitch0)
        score   = sum(d[round(c)] for c in centres)       # energy captured at comb teeth
        best = keep_max(best, (score, phase))
    v0 = best.phase
    # Local refinement of (pitch, v0) by maximizing captured energy (e.g. Nelder-Mead
    # over a small window), or by fitting peak positions with linear regression:
    peaks = detect_peaks(d, min_distance≈0.6*pitch0)
    idx   = round((peaks - v0) / pitch0)                  # nominal lane index per peak
    pitch, v0 = linregress(idx -> peaks).slope, .intercept   # peaks ≈ v0 + idx*pitch
    return pitch, v0
```

The linear regression of *measured peak position* against *nominal lane index* is
the key trick: it yields a sub-pixel pitch and offset and naturally averages out
per-lane jitter. `n_lanes` = number of comb teeth spanning the play area.

### 4.4 Robustness to skew / stretch (windowed consensus)

A single global profile blurs if the roll drifts along its length. Compute the
profile and pitch in several overlapping windows along `u`, then reconcile:

```
function lane_model(holes, n_cols, n_rows, config):
    windows = split_u_into_overlapping_bands(n_rows, k=config.n_windows)
    estimates = [estimate_pitch_and_offset(holes in w) for w in windows]
    pitch  = robust_mean(e.pitch for e in estimates)      # median / trimmed mean
    # Allow v0 to vary linearly with u (captures gentle skew): fit v0(u).
    v0_of_u = linregress(window_centre_u -> e.v0)
    conf = consistency_score(estimates)                   # low variance -> high conf
    return LaneModel(pitch, v0_at_u0, n_lanes, conf, method)
```

If `v0` drift across windows exceeds a fraction of pitch, store the linear
`v0(u)` correction so assignment (§4.5) uses the right lane centres at each `u`.

### 4.5 Assign holes to lanes

```
function assign(holes, lane_model, config):
    for h in holes:
        v_mm = to_mm_v(h.centroid_px.col)
        lane, residual = lane_model.nearest_lane(v_mm, at_u=to_mm_u(h.centroid_px.row))
        if abs(residual) <= config.lane_tol_frac * lane_model.pitch_mm:
            h.lane = lane
        else:
            h.lane = lane                                  # tentative
            review.add(AMBIGUOUS_LANE, ref=h, conf=1 - residual/(0.5*pitch))
```

Holes landing between two lane centres (residual near half a pitch) are assigned
to the nearest but flagged for review. This is exactly the "uncertain box"
behaviour, applied to holes.

---

## 5. Note assembly (stage: notes)

Within each lane, perforations are runs along `u`. A single sustained note is one
run; chain-perforated rolls (a sustained note rendered as a dotted column of
holes) need small gaps bridged.

```
function assemble_notes(holes_by_lane, lane_model, calibration, config):
    notes = []
    for lane, hs in holes_by_lane.items():
        hs = sort_by_u(hs)
        runs = []
        cur  = None
        for h in hs:
            u0, u1 = to_mm_u(h.bbox.row_min), to_mm_u(h.bbox.row_max)
            if cur is None:
                cur = [u0, u1]
            elif u0 - cur[1] <= config.bridge_gap_mm:      # bridge small gaps
                cur[1] = max(cur[1], u1)
            else:
                runs.append(cur); cur = [u0, u1]
        if cur: runs.append(cur)
        for (u_start, u_end) in runs:
            conf = note_confidence(u_start, u_end, lane_model, holes)
            note = NoteEvent(lane, lane_model.v_center(lane), u_start, u_end, conf)
            notes.append(note)
            if note.length_mm < config.min_note_len_mm or conf < config.note_conf_min:
                review.add(SHORT_OR_NOISY_NOTE, ref=note, conf=conf)
    return notes
```

`bridge_gap_mm` defaults to a small fraction of pitch; expose it because chain
perforation spacing varies. Note confidence combines: edge sharpness of the run
endpoints, how cleanly the holes sat on the lane centre, and run-length
plausibility.

Lane → MIDI pitch mapping is **out of scope here**. If a standard is later
guessed/supplied, a separate optional pass fills `NoteEvent.pitch`.

---

## 6. Slit-scan video reconstruction (VideoSource) — CORE

Reconstruct one flat strip from a video of the roll moving past the camera.
Because rolls are highly periodic, feature-based panorama stitching (SIFT/ORB +
homography, `cv2.Stitcher`) mis-matches repeated holes and ghosts — **do not use
it**. Instead measure inter-frame translation and append thin slices (a
push-broom / slit-scan reconstruction).

```
function reconstruct(video, config):
    frames = iter_frames(video)
    ref = to_gray(first usable frame within roi)
    strip_rows = []                                  # accumulated slices (lists of pixels)
    accumulated_shift = 0.0
    prev = ref
    for frame in frames:
        g = to_gray(crop(frame, roi))
        # 1. Estimate translation between consecutive frames.
        (dv, du), response = phase_correlate(prev, g)    # cv2.phaseCorrelate (sub-pixel)
        #   du is the travel-direction shift; dv should be ~0 (lateral drift).
        if response < config.min_corr_response:
            (du, dv) = optical_flow_translation(prev, g)  # Farneback fallback
        accumulated_shift += du
        # 2. Emit slices for each new row of travel revealed since last frame.
        while accumulated_shift >= 1.0:
            row = sample_center_line(g, offset)           # one (or few) pixel row(s)
            strip_rows.append(correct_lateral(row, dv))   # compensate small dv
            accumulated_shift -= 1.0
        prev = g
    strip = stack(strip_rows)                             # H x W reconstructed image
    return strip
```

Details and safeguards:
- **Constant-ish speed not required:** the accumulator emits slices proportional
  to measured travel, so variable feed speed is handled — slow frames emit fewer
  rows, fast frames more.
- **Direction auto-detect (`travel="auto"`):** infer the sign/axis of motion from
  the dominant `phaseCorrelate` shift over the first N frames.
- **Lateral drift (`dv`):** small side-to-side wobble is corrected per slice;
  large `dv` lowers confidence and is logged.
- **Output:** the reconstructed `strip` is handed to the **same** deskew/crop
  (§1) and then the identical hole/lane/note path. Calibration along `u` comes
  from "1 slice = 1 px"; along `v` from the frame's `roi` width and any supplied
  `physical_width_mm`.
- Raise `VideoReconstructionError` only if correlation collapses for a sustained
  stretch (e.g. occlusion); otherwise degrade and flag.

---

## 7. Text scope classification + timeline association

### 7.1 Scope (scope.py)

Each detected box (converted to mm) is classified by **where** it sits relative
to the play area. The play area is the `v`-band spanned by the lane model;
margins are outside it; header/footer are the leading/trailing `u`-bands.

```
function classify_scope(bbox_mm, lane_model, roll_len_mm, config):
    in_play_v = lane_model.v_min - m <= bbox.v_center <= lane_model.v_max + m
    if not in_play_v:
        return GLOBAL_MARGIN
    if bbox.u1 < config.header_frac * roll_len_mm:  return GLOBAL_HEADER
    if bbox.u0 > (1 - config.footer_frac) * roll_len_mm: return GLOBAL_FOOTER
    return TIMELINE
```

Boxes near a band boundary get `UNCERTAIN_SCOPE` review items.

### 7.2 Association (associate.py)

A `TIMELINE` box annotates the notes it spans along `u`.

```
function associate(text_region, notes, config):
    u0, u1 = text_region.bbox_mm.u_span
    pad = config.assoc_pad_mm                         # small tolerance
    hits = [i for i,n in enumerate(notes)
            if n.u_end_mm >= u0 - pad and n.u_start_mm <= u1 + pad]
    if config.assoc_lane_aware:                       # optional: bias to nearby lanes
        hits = filter_by_v_proximity(hits, text_region.bbox_mm.v_center, notes)
    text_region.associated_note_ids = tuple(hits)
    return text_region
```

So a handwritten "louder" sitting beside a passage attaches to exactly the notes
in that `u`-range — answering "which notes were meant to be played louder".
Optional `category` tagging (e.g. recognizing dynamic words) is a thin lookup on
top, never required for association.

---

## 8. Confidence & review rules (review/queue.py)

A single place builds `ReviewItem`s so thresholds stay consistent:

- **Text:** `confidence < config.ocr_conf_min` → `LOW_OCR_CONFIDENCE`; a box with
  no recognizer output → `DETECTED_NOT_RECOGNIZED`; handwriting almost always
  lands here more than print — that is expected and is the point of the queue.
- **Lanes:** residual > half-tolerance → `AMBIGUOUS_LANE`.
- **Notes:** below min length or low endpoint sharpness → `SHORT_OR_NOISY_NOTE`.
- **Scope:** box within `config.scope_edge_mm` of a band boundary →
  `UNCERTAIN_SCOPE`.

De-duplicate by `(reason, ref_kind, ref_id)`. Items carry the bbox-bearing
reference so a future UI can render and fix them directly. The pipeline never
blocks; review is always *data*.
