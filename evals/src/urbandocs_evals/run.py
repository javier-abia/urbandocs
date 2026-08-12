"""Run the harness as a LangSmith Experiment against the gold-set Dataset (#85).

One `aevaluate` call: `target` drives a fresh agent through the real MCP
loop for each question, `judge_evaluator` grades the resulting answer
pass/fail against that question's gold answer and sources. Each call is
its own LangSmith Experiment, so pass rate is comparable run-over-run
through the LangSmith UI rather than a local log the next run overwrites.
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


async def run_experiment(
    cfg: Config,
    client: Client,
    *,
    concurrency: int = 1,
    experiment_prefix: str = "urbandocs-eval",
    question_set: str | None = None,
) -> Any:
    judge = build_judge(cfg)

    async def target(inputs: dict[str, str]) -> dict[str, str]:
        # A fresh agent (and fresh MCP session) per question -- simplest
        # thing that is safe under concurrency; 20 questions makes the
        # reconnect cost a non-issue.
        agent = build_agent(cfg)
        answer = await answer_question(agent, inputs["question"], max_requests=cfg.max_requests)
        return {"answer": answer}

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
        return {
            "key": "correctness",
            "score": verdict.passed,
            "comment": verdict.reasoning,
        }

    return await aevaluate(
        target,
        data=_select_examples(client, cfg.langsmith_dataset, question_set),
        evaluators=[judge_evaluator],
        experiment_prefix=experiment_prefix,
        max_concurrency=concurrency,
        client=client,
    )
