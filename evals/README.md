# evals — end-to-end eval harness (#85)

Runs the 20-question gold set (`docs/eval-questions.csv` +
`docs/eval-answers.csv`, #30) against the real engine, end to end: a
[`pydantic-ai`](https://ai.pydantic.dev/) agent connects to
`urbandocs.server`'s real `search`/`get`/`get_by_cite`/`get_page` tools as an
actual MCP client — no mocking — driven the way the tool descriptions
instruct. Model calls go through **LiteLLM** on a dedicated eval virtual key,
isolated from production traffic/spend. A second, different model grades
each answer pass/fail, all-or-nothing, against the gold answer and its
required citations; it separately flags (without affecting pass/fail) any
wrong extra claim the candidate volunteers beyond the gold answer, for
spot-checking. Every run is a **LangSmith Experiment** against a
**LangSmith Dataset** built from the gold set, so pass rate is comparable
run-over-run through the LangSmith UI, alongside three more per-question
feedback keys (#84): wall-clock **latency**, **input/output token usage**
(`RunResult.usage()`), and **step count** (`RunUsage.tool_calls`, the
number of tool calls before a final answer). These stay observational —
they don't gate `correctness` — so a change can be judged on more than
pass/fail.

Self-contained project, own `pyproject.toml`/`uv.lock`, same pattern as
`tools/docling-convert/` — resolved independently of the root project, not
part of the four gates (`ruff`/`ty`/`pytest`/`format`) `AGENTS.md` describes,
and touches nothing in the production `dependencies` list `urbandocs.server`
ships with.

## Setup

```sh
cd evals
uv sync
cp .env.example .env   # then fill in the values below
```

Every value in `.env` is required at run time except where noted — this
harness fails loud on a missing variable rather than defaulting a model
name or falling back silently. See `.env.example` for the full list and
what each one is for. In short:

- `LITELLM_BASE_URL` / `LITELLM_EVAL_API_KEY` — the dedicated eval key.
- `EVAL_MODEL` / `EVAL_JUDGE_MODEL` — must differ (self-preference bias,
  enforced); the judge should also be the *stronger* of the two (#85),
  which the harness can't check for you. No default, since #85 leaves the
  exact choice to whatever production LiteLLM actually runs.
- `URBANDOCS_MCP_URL` — required. LiteLLM's own MCP passthrough route
  (`<litellm-url>/normativa/mcp`, `docs/ops/deploy-runbook.md`), the same
  path an architect's agent uses in production — not derived from
  `LITELLM_BASE_URL`, since that's the chat-completions base and the two
  aren't the same URL. Point at the engine directly instead if running
  from the box itself.
- `LANGSMITH_API_KEY` (and friends) — read directly by the `langsmith` SDK.
- `EVAL_MAX_REQUESTS` — optional, defaults to 50. Caps model requests per
  question, the enforced form of "runs until it produces a final answer,
  or stops" (#85).

## Run

**Once**, to create the LangSmith Dataset from the gold-set CSVs:

```sh
uv run urbandocs-evals upload-dataset
```

Idempotent — a dataset that already exists is left untouched; pass
`--recreate` to drop and rebuild it after the gold set changes.

**Every eval run**, against that dataset, as a new Experiment:

```sh
uv run urbandocs-evals run
```

Manual, on demand — no CI wiring (#85's scope; this repo has no CI/CD
pipeline and deploys are already manual). `--concurrency N` runs more than
one question at a time (default 1: sequential, simplest thing that's safe
against a fresh MCP session per question); `--experiment-prefix` names the
run in LangSmith; `--set {easy,complex}` runs only that tier (default: the
whole gold set). One Dataset either way — `--set` filters by each
example's `set` metadata rather than pointing at a second Dataset, so
pass rate stays comparable across easy-only, complex-only and full runs
in the same LangSmith UI:

```sh
uv run urbandocs-evals run --set easy
uv run urbandocs-evals run --set complex
```

Judge verdicts are **spot-checked by the owner**, not read exhaustively for
every run (#85) — that's the tradeoff for being able to re-run this often.

## What this does and doesn't cover

In scope: one fixed model under test, the model LiteLLM's production config
actually runs — this is not a model-comparison matrix. Out of scope, and
tracked separately:

- Wiring LiteLLM's own production traffic into LangSmith tracing —
  `docs/ops/deploy-runbook.md`'s deferred work, unrelated to this harness's
  own tracing (each `run` call already produces one LangSmith Experiment).

## Layout

```
evals/
├── src/urbandocs_evals/
│   ├── config.py    # env -> Config, fail-loud
│   ├── dataset.py   # gold-set CSVs -> LangSmith Dataset
│   ├── agent.py      # the agent under test: LiteLLM model + real MCP toolset
│   ├── judge.py       # the grading model: pass/fail, all-or-nothing
│   ├── run.py          # one aevaluate() call: target + judge evaluator
│   └── cli.py            # `upload-dataset` / `run`
└── tests/            # unit tests only -- CSV joining, prompt formatting,
                       # config validation. No network, no live model calls.
```
