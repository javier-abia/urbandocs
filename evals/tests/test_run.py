from urbandocs_evals.run import _select_examples


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
