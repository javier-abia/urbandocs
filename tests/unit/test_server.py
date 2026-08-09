"""`get` and `get_by_cite` on the wire: the one place this suite crosses the
MCP transport (#60, #61).

Everything else about these operations is a plain-function test in
`test_read.py` and `test_resolve.py` -- `build_server` holds no retrieval
logic of its own (#59), so this file's whole job is to prove the wire agrees
with the function: each tool is listed under its name with a non-empty
description, and a call returns the same result the underlying function would.

The description-content tests below are #64's: MCP cannot compel the sweep
->rank->get->expand loop or the evidence-only contract, so those instructions
only reach the calling agent if the text carries them and stays intact
through the gateway (#43, checked at deploy by #53) -- these tests are the
in-repo half of that guarantee.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest
from mcp.client._memory import InMemoryTransport
from mcp.client.session import ClientSession

from urbandocs.read import get, get_page
from urbandocs.resolve import get_by_cite
from urbandocs.server import (
    GET_BY_CITE_DESCRIPTION,
    GET_DESCRIPTION,
    GET_PAGE_DESCRIPTION,
    SEARCH_DESCRIPTION,
    build_server,
)
from urbandocs.substrate import load_substrate


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def substrate(fixture_dir):
    return load_substrate(corpus_path=fixture_dir / "corpus.tsv")


@pytest.mark.anyio
async def test_search_is_listed_with_a_non_empty_description(substrate):
    server = build_server(substrate)
    async with (
        InMemoryTransport(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        tool = next(t for t in tools.tools if t.name == "search")
        assert tool.description and tool.description.strip()


@pytest.mark.anyio
async def test_all_four_tools_are_listed_with_non_empty_descriptions(substrate):
    """The corpus-wide sweep is structural, but everything past it -- rank,
    get, expand, the single refine round, the no-ruling contract -- is
    instructed through these descriptions (#64). A tool listed with an empty
    or missing one silently drops that instruction."""
    server = build_server(substrate)
    async with (
        InMemoryTransport(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()

    by_name = {t.name: t.description for t in tools.tools}
    assert set(by_name) == {"search", "get", "get_by_cite", "get_page"}
    for name, description in by_name.items():
        assert description and description.strip(), name


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


@pytest.mark.anyio
async def test_get_by_cite_is_listed_with_a_non_empty_description(substrate):
    server = build_server(substrate)
    async with (
        InMemoryTransport(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        tool = next(t for t in tools.tools if t.name == "get_by_cite")
        assert tool.description and tool.description.strip()


@pytest.mark.anyio
async def test_get_by_cite_over_the_wire_returns_the_same_candidates_as_the_function(
    substrate,
):
    want = get_by_cite("a)", substrate)

    server = build_server(substrate)
    async with (
        InMemoryTransport(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("get_by_cite", {"cite": "a)"})

    assert result.structured_content == {"result": [asdict(c) for c in want]}


@pytest.mark.anyio
async def test_get_by_cite_over_the_wire_honours_the_doc_filter(substrate):
    want = get_by_cite("B.1", substrate, doc="D128")

    server = build_server(substrate)
    async with (
        InMemoryTransport(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("get_by_cite", {"cite": "B.1", "doc": "D128"})

    assert result.structured_content == {"result": [asdict(c) for c in want]}


@pytest.mark.anyio
async def test_get_page_is_listed_with_a_non_empty_description(substrate):
    server = build_server(substrate)
    async with (
        InMemoryTransport(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        tool = next(t for t in tools.tools if t.name == "get_page")
        assert tool.description and tool.description.strip()


@pytest.mark.anyio
async def test_get_page_over_the_wire_returns_the_same_records_as_the_function(
    substrate,
):
    want = get_page("SUA", 76, substrate)

    server = build_server(substrate)
    async with (
        InMemoryTransport(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("get_page", {"doc": "SUA", "page": 76})

    assert result.structured_content == {"result": [asdict(r) for r in want]}


@pytest.mark.anyio
async def test_get_page_out_of_range_is_a_tool_error_not_an_empty_result(substrate):
    """`UnknownPageError` (#62) must surface as a reported failure over the
    wire, not the empty list a page with no records returns."""
    server = build_server(substrate)
    async with (
        InMemoryTransport(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("get_page", {"doc": "SUA", "page": 9999})

    assert result.is_error


# --------------------------------------------------------------------------- #
# #64: the instructed loop only reaches the calling agent if this text does.
# Plain string checks on the module constants, not over the wire -- these
# fail the moment a phrase is trimmed or dropped, which is the point.
# --------------------------------------------------------------------------- #


def test_search_description_states_the_term_floor_and_stems():
    assert "own term" in SEARCH_DESCRIPTION
    assert "stem" in SEARCH_DESCRIPTION
    assert '"anch"' in SEARCH_DESCRIPTION


def test_search_description_states_the_loop_order_and_single_refine_round():
    for step in ("sweep", "rank", "`get`", "expand"):
        assert step in SEARCH_DESCRIPTION
    assert "one refine round" in SEARCH_DESCRIPTION


def test_descriptions_state_the_evidence_only_contract():
    for phrase in ("no synthesis", "no ruling", "no verdict"):
        assert phrase in SEARCH_DESCRIPTION
    assert "not a ruling" in GET_DESCRIPTION


def test_get_by_cite_description_states_it_is_a_resolver_not_a_getter():
    assert "Returns addresses only" in GET_BY_CITE_DESCRIPTION
    assert "never legal text" in GET_BY_CITE_DESCRIPTION


def test_get_page_description_states_it_is_off_loop():
    assert "Off-loop" in GET_PAGE_DESCRIPTION
