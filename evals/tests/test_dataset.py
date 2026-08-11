from pathlib import Path

import pytest

from urbandocs_evals.dataset import load_gold_set

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"


def test_load_gold_set_joins_all_twenty_questions() -> None:
    gold = load_gold_set(DOCS_DIR)
    assert len(gold) == 20
    assert {g.set_ for g in gold} == {"easy", "complex"}


def test_each_example_has_question_answer_and_sources() -> None:
    gold = load_gold_set(DOCS_DIR)
    for g in gold:
        assert g.question.strip()
        assert g.answer.strip()
        assert g.sources.strip()


def test_keys_are_unique() -> None:
    gold = load_gold_set(DOCS_DIR)
    keys = [g.key for g in gold]
    assert len(keys) == len(set(keys))


def test_mismatched_csvs_raise(tmp_path: Path) -> None:
    (tmp_path / "eval-questions.csv").write_text(
        "set,number,question\neasy,1,only in questions\n", encoding="utf-8"
    )
    (tmp_path / "eval-answers.csv").write_text(
        "set,number,answer,sources\neasy,2,only in answers,src\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="don't line up"):
        load_gold_set(tmp_path)
