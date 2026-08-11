from urbandocs_evals.judge import GradingInputs, format_judge_prompt


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
