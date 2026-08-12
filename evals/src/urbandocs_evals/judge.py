"""LLM judge: pass/fail, all-or-nothing (#85, per #30's no-partial-credit rule).

A second, different model from the one under test grades each answer against
the gold `answer` and `sources` columns, to avoid self-preference bias
(`Config.from_env` refuses to build a harness where they're the same model).
PASS requires **both** content match and citation coverage -- a fluent
answer missing or misciting its source is a FAIL, never a partial score.
Separately, the judge flags any wrong extra claim the candidate volunteers
beyond the gold answer, for spot-checking -- that flag does not itself
change the verdict.
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
    "way the gold answer is.\n\n"
    "Separately from the pass/fail verdict, check whether the candidate "
    "volunteers information beyond the gold answer -- an extra figure, "
    "exception, or qualifier the gold answer never claimed. If any of that "
    "extra material is wrong or contradicts the gold answer, name it in "
    "`extra_claim_note`; otherwise leave `extra_claim_note` empty. Do not "
    "flag detail that is merely unverifiable from what's in front of you -- "
    "only flag extra material you can actually identify as wrong or "
    "contradictory. This flag is for the record only and must NOT change "
    "`passed` -- a candidate with a wrong extra claim can still PASS if (1) "
    "and (2) above are satisfied.\n\n"
    "The gold `sources` column names each document by the filename of its "
    "human-readable draft (e.g. `dog-habitabilidad.md`, `DB-SI.md`). The "
    "candidate agent never sees those filenames -- it cites the same "
    "documents by the short code the production corpus mints for them. "
    "Both name the same document; treat them as equivalent when checking "
    "citation coverage:\n"
    "  D128 = dog-habitabilidad   DBS = DB-SI      SUA = DccSUA\n"
    "  DOG  = DOG_2025            LEY = ley-suelo-galicia   PGO = PGOM\n"
    "A candidate citing `D128:p31:§A.3.2.3.c` for a gold source of "
    "`dog-habitabilidad.md:1141` has covered that source -- do not fail an "
    "answer solely because it used the short code instead of the filename."
)


class Verdict(BaseModel):
    passed: bool = Field(description="True only if both content and citation coverage pass.")
    reasoning: str = Field(description="One or two sentences: why, citing what was missing if it failed.")
    extra_claim_note: str = Field(
        default="",
        description="Wrong or contradictory extra material the candidate volunteered beyond "
        "the gold answer, if any -- empty if none. Informational only; never affects `passed`.",
    )


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
