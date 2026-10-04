"""Run the harness as a Langfuse Experiment against the gold-set Dataset (#85).

One `run_experiment` call: `task` drives a fresh agent through the real MCP
loop for each question, `judge_evaluator` grades the resulting answer
pass/fail against that question's gold answer and sources, as the
`correctness` score. Each call is its own Langfuse dataset run, so pass rate
is comparable run-over-run through the Langfuse UI rather than a local log
the next run overwrites. When the judge flags a wrong extra claim the
candidate volunteered, that's a second, separate `extra_claim` score --
informational for spot-checking, it never changes `correctness`. #84's
latency/token-usage/step-count benchmarks are scored from inside `task`, off
the same run -- no second model call -- and a run-level `pass_rate` sums up
`correctness`.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langfuse import Evaluation, Langfuse
from langfuse.api.commons.types.dataset_item import DatasetItem
from langfuse.api.commons.types.dataset_status import DatasetStatus
from langfuse.experiment import ExperimentItemResult, ExperimentResult
from pydantic_ai import Agent

from urbandocs_evals.agent import AnswerResult, answer_question, build_agent
from urbandocs_evals.config import Config
from urbandocs_evals.judge import GradingInputs, Verdict, build_judge, grade


def _select_items(items: list[DatasetItem], question_set: str | None) -> list[DatasetItem]:
    """The active items to run -- all of them, or one `set` from them.

    Filters on each item's `metadata={"set": ...}` (set by `upload_dataset`)
    instead of maintaining a second Dataset, so an easy-only or complex-only
    run's pass rate stays comparable, in the same Langfuse UI, to a run
    against the whole gold set. Archived items (dropped from the gold set)
    are never run.
    """
    return [
        item
        for item in items
        if item.status == DatasetStatus.ACTIVE
        and (question_set is None or (item.metadata or {}).get("set") == question_set)
    ]


def _metrics_scores(result: AnswerResult) -> list[Evaluation]:
    """The #84 scores for one agent run."""
    return [
        Evaluation(name="latency_seconds", value=result.elapsed_seconds, data_type="NUMERIC"),
        Evaluation(name="input_tokens", value=result.usage.input_tokens, data_type="NUMERIC"),
        Evaluation(name="output_tokens", value=result.usage.output_tokens, data_type="NUMERIC"),
        Evaluation(name="step_count", value=result.usage.tool_calls, data_type="NUMERIC"),
    ]


def _verdict_scores(verdict: Verdict) -> list[Evaluation]:
    """The judge's item scores: `correctness`, plus `extra_claim` when flagged."""
    results = [
        Evaluation(
            name="correctness",
            value=verdict.passed,
            comment=verdict.reasoning,
            data_type="BOOLEAN",
        )
    ]
    if verdict.extra_claim_note:
        # `True` = the judge flagged an extra claim. Informational only --
        # for the owner's spot-check, never folded into `correctness`.
        results.append(
            Evaluation(
                name="extra_claim",
                value=True,
                comment=verdict.extra_claim_note,
                data_type="BOOLEAN",
            )
        )
    return results


def _pass_rate(
    *, item_results: list[ExperimentItemResult], attempted: int, **kwargs: Any
) -> list[Evaluation]:
    """Run-level `pass_rate`: judge passes over every item attempted.

    The SDK drops an item whose task raised from `item_results`, so the
    denominator is `attempted`, not `len(item_results)` -- a crash is a fail.
    No items, no score.
    """
    if attempted == 0:
        return []
    passed = sum(
        bool(e.value) for r in item_results for e in r.evaluations if e.name == "correctness"
    )
    return [
        Evaluation(
            name="pass_rate", value=passed / attempted, comment=f"{passed}/{attempted} passed"
        )
    ]


def run_experiment(
    cfg: Config,
    client: Langfuse,
    *,
    concurrency: int = 1,
    experiment_name: str = "urbandocs-eval",
    question_set: str | None = None,
) -> ExperimentResult:
    # Exports pydantic-ai's model and MCP tool-call spans, so each item's
    # trace shows the full search/get loop, not just the final answer.
    Agent.instrument_all()
    judge = build_judge(cfg)
    items = _select_items(client.get_dataset(cfg.langfuse_dataset).items, question_set)

    async def task(*, item: DatasetItem, **kwargs: Any) -> str:
        # A fresh agent (and fresh MCP session) per question -- simplest
        # thing that is safe under concurrency; 20 questions makes the
        # reconnect cost a non-issue.
        agent = build_agent(cfg)
        question = (item.input or {})["question"]
        result = await answer_question(agent, question, max_requests=cfg.max_requests)
        # Scored on the item's task span, since only the task sees usage; the
        # trace output stays the answer alone.
        for score in _metrics_scores(result):
            client.score_current_span(
                name=score.name, value=score.value, data_type=score.data_type
            )
        return result.answer

    async def judge_evaluator(
        *,
        input: dict[str, str],
        output: str,
        expected_output: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[Evaluation]:
        if expected_output is None:
            raise ValueError("judge_evaluator needs the gold item to grade against")
        verdict = await grade(
            judge,
            GradingInputs(
                question=input["question"],
                candidate_answer=output,
                gold_answer=expected_output.get("answer", ""),
                gold_sources=expected_output.get("sources", ""),
            ),
        )
        return _verdict_scores(verdict)

    return client.run_experiment(
        name=experiment_name,
        data=items,
        task=task,
        evaluators=[judge_evaluator],
        run_evaluators=[partial(_pass_rate, attempted=len(items))],
        max_concurrency=concurrency,
    )
