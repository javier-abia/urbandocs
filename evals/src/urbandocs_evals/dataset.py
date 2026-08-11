"""Upload the gold set as a LangSmith Dataset (#85).

`docs/eval-questions.csv` and `docs/eval-answers.csv` are the 20-question
gold set (#30) -- one row per question, joined here on `(set, number)` into
one LangSmith example per question: `inputs={"question"}`,
`outputs={"answer", "sources"}` as the reference an experiment is graded
against. Uploaded once; every harness run afterwards is an Experiment
against this same Dataset, so pass rate is comparable run-over-run (#85).
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from langsmith import Client
from langsmith.schemas import ExampleCreate

QUESTIONS_CSV = "eval-questions.csv"
ANSWERS_CSV = "eval-answers.csv"


@dataclass(frozen=True)
class GoldExample:
    set_: str
    number: str
    question: str
    answer: str
    sources: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.set_, self.number)


def _read_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not any(row.values()):
                continue  # trailing blank line
            yield row


def load_gold_set(docs_dir: Path) -> list[GoldExample]:
    """Join the questions and answers CSVs into one example per question."""
    questions = {
        (row["set"], row["number"]): row["question"]
        for row in _read_rows(docs_dir / QUESTIONS_CSV)
    }
    answers = {
        (row["set"], row["number"]): row for row in _read_rows(docs_dir / ANSWERS_CSV)
    }

    if questions.keys() != answers.keys():
        missing_answers = questions.keys() - answers.keys()
        missing_questions = answers.keys() - questions.keys()
        raise ValueError(
            f"questions and answers CSVs don't line up -- "
            f"missing answers for {sorted(missing_answers)}, "
            f"missing questions for {sorted(missing_questions)}"
        )

    return [
        GoldExample(
            set_=set_,
            number=number,
            question=questions[set_, number],
            answer=answers[set_, number]["answer"],
            sources=answers[set_, number]["sources"],
        )
        for set_, number in questions
    ]


def upload_dataset(
    client: Client,
    dataset_name: str,
    docs_dir: Path,
    *,
    recreate: bool = False,
) -> str:
    """Create (or replace) the LangSmith dataset from the gold-set CSVs.

    Returns a one-line summary for the caller to print. Idempotent by
    default: an existing dataset is left alone and reported, not silently
    re-uploaded into duplicate examples -- pass `recreate=True` to drop and
    rebuild it (e.g. after the gold set changes).
    """
    gold = load_gold_set(docs_dir)

    exists = client.has_dataset(dataset_name=dataset_name)
    if exists and recreate:
        client.delete_dataset(dataset_name=dataset_name)
        exists = False

    if exists:
        return (
            f"dataset {dataset_name!r} already exists -- left untouched "
            f"({len(gold)} rows in the CSVs). Pass --recreate to rebuild it."
        )

    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description=(
            "urbandocs gold set (#30): 20 normativa questions, each with a "
            "human-judged answer and its required citations. PASS is "
            "all-or-nothing -- content matches AND every cited source is "
            "covered, per #85."
        ),
    )
    client.create_examples(
        dataset_id=dataset.id,
        examples=[
            ExampleCreate(
                inputs={"question": g.question},
                outputs={"answer": g.answer, "sources": g.sources},
                metadata={"set": g.set_, "number": g.number},
            )
            for g in gold
        ],
    )
    return f"created dataset {dataset_name!r} with {len(gold)} examples"
