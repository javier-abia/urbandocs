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
from urbandocs.search import search
from urbandocs.server import (
    GET_BY_CITE_DESCRIPTION,
    GET_DESCRIPTION,
    GET_PAGE_DESCRIPTION,
    SEARCH_DESCRIPTION,
    WireSection,
    _dedupe_ancestors,
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
    assert by_name == {
        "search": SEARCH_DESCRIPTION,
        "get": GET_DESCRIPTION,
        "get_by_cite": GET_BY_CITE_DESCRIPTION,
        "get_page": GET_PAGE_DESCRIPTION,
    }


# --------------------------------------------------------------------------- #
# search's wire shape: ancestor strings interned once, referenced by index
# (#87) -- `search` itself, and `RankedSection`, are unchanged; only what
# crosses the wire is re-encoded.
# --------------------------------------------------------------------------- #


def test_dedupe_ancestors_interns_a_chain_shared_across_sections(substrate):
    """SUA:p32:§9, §13 and §16 all sit under the same three headings (fixture
    data, not contrived) -- deduping must store that chain once and reference
    it three times, not carry three independent copies."""
    ranked = search(["condicion", "puerta"], substrate)
    response = _dedupe_ancestors(ranked)

    shared_ids = ["SUA:p32:§9", "SUA:p32:§13", "SUA:p32:§16"]
    wire_by_id = {s.section_id: s for s in response.sections}
    want = next(r.ancestors for r in ranked if r.section_id == "SUA:p32:§9")
    for section_id in shared_ids:
        wire = wire_by_id[section_id]
        assert [response.ancestors[i] for i in wire.ancestor_ids] == want

    # One pool entry per distinct heading text, not per section that uses it.
    assert response.ancestors.count("1.2 Impacto con elementos practicables") == 1
    assert len(response.ancestors) < sum(len(r.ancestors) for r in ranked)


def test_dedupe_ancestors_reconstructs_every_section_unchanged(substrate):
    """No information lost: resolving each section's `ancestor_ids` against
    the pool must reproduce exactly the `RankedSection.ancestors` it started
    from, for every section, not just the ones that share a chain."""
    ranked = search(["condicion", "puerta"], substrate)
    response = _dedupe_ancestors(ranked)

    for original, wire in zip(ranked, response.sections, strict=True):
        assert [response.ancestors[i] for i in wire.ancestor_ids] == original.ancestors
        assert wire.section_id == original.section_id
        assert wire.score == original.score
        assert wire.doc == original.doc
        assert wire.page == original.page
        assert wire.matched_children == original.matched_children


@pytest.mark.anyio
async def test_search_over_the_wire_matches_the_deduped_function_result(substrate):
    """The MCP `search` tool must return exactly what `_dedupe_ancestors`
    produces over the plain function's result -- the wire adds no logic of
    its own beyond that re-encoding."""
    want = _dedupe_ancestors(search(["condicion", "puerta"], substrate))

    server = build_server(substrate)
    async with (
        InMemoryTransport(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("search", {"terms": ["condicion", "puerta"]})

    assert result.structured_content == {
        "ancestors": want.ancestors,
        "sections": [asdict(s) for s in want.sections],
    }


def test_wire_section_carries_no_ancestors_field():
    """`WireSection` replaces `ancestors` with `ancestor_ids` outright --
    guards against a re-add that silently reintroduces the duplication #87
    removed."""
    assert "ancestors" not in set(WireSection.__dataclass_fields__)
    assert "ancestor_ids" in WireSection.__dataclass_fields__


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
    assert "Synonyms may be added" in SEARCH_DESCRIPTION
    assert "may never be dropped" in SEARCH_DESCRIPTION


def test_search_description_states_the_minimum_stem_length():
    assert "never shorter than 3 characters" in SEARCH_DESCRIPTION
    assert '"m" from "metros"' in SEARCH_DESCRIPTION


def test_search_description_excludes_bare_numbers():
    assert "Leave out bare numbers entirely" in SEARCH_DESCRIPTION
    assert '"6" reaches "6", "60", "6.1", "6º"' in SEARCH_DESCRIPTION


def test_search_description_states_terms_are_marginal_cost_only():
    assert "adding a term can only raise a section's score, never lower it" in (
        SEARCH_DESCRIPTION
    )
    assert "one term per necessary content word and stop" in SEARCH_DESCRIPTION


def test_search_description_states_the_score_floor_honestly():
    """#102: `search` no longer claims #56's unqualified "never truncated" --
    it states the score >= 2 floor and its single-term-search consequence."""
    assert "never truncated" not in SEARCH_DESCRIPTION
    assert "two or more terms" in SEARCH_DESCRIPTION
    assert "single-term search never returns anything" in SEARCH_DESCRIPTION


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
