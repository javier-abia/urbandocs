"""The server-side audit log (#65): every call records a re-runnable
invocation, re-running it reproduces the logged result, and nothing about
recording reaches the wire.
"""

from __future__ import annotations

import hashlib
import json
import shlex

import pytest
from mcp.client._memory import InMemoryTransport
from mcp.client.session import ClientSession

from urbandocs import audit, cli
from urbandocs.server import build_server
from urbandocs.substrate import load_substrate

CALLS = [
    ("search", {"terms": ["condicion", "puerta"]}),
    ("get", {"ids": ["D128:p21:A.2.2", "D128:p22:§4,§8,A.2.2.e", "nope"]}),
    ("get_by_cite", {"cite": "B.1", "doc": "D128"}),
    ("get_by_cite", {"cite": "a)"}),
    ("get_page", {"doc": "SUA", "page": 76}),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def substrate(fixture_dir):
    return load_substrate(corpus_path=fixture_dir / "corpus.tsv")


@pytest.fixture
def log(tmp_path, fixture_dir):
    return audit.AuditLog(
        tmp_path / "logs" / "audit.jsonl",
        audit.substrate_sha256(fixture_dir / "corpus.tsv"),
    )


async def _call(server, name, arguments):
    async with (
        InMemoryTransport(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await session.call_tool(name, arguments)


def _lines(log):
    return [json.loads(line) for line in log.path.read_text().splitlines()]


@pytest.mark.anyio
@pytest.mark.parametrize(("name", "arguments"), CALLS)
async def test_each_call_logs_an_invocation_that_reproduces_its_result(
    name, arguments, substrate, log, fixture_dir, capsysbinary
):
    await _call(build_server(substrate, log), name, arguments)

    [line] = _lines(log)
    assert line["substrate_sha256"] == log.substrate_sha256
    argv = shlex.split(line["invocation"])
    assert argv[: len(audit.PROG)] == audit.PROG

    corpus = ["--corpus", str(fixture_dir / "corpus.tsv")]
    assert cli.main([*corpus, *argv[len(audit.PROG) :]]) == 0
    out = capsysbinary.readouterr().out
    assert hashlib.sha256(out).hexdigest() == line["result_sha256"]


@pytest.mark.anyio
@pytest.mark.parametrize(("name", "arguments"), CALLS)
async def test_recording_leaves_the_wire_result_unchanged(
    name, arguments, substrate, log
):
    plain = await _call(build_server(substrate), name, arguments)
    logged = await _call(build_server(substrate, log), name, arguments)

    assert logged.structured_content == plain.structured_content
    assert logged.content == plain.content


@pytest.mark.anyio
async def test_a_failing_call_logs_its_error_and_still_fails(substrate, log):
    result = await _call(
        build_server(substrate, log), "get_page", {"doc": "SUA", "page": 9999}
    )

    assert result.is_error
    [line] = _lines(log)
    assert line["error"].startswith("UnknownPageError")
    assert "result_sha256" not in line
    assert shlex.split(line["invocation"])[-3:] == ["get-page", "SUA", "9999"]


@pytest.mark.anyio
async def test_calls_append_in_order(substrate, log):
    server = build_server(substrate, log)
    for name, arguments in CALLS:
        await _call(server, name, arguments)

    ops = [shlex.split(line["invocation"])[len(audit.PROG)] for line in _lines(log)]
    assert ops == ["search", "get", "get-by-cite", "get-by-cite", "get-page"]


@pytest.mark.parametrize(
    ("argv", "want"),
    [
        (audit.search_argv(["-anch", "puert"]), {"terms": ["-anch", "puert"]}),
        (audit.get_argv(["-x"]), {"ids": ["-x"]}),
        (audit.get_by_cite_argv("-a)", "D128"), {"cite": "-a)", "doc": "D128"}),
        (audit.get_by_cite_argv("", None), {"cite": "", "doc": None}),
        (audit.get_page_argv("SUA", -1), {"doc": "SUA", "page": -1}),
    ],
)
def test_an_argument_that_looks_like_an_option_still_parses_as_itself(argv, want):
    args = vars(cli._parser().parse_args(shlex.split(shlex.join(argv))))
    assert {k: args[k] for k in want} == want


def test_the_substrate_digest_covers_the_provenance_sidecar(tmp_path, fixture_dir):
    for name in ("corpus.tsv", "corpus.provenance.tsv"):
        (tmp_path / name).write_bytes((fixture_dir / name).read_bytes())
    before = audit.substrate_sha256(tmp_path / "corpus.tsv")

    with (tmp_path / "corpus.provenance.tsv").open("a") as fh:
        fh.write("X\t1\t1\tnative\n")

    assert audit.substrate_sha256(tmp_path / "corpus.tsv") != before
