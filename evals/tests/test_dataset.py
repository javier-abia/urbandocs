from pathlib import Path
from types import SimpleNamespace

import pytest
from langfuse.api import NotFoundError
from langfuse.api.commons.types.dataset_status import DatasetStatus

from urbandocs_evals.dataset import load_gold_set, upload_dataset

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


DATASET = "urbandocs-gold-set"


def _write_gold(docs_dir: Path, rows: list[tuple[str, str]]) -> None:
    q = ["set,number,question"] + [f"{s},{n},Q{s}{n}" for s, n in rows]
    a = ["set,number,answer,sources"] + [f"{s},{n},A{s}{n},S{s}{n}" for s, n in rows]
    (docs_dir / "eval-questions.csv").write_text("\n".join(q) + "\n", encoding="utf-8")
    (docs_dir / "eval-answers.csv").write_text("\n".join(a) + "\n", encoding="utf-8")


class FakeLangfuse:
    """Stores items by id, upserting on `create_dataset_item` as Langfuse does."""

    def __init__(self, items: list[SimpleNamespace] | None = None) -> None:
        self.exists = items is not None
        self.items = {i.id: i for i in items or []}
        self.writes: list[SimpleNamespace] = []

    def get_dataset(self, name: str) -> SimpleNamespace:
        if not self.exists:
            raise NotFoundError(body=f"dataset {name} not found")
        return SimpleNamespace(items=list(self.items.values()))

    def create_dataset(self, **_: str) -> None:
        self.exists = True

    def create_dataset_item(self, **kwargs: object) -> None:
        item = SimpleNamespace(**kwargs)
        self.writes.append(item)
        self.items[item.id] = item


def _existing(id_: str, status: DatasetStatus) -> SimpleNamespace:
    return SimpleNamespace(
        id=id_,
        status=status,
        input={"question": "old"},
        expected_output={"answer": "old", "sources": "old"},
        metadata={"set": "easy", "number": "9"},
    )


def _upload(client: FakeLangfuse, docs_dir: Path) -> str:
    return upload_dataset(client, DATASET, docs_dir)  # type: ignore[arg-type]


def test_upload_upserts_every_row_active_on_a_stable_id(tmp_path: Path) -> None:
    _write_gold(tmp_path, [("easy", "1"), ("complex", "2")])
    client = FakeLangfuse()
    _upload(client, tmp_path)
    assert client.exists
    assert [vars(w) for w in client.writes] == [
        {
            "dataset_name": DATASET,
            "id": f"{DATASET}-easy-1",
            "input": {"question": "Qeasy1"},
            "expected_output": {"answer": "Aeasy1", "sources": "Seasy1"},
            "metadata": {"set": "easy", "number": "1"},
            "status": DatasetStatus.ACTIVE,
        },
        {
            "dataset_name": DATASET,
            "id": f"{DATASET}-complex-2",
            "input": {"question": "Qcomplex2"},
            "expected_output": {"answer": "Acomplex2", "sources": "Scomplex2"},
            "metadata": {"set": "complex", "number": "2"},
            "status": DatasetStatus.ACTIVE,
        },
    ]


def test_upload_archives_an_item_dropped_from_the_csvs(tmp_path: Path) -> None:
    _write_gold(tmp_path, [("easy", "1")])
    gone = _existing(f"{DATASET}-easy-9", DatasetStatus.ACTIVE)
    client = FakeLangfuse([gone])
    summary = _upload(client, tmp_path)
    archived = client.items[gone.id]
    # Re-written as-is with only the status flipped: deleting would erase run history.
    assert archived.status == DatasetStatus.ARCHIVED
    assert (archived.input, archived.expected_output, archived.metadata) == (
        gone.input,
        gone.expected_output,
        gone.metadata,
    )
    assert summary.endswith("1 items upserted, 1 archived")


def test_upload_reactivates_an_archived_item_back_in_the_csvs(tmp_path: Path) -> None:
    _write_gold(tmp_path, [("easy", "1")])
    back = _existing(f"{DATASET}-easy-1", DatasetStatus.ARCHIVED)
    client = FakeLangfuse([back])
    summary = _upload(client, tmp_path)
    assert [(w.id, w.status) for w in client.writes] == [
        (back.id, DatasetStatus.ACTIVE)
    ]
    assert client.items[back.id].input == {"question": "Qeasy1"}
    assert summary.endswith("0 archived")


def test_upload_is_idempotent(tmp_path: Path) -> None:
    _write_gold(tmp_path, [("easy", "1"), ("complex", "2")])
    client = FakeLangfuse()
    _upload(client, tmp_path)
    first = dict(client.items)
    client.writes.clear()
    summary = _upload(client, tmp_path)
    assert [vars(w) for w in client.writes] == [vars(i) for i in first.values()]
    assert client.items.keys() == first.keys()
    assert summary.endswith("2 items upserted, 0 archived")
