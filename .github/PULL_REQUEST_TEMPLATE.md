<!--
Thanks for contributing to perfora. Keep the description short; the checklist is
what matters, because it encodes the project's contract (see CLAUDE.md).
-->

## What this changes

<!-- One or two sentences. Link the issue it closes, if any. -->

## Why

<!-- The problem this solves. For algorithm changes: which rolls got better, and
     how you know (numbers, not impressions). -->

## Checklist

- [ ] `uv run ruff check .` and `uv run mypy` are clean.
- [ ] `uv run pytest` passes, and new behaviour has a test — a deterministic one
      built on the synthetic roll generator (`tests/fixtures/synth.py`), not on
      a real scan.
- [ ] Spatial quantities that leave a stage are in **millimetres**, and geometry
      uses the `u` (travel) / `v` (cross) axis names, never bare x/y.
- [ ] Nothing uncertain is silently dropped — low-confidence results go to the
      review queue.
- [ ] No new dependency in the **core** install. Anything heavy (OCR, ML) is an
      optional extra, imported lazily.
- [ ] No roll-decoding logic taken from another player-piano/piano-roll project.

## Documentation (part of "done", not a follow-up)

- [ ] `README.md` reflects the change (behaviour, defaults, CLI, install).
- [ ] `Config` field `#:` comments updated, and the README config table matches
      the code exactly (same names, same defaults).
- [ ] Docstrings (NumPy style, with units) updated for changed signatures.
- [ ] `uv run sphinx-build -b html -W docs docs/_build/html` still builds.
- [ ] `CHANGELOG.md` has an entry under *Unreleased*.
- [ ] `CLAUDE.md` updated if a constraint, the stack, or the workflow changed.

## Anything reviewers should look at closely

<!-- Trade-offs you are unsure about, or a decision worth a second opinion. -->
