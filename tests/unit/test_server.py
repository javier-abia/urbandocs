"""`get` on the wire: the one place this suite crosses the MCP transport (#60).

Everything else about `get` is a plain-function test in `test_read.py` --
`build_server` holds no retrieval logic of its own (#59), so this file's whole
job is to prove the wire agrees with the function: the tool is listed under
its name with a non-empty description, and a call returns the same records
`urbandocs.read.get` would.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest
from mcp.client._memory import InMemoryTransport
from mcp.client.session import ClientSession

from urbandocs.read import get
from urbandocs.server import build_server
from urbandocs.substrate import load_substrate


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def substrate(fixture_dir):
    return load_substrate(corpus_path=fixture_dir / "corpus.tsv")


@pytest.mark.anyio
async def test_get_is_listed_with_a_non_empty_description(substrate):
    server = build_server(substrate)
    async with (
        InMemoryTransport(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        get_tool = next(t for t in tools.tools if t.name == "get")
        assert get_tool.description and get_tool.description.strip()


@pytest.mark.anyio
async def test_get_over_the_wire_returns_the_same_records_as_the_function(substrate):
    ids = ["D128:p21:A.2.2", "SUA:p74:anejoB", "HAB:p20:art14.1.a"]
    want = get(ids, substrate)

    server = build_server(substrate)
    async with (
        InMemoryTransport(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("get", {"ids": ids})

    assert result.structured_content == {
        "records": [asdict(r) for r in want.records],
        "unknown_ids": want.unknown_ids,
    }
