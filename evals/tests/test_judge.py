from urbandocs_evals.judge import JUDGE_SYSTEM_PROMPT, GradingInputs, Verdict, format_judge_prompt


def test_system_prompt_flags_wrong_extra_claims_without_gating_pass() -> None:
    # Regression guard: a wrong extra claim is tracked (extra_claim_note)
    # but must not itself flip `passed` -- only content match and citation
    # coverage do.
    assert "beyond the gold answer" in JUDGE_SYSTEM_PROMPT
    assert "extra_claim_note" in JUDGE_SYSTEM_PROMPT
    assert "must NOT change" in JUDGE_SYSTEM_PROMPT


def test_verdict_extra_claim_note_defaults_empty() -> None:
    verdict = Verdict(passed=True, reasoning="matches")
    assert verdict.extra_claim_note == ""


def test_format_judge_prompt_carries_all_four_fields() -> None:
    prompt = format_judge_prompt(
        GradingInputs(
            question="¿Q?",
            candidate_answer="candidate",
            gold_answer="gold",
            gold_sources="DB-SI.md:629",
        )
    )
    assert "¿Q?" in prompt
    assert "candidate" in prompt
    assert "gold" in prompt
    assert "DB-SI.md:629" in prompt
