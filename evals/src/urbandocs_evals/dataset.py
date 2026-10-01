"""Sync the gold set into a Langfuse Dataset (#85).

`docs/eval-questions.csv` and `docs/eval-answers.csv` are the 20-question
gold set (#30) -- one row per question, joined here on `(set, number)` into
one Langfuse dataset item per question: `input={"question"}`,
`expected_output={"answer", "sources"}` as the reference an experiment is
graded against. Every harness run is an Experiment against this same
Dataset, so pass rate is comparable run-over-run (#85).
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from langfuse import Langfuse
from langfuse.api import NotFoundError
from langfuse.api.commons.types.dataset_status import DatasetStatus

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

    def item_id(self, dataset_name: str) -> str:
        # Langfuse upserts items on id, unique project-wide -- so prefix the dataset.
        return f"{dataset_name}-{self.set_}-{self.number}"


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


def upload_dataset(client: Langfuse, dataset_name: str, docs_dir: Path) -> str:
    """Create the Langfuse dataset if missing and sync its items to the CSVs.

    Returns a one-line summary for the caller to print. Idempotent: items
    upsert on a deterministic id, so re-running after a gold-set edit updates
    them in place (Langfuse versions items, so past runs keep what they saw).
    An item no longer in the CSVs is archived, not deleted -- deleting would
    erase its run history.
    """
    gold = load_gold_set(docs_dir)

    try:
        existing = client.get_dataset(dataset_name).items
    except NotFoundError:
        client.create_dataset(
            name=dataset_name,
            description=(
                "urbandocs gold set (#30): 20 normativa questions, each with a "
                "human-judged answer and its required citations. PASS is "
                "all-or-nothing -- content matches AND every cited source is "
                "covered, per #85."
            ),
        )
        existing = []

    for g in gold:
        client.create_dataset_item(
            dataset_name=dataset_name,
            id=g.item_id(dataset_name),
            input={"question": g.question},
            expected_output={"answer": g.answer, "sources": g.sources},
            metadata={"set": g.set_, "number": g.number},
            status=DatasetStatus.ACTIVE,
        )

    wanted = {g.item_id(dataset_name) for g in gold}
    orphans = [i for i in existing if i.id not in wanted and i.status == DatasetStatus.ACTIVE]
    for item in orphans:
        client.create_dataset_item(
            dataset_name=dataset_name,
            id=item.id,
            input=item.input,
            expected_output=item.expected_output,
            metadata=item.metadata,
            status=DatasetStatus.ARCHIVED,
        )

    return (
        f"synced dataset {dataset_name!r}: {len(gold)} items upserted, "
        f"{len(orphans)} archived"
    )
