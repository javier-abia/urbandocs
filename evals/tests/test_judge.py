from urbandocs_evals.judge import JUDGE_SYSTEM_PROMPT, GradingInputs, format_judge_prompt


def test_system_prompt_fails_wrong_extra_claims() -> None:
    # Regression guard for the criterion itself, not just content match and
    # citation coverage -- a correct core answer padded with a wrong extra
    # claim must still be a FAIL.
    assert "wrong" in JUDGE_SYSTEM_PROMPT
    assert "beyond the gold answer" in JUDGE_SYSTEM_PROMPT


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
