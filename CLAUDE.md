# CLAUDE.md

The project contract lives in [`AGENTS.md`](AGENTS.md) — hard constraints, tech
stack, conventions, the branch/PR workflow, what counts as "done" for
documentation, and how human-facing docs should be written. **Read it before
changing anything.** It is tool-agnostic on purpose; everything in it applies to
Claude Code too.

Only Claude Code-specific notes belong in this file.

## Claude Code specifics

- Claude-only configuration (permissions, hooks, local settings) goes in
  `.claude/`, not here and not in `AGENTS.md`.
- Nothing in this repo requires an MCP server, a custom skill, or a subagent.
  Plain file edits plus `uv run ...` cover the whole workflow.
- Before pushing, run the same four checks CI runs:

  ```bash
  uv run ruff check .
  uv run mypy
  uv run pytest
  uv run sphinx-build -b html -W docs docs/_build/html
  ```

  Don't run `ruff format` — the project lints but doesn't enforce formatting, and
  a wholesale reformat buries the actual change.
- `main` is protected by a local `pre-push` hook, not by GitHub. Branch first
  (`feat/…`, `fix/…`, `docs/…`, …) and open a PR; a direct push to `main` is a
  mistake even when it works.
