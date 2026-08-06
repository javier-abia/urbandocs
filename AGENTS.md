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

## Commit hooks

After `uv sync`, one more command per clone:

```sh
uv run pre-commit install
```

Skipping it is not fatal — CI runs the same config over every file — but you
will find out in review rather than in a second. Git hooks live in `.git/`,
which is not cloned and not shared, so this is per-clone. (It *is* shared
between a repo and its worktrees, which use the same `.git/hooks`.)

The hooks **fix rather than reject** wherever they can, because agents commit
here and a failure nobody can diagnose becomes a retry loop. When a hook edits
your files the commit aborts with `files were modified by this hook` — that is
success, not failure. Re-run `git add` on the changed paths and commit again.

What runs, from `.pre-commit-config.yaml` (~2s over the whole repo):

```
trailing whitespace, end of file    fix
check-added-large-files (3 MB)      reject
detect-secrets                      reject
ruff check --fix                    fix what it can, reject the rest
ruff format                         fix
```

`ty` and `pytest` are deliberately *not* here: they can only reject, so they
belong to CI. Nor are the ruff rules with no safe fix — `ANN`, `ARG`, `E501`,
`N818`, `RET504`, `F841` will stop a commit, and you have to fix them yourself.

Two things that will otherwise surprise you:

- **The whitespace hooks skip `documentos/`, `tests/fixtures/` and `LICENSE`.**
  Those are byte-faithful artifacts, not source. `tests/fixtures/corpus/corpus.tsv`
  in particular has rows ending in two tabs — empty `text` and `norm` columns —
  and stripping them makes the rows 6 columns wide and breaks five tests.
- **A secret-scan false positive** is silenced with a trailing
  `# pragma: allowlist secret` on the line. That is the hatch to reach for.
  `detect-secrets` is not a project dependency — pre-commit builds it in its own
  venv — so re-recording the whole baseline, which you should rarely want, means
  `uvx --from 'detect-secrets==1.5.0' detect-secrets scan --baseline .secrets.baseline`,
  with the version matching the `rev` in `.pre-commit-config.yaml`.

To bypass everything in an emergency: `git commit --no-verify`. CI will still
catch it.

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
