"""LLM judge: pass/fail, all-or-nothing (#85, per #30's no-partial-credit rule).

A second, different model from the one under test grades each answer against
the gold `answer` and `sources` columns, to avoid self-preference bias
(`Config.from_env` refuses to build a harness where they're the same model).
PASS requires **both** content match and citation coverage -- a fluent
answer missing or misciting its source is a FAIL, never a partial score.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from urbandocs_evals.agent import build_litellm_model
from urbandocs_evals.config import Config

JUDGE_SYSTEM_PROMPT = (
    "You are grading one answer from a normativa search agent against a "
    "human-written gold answer, pass/fail, all-or-nothing. There is no "
    "partial credit: a rule returned without its qualifier is not 80% "
    "correct, it is incorrect. PASS requires BOTH of the following: "
    "(1) the candidate answer's content matches the gold answer's -- same "
    "governing rule(s), same figures, same qualifiers and exceptions, "
    "not just a similar-sounding answer; and (2) the candidate answer's "
    "cited sources cover the gold `sources` -- every document/article the "
    "gold answer cites must be identifiable in the candidate's own "
    "citations (exact page numbers need not match verbatim, but the "
    "document and provision must be traceable to the gold source). A "
    "fluent, correct-sounding answer that is missing a citation, or cites "
    "the wrong provision, is a FAIL. Judge only what's in front of you -- "
    "do not reward an answer for being plausible if it isn't grounded the "
    "way the gold answer is."
)


class Verdict(BaseModel):
    passed: bool = Field(description="True only if both content and citation coverage pass.")
    reasoning: str = Field(description="One or two sentences: why, citing what was missing if it failed.")


def build_judge(cfg: Config) -> Agent[None, Verdict]:
    return Agent(
        build_litellm_model(cfg, cfg.judge_model),
        output_type=Verdict,
        system_prompt=JUDGE_SYSTEM_PROMPT,
    )


@dataclass(frozen=True)
class GradingInputs:
    """The four fields one grading call needs, travelling together."""

    question: str
    candidate_answer: str
    gold_answer: str
    gold_sources: str


def format_judge_prompt(inputs: GradingInputs) -> str:
    return (
        f"Question:\n{inputs.question}\n\n"
        f"Gold answer (reference):\n{inputs.gold_answer}\n\n"
        f"Gold sources (must be covered):\n{inputs.gold_sources}\n\n"
        f"Candidate answer to grade:\n{inputs.candidate_answer}"
    )


async def grade(judge: Agent[None, Verdict], inputs: GradingInputs) -> Verdict:
    result = await judge.run(format_judge_prompt(inputs))
    return result.output
