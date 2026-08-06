# AGENTS.md

## Toolchain

One command gets you to a state where every gate runs:

```sh
uv sync
```

That installs the `dev` dependency group, which is the whole toolchain. Versions
come from the committed `uv.lock`, so everyone and every CI run gets the same
ones; `ty` in particular is pinned exactly, because it is 0.0.x and moving.

The four gates, all configured in `pyproject.toml`:

```sh
uv run ruff check           # lint          (add --fix to apply safe fixes)
uv run ruff format          # format        (add --check to assert instead)
uv run ty check             # types
uv run pytest               # tests
```

**Run these from the repo root.** `ruff` and `ty` work from any directory, but
`pytest` only honours `testpaths` when it is started from the rootdir — run it
anywhere else and it silently collects nothing and reports success.

Scope: the gates cover `src/urbandocs/` and `tests/` only. `scripts/` holds
research scripts kept as evidence for decisions already made, and
`tools/docling-convert/` resolves its own ML toolchain; both are excluded
deliberately, so do not "fix" them into the gates.

Two settings are worth knowing before they surprise you:

- **`ty` treats `missing-type-argument` as an error.** A bare `dict` or `list`
  annotation resolves its parameters to `Unknown` and switches type checking off
  downstream, so write `dict[str, int]`, or name the shape (`ingest.py` defines
  `Node`, `Box` and `Row` for exactly this).
- **pytest turns warnings into failures** (`filterwarnings = ["error"]`) and
  `xfail` is strict.

## Commit & PR conventions

- Use [Conventional Commits](https://www.conventionalcommits.org/) for all commit messages (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, etc.).
- Do **not** add "Co-authored-by" AI/assistant trailers or any "Generated with" AI attribution to commits or PRs.

## Agent skills

### Issue tracker

Issues and PRDs live as GitHub issues (via the `gh` CLI). External PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout (`CONTEXT.md` + `docs/adr/` at repo root). See `docs/agents/domain.md`.
