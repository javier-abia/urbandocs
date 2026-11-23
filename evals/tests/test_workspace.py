from pydantic_ai import RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from urbandocs_evals.agent import AnswerResult
from urbandocs_evals.run import _metrics_scores
from urbandocs_evals.workspace import (
    SHOW,
    WorkerStats,
    Workspace,
    collapse_old_results,
    page_of,
    render,
)


def _ctx(ws: Workspace) -> RunContext[Workspace]:
    return RunContext(deps=ws, model=TestModel(), usage=RunUsage())


def _round(call_id: str, content: object) -> list[ModelResponse | ModelRequest]:
    return [
        ModelResponse(parts=[ToolCallPart("get", {}, tool_call_id=call_id)]),
        ModelRequest(parts=[ToolReturnPart("get", content, tool_call_id=call_id)]),
    ]


def _returned(messages: list) -> list[object]:
    return [
        p.content
        for m in messages
        if isinstance(m, ModelRequest)
        for p in m.parts
        if isinstance(p, ToolReturnPart)
    ]


def test_older_results_become_their_log_line_and_the_latest_stays_whole() -> None:
    ws = Workspace(mcp=MCPToolset("http://unused"), stubs={"a": "get -> 2 records", "b": "x"})
    messages = [
        ModelRequest(parts=[UserPromptPart("q")]),
        *_round("a", {"records": ["big"]}),
        *_round("b", {"records": ["latest"]}),
    ]
    assert _returned(collapse_old_results(_ctx(ws), messages)) == [
        "get -> 2 records",
        {"records": ["latest"]},
    ]
    # The run's own history is left untouched.
    assert _returned(messages)[0] == {"records": ["big"]}


def test_search_page_keeps_each_sections_ancestor_chain() -> None:
    response = {
        "ancestors": [f"h{i}" for i in range(SHOW + 5)],
        "sections": [{"section_id": f"s{i}", "ancestor_ids": [0, i]} for i in range(SHOW + 5)],
    }
    page = page_of(response, SHOW)
    assert [s["section_id"] for s in page["sections"]] == [f"s{i}" for i in range(SHOW, SHOW + 5)]
    chains = [[page["ancestors"][i] for i in s["ancestor_ids"]] for s in page["sections"]]
    assert chains == [["h0", f"h{i}"] for i in range(SHOW, SHOW + 5)]


def test_reply_carries_citation_chain_text_and_children() -> None:
    record = {
        "id": "DBS:p24:§2",
        "doc": "DBS",
        "page": 24,
        "ancestors": ["4 Dimensionado", "4.2 Cálculo"],
        "text": "Puertas y pasos A ≥ P / 200 ≥ 0,80 m",
        "children": [{"id": "DBS:p24:§3", "text": "(1) nota"}],
    }
    assert render([record]) == (
        "[DBS p.24 · DBS:p24:§2]\n4 Dimensionado > 4.2 Cálculo\n"
        "Puertas y pasos A ≥ P / 200 ≥ 0,80 m\n  DBS:p24:§3: (1) nota"
    )


def test_workspace_run_also_scores_the_worker() -> None:
    worker = WorkerStats(
        usage=RunUsage(input_tokens=9_000, output_tokens=300, tool_calls=6),
        peak_context_tokens=4_000,
    )
    result = AnswerResult(answer="a", usage=RunUsage(), elapsed_seconds=1.0, worker=worker)
    named = {e.name: e.value for e in _metrics_scores(result)}
    assert {k: named[k] for k in named if k.startswith("worker_")} == {
        "worker_input_tokens": 9_000,
        "worker_output_tokens": 300,
        "worker_step_count": 6,
        "worker_peak_context_tokens": 4_000,
    }
