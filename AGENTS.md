# AGENTS.md

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
