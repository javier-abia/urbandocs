from urbandocs_evals.run import _metrics_results, _select_examples


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def list_examples(self, *, dataset_name: str, metadata: dict[str, str]) -> str:
        self.calls.append((dataset_name, metadata))
        return "filtered-examples"  # stand-in for the real Example iterator


def test_no_set_returns_dataset_name_unfiltered() -> None:
    client = _RecordingClient()
    result = _select_examples(client, "urbandocs-gold-set", None)  # type: ignore[arg-type]
    assert result == "urbandocs-gold-set"
    assert client.calls == []


def test_set_filters_by_metadata() -> None:
    client = _RecordingClient()
    result = _select_examples(client, "urbandocs-gold-set", "easy")  # type: ignore[arg-type]
    assert result == "filtered-examples"
    assert client.calls == [("urbandocs-gold-set", {"set": "easy"})]


def test_metrics_results_names_targets_outputs_as_feedback_keys() -> None:
    outputs = {
        "answer": "irrelevant here",
        "latency_seconds": 4.5,
        "input_tokens": 1200,
        "output_tokens": 80,
        "tool_calls": 3,
    }
    assert _metrics_results(outputs) == [
        {"key": "latency_seconds", "score": 4.5},
        {"key": "input_tokens", "score": 1200},
        {"key": "output_tokens", "score": 80},
        {"key": "step_count", "score": 3},
    ]


def test_metrics_results_tolerates_missing_outputs() -> None:
    # A stalled run's `target` output still has these keys (#84's
    # zeroed-usage case), but the evaluator itself must not raise on a
    # `Run.outputs` shaped some other way.
    assert _metrics_results({}) == [
        {"key": "latency_seconds", "score": None},
        {"key": "input_tokens", "score": None},
        {"key": "output_tokens", "score": None},
        {"key": "step_count", "score": None},
    ]
