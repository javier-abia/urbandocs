"""Run the harness as a LangSmith Experiment against the gold-set Dataset (#85).

One `aevaluate` call: `target` drives a fresh agent through the real MCP
loop for each question, `judge_evaluator` grades the resulting answer
pass/fail against that question's gold answer and sources, as the
`correctness` feedback key. Each call is its own LangSmith Experiment, so
pass rate is comparable run-over-run through the LangSmith UI rather than a
local log the next run overwrites. When the judge flags a wrong extra claim
the candidate volunteered, that's a second, separate `extra_claim` feedback
key -- informational for spot-checking, it never changes `correctness`.
`metrics_evaluator` records #84's latency/token-usage/step-count benchmarks
as three more feedback keys, off the same run -- no second model call, just
surfacing what `target` already measured.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from langsmith import Client
from langsmith.evaluation import aevaluate
from langsmith.schemas import Example, Run

from urbandocs_evals.agent import answer_question, build_agent
from urbandocs_evals.config import Config
from urbandocs_evals.judge import GradingInputs, build_judge, grade


def _select_examples(
    client: Client, dataset_name: str, question_set: str | None
) -> str | Iterable[Example]:
    """`aevaluate`'s `data` -- the whole Dataset by name, or one `set` from it.

    Filters on each example's `metadata={"set": ...}` (set by
    `upload_dataset`) instead of maintaining a second Dataset, so an
    easy-only or complex-only run's pass rate stays comparable, in the same
    LangSmith UI, to a run against the whole gold set.
    """
    if question_set is None:
        return dataset_name
    return client.list_examples(dataset_name=dataset_name, metadata={"set": question_set})


def _metrics_results(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    """The #84 feedback rows for one run's `target` outputs.

    Pulled out of `metrics_evaluator` so the mapping is unit-testable without
    a `Run` object -- `target` already put these fields there, this just
    names them as LangSmith feedback keys. Token counts ride on `value`, not
    `score`: LangSmith rejects a feedback `score` outside
    +-99999.9999 (422 on ingest), a bound a sweep-heavy question's prompt
    tokens clear in practice. `latency_seconds`/`step_count` stay on `score`
    since nothing in this harness gets near that ceiling for either.
    """
    return [
        {"key": "latency_seconds", "score": outputs.get("latency_seconds")},
        {"key": "input_tokens", "value": outputs.get("input_tokens")},
        {"key": "output_tokens", "value": outputs.get("output_tokens")},
        {"key": "step_count", "score": outputs.get("tool_calls")},
    ]


async def run_experiment(
    cfg: Config,
    client: Client,
    *,
    concurrency: int = 1,
    experiment_prefix: str = "urbandocs-eval",
    question_set: str | None = None,
) -> Any:
    judge = build_judge(cfg)

    async def target(inputs: dict[str, str]) -> dict[str, Any]:
        # A fresh agent (and fresh MCP session) per question -- simplest
        # thing that is safe under concurrency; 20 questions makes the
        # reconnect cost a non-issue.
        agent = build_agent(cfg)
        result = await answer_question(agent, inputs["question"], max_requests=cfg.max_requests)
        return {
            "answer": result.answer,
            "latency_seconds": result.elapsed_seconds,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "tool_calls": result.usage.tool_calls,
        }

    async def judge_evaluator(run: Run, example: Example | None) -> dict[str, Any]:
        if example is None:
            raise ValueError("judge_evaluator needs the gold example to grade against")
        outputs = run.outputs or {}
        reference = example.outputs or {}
        verdict = await grade(
            judge,
            GradingInputs(
                question=example.inputs["question"],
                candidate_answer=outputs.get("answer", ""),
                gold_answer=reference.get("answer", ""),
                gold_sources=reference.get("sources", ""),
            ),
        )
        results: list[dict[str, Any]] = [
            {"key": "correctness", "score": verdict.passed, "comment": verdict.reasoning}
        ]
        if verdict.extra_claim_note:
            # Informational only -- flagged for the owner's spot-check, never
            # folded into `correctness`/`passed`.
            results.append(
                {"key": "extra_claim", "score": False, "comment": verdict.extra_claim_note}
            )
        return {"results": results}

    def metrics_evaluator(run: Run, example: Example | None) -> dict[str, Any]:
        # #84: latency/token-usage/step-count, alongside `correctness` on the
        # same run -- `target` already computed these, so no LLM call here.
        return {"results": _metrics_results(run.outputs or {})}

    return await aevaluate(
        target,
        data=_select_examples(client, cfg.langsmith_dataset, question_set),
        evaluators=[judge_evaluator, metrics_evaluator],
        experiment_prefix=experiment_prefix,
        max_concurrency=concurrency,
        client=client,
    )
