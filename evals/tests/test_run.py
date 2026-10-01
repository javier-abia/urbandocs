from datetime import UTC, datetime

from langfuse.api.commons.types.dataset_item import DatasetItem
from langfuse.api.commons.types.dataset_status import DatasetStatus

from types import SimpleNamespace

from pydantic_ai.usage import RunUsage

from urbandocs_evals.agent import AnswerResult
from urbandocs_evals.run import _metrics_scores, _pass_rate, _select_items


def _item(id_: str, set_: str, status: DatasetStatus = DatasetStatus.ACTIVE) -> DatasetItem:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    return DatasetItem(
        id=id_,
        status=status,
        input={"question": "¿Q?"},
        expected_output={"answer": "a", "sources": "s"},
        metadata={"set": set_, "number": "1"},
        dataset_id="ds",
        dataset_name="urbandocs-gold-set",
        created_at=now,
        updated_at=now,
        media_references=[],
    )


def test_no_set_returns_every_active_item() -> None:
    items = [_item("a", "easy"), _item("b", "complex")]
    assert [i.id for i in _select_items(items, None)] == ["a", "b"]


def test_set_filters_by_metadata() -> None:
    items = [_item("a", "easy"), _item("b", "complex")]
    assert [i.id for i in _select_items(items, "easy")] == ["a"]


def test_archived_items_never_run() -> None:
    # `upload_dataset` archives an item dropped from the gold set rather than
    # deleting it (which would erase its run history), so selection must skip it.
    items = [_item("a", "easy"), _item("gone", "easy", DatasetStatus.ARCHIVED)]
    assert [i.id for i in _select_items(items, None)] == ["a"]
    assert [i.id for i in _select_items(items, "easy")] == ["a"]


def test_metrics_scores_name_the_run_metrics_as_numeric_scores() -> None:
    result = AnswerResult(
        answer="irrelevant here",
        usage=RunUsage(input_tokens=160_838, output_tokens=80, tool_calls=3),
        elapsed_seconds=4.5,
    )
    assert [(e.name, e.value, e.data_type) for e in _metrics_scores(result)] == [
        ("latency_seconds", 4.5, "NUMERIC"),
        ("input_tokens", 160_838, "NUMERIC"),
        ("output_tokens", 80, "NUMERIC"),
        ("step_count", 3, "NUMERIC"),
    ]


def test_metrics_scores_of_a_stalled_run_are_zero_not_none() -> None:
    # A run that hits the request cap reports zeroed usage (#84); a NUMERIC
    # score can't hold `None`.
    result = AnswerResult(answer="[stopped]", usage=RunUsage(), elapsed_seconds=1.0)
    assert all(e.value is not None for e in _metrics_scores(result))


def _item_result(*verdicts: bool) -> SimpleNamespace:
    return SimpleNamespace(
        evaluations=[SimpleNamespace(name="correctness", value=v) for v in verdicts]
        + [SimpleNamespace(name="extra_claim", value=False)]
    )


def test_pass_rate_counts_only_correctness() -> None:
    results = [_item_result(True), _item_result(False), _item_result(True)]
    rate = _pass_rate(item_results=results)  # type: ignore[arg-type]
    assert rate.value == 2 / 3
    assert rate.comment == "2/3 passed"


def test_pass_rate_with_no_verdicts_is_none() -> None:
    assert _pass_rate(item_results=[]).value is None
