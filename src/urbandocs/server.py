"""The MCP transport adapter: `search`, `get`, `get_by_cite` and `get_page`
exposed over streamable HTTP (#59, #60, #61, #62).

Holds no retrieval logic of its own -- `urbandocs.search.search`,
`urbandocs.read.get`, `urbandocs.resolve.get_by_cite` and
`urbandocs.read.get_page` are already complete (#56); this module's job is the
wire. Loads the substrate once at startup, fail-loud (#38, #56), registers
each operation as an MCP tool, and binds loopback-only with DNS-rebinding
protection, since the engine authenticates nobody -- identity and attribution
are the gateway's job (#43).

    uv run -m urbandocs.server

Fixed by #43: streamable HTTP, `127.0.0.1:8848`, path `/mcp`. Not the LAN --
LiteLLM on the same box is the only caller.
"""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from urbandocs.read import GetResponse, PageRecord
from urbandocs.read import get as _get
from urbandocs.read import get_page as _get_page
from urbandocs.resolve import CiteCandidate
from urbandocs.resolve import get_by_cite as _get_by_cite
from urbandocs.search import RankedSection
from urbandocs.search import search as _search
from urbandocs.substrate import Substrate, load_substrate

HOST = "127.0.0.1"
PORT = 8848
STREAMABLE_HTTP_PATH = "/mcp"

# The term floor, shipped as a tool description since MCP cannot compel a
# call sequence (#59): this text is what stops a sweep from silently missing
# a term and returning a clean, wrong empty list. Terms are submitted as
# stems, not full words -- "anch" reaches both "ancho" and "anchura" (#9).
# Also carries the loop order and the evidence contract (#64): MCP cannot
# enforce either, so the calling agent has to be told sweep -> rank -> get ->
# expand with one refine round, and that this engine never rules or verifies
# completeness on its behalf.
#
# Also warns off corpus-wide terms: scoring counts distinct slots matched,
# with no per-term weighting (search.py), so a term the whole corpus shares
# inflates boilerplate sections for free. "Vigo" is the worst case measured
# so far -- it also collides as a stem with "vigor" ("entrada en vigor"),
# outranking the actually relevant section in a real query.
SEARCH_DESCRIPTION = (
    "Sweep the whole normativa corpus for the given terms and return the "
    "complete ranked list of matching sections, never truncated. Submit "
    "every content word of the question as its own term -- entity and "
    'attribute searched separately, e.g. "anchura" and "puerta", never '
    '"anchura de puerta" as one term -- and submit each term as a stem '
    'rather than a full word: "anch" reaches both "ancho" and "anchura"; a '
    "full word reaches only the documents that happen to print that exact "
    "form. Every term counts equally toward a section's score, so a term "
    "the whole corpus shares -- the municipality's own name chief among "
    "them, in a corpus that is that municipality's normativa -- matches "
    "boilerplate as readily as the target and only dilutes the ranking; "
    "leave it out. Because matching is stem-prefix, such a term can also "
    'collide with an unrelated common word ("Vigo" reaches "vigor" too), '
    "inflating the wrong section's score rather than the right one's. A "
    "term matching nothing contributes nothing to the result; it is "
    "not an error. Synonyms may be added to a slot; terms already in the "
    "sweep may never be dropped on a refine round. Each returned section "
    "carries an address only -- "
    "document, PDF page, ancestor heading chain, section id, and "
    "matched child ids -- never the provision's legal text; call `get` on "
    "the ids that matter to read it. The ancestor chain is not repeated in "
    "full on every section: the result carries one `ancestors` pool of "
    "unique heading strings, and each section's `ancestor_ids` are "
    "root-first indices into it -- look each one up to read the section's "
    "full chain. This is the first step of a fixed loop: "
    "sweep here, rank arrives pre-sorted, `get` the sections that matter, "
    "then expand by following at most one in-corpus pointer via `get_by_cite` "
    "and search again if it opens a new question -- one refine round, not a "
    "recursion. The engine returns evidence, never an answer: no synthesis "
    "across sections, no ruling on which provision governs, and no verdict "
    "that a sweep was complete -- every result has to be opened and verified "
    "at its cited source."
)

# Names the ancestor chain and children explicitly, not just "context" (#60):
# a batch that comes back short, or a rule returned without its qualifier or
# obligation, are the two failure shapes this must not produce.
GET_DESCRIPTION = (
    "Return verbatim legal text for one or more section or record ids from "
    "`search`. Each result carries the record's own text, its full ancestor "
    "heading chain up to the root, and its direct children -- never "
    "grandchildren, never a sibling's subtree -- because a qualifier often "
    "lives in the parent and the obligation it introduces often lives in the "
    "children. Batch several ids in one call rather than calling once per id. "
    "An id not found in the corpus is reported by itself and does not fail "
    "the rest of the batch; a large batch is never truncated or refused. This "
    "is the loop's `get` step, called on what `search` ranked -- the text it "
    "returns is evidence to read and verify, not a ruling and not a "
    "paraphrase to repeat as an answer."
)

# States "a resolver, never a getter" up front (#61) -- the name reads like it
# returns the cited thing, and most cites in this corpus are ambiguous enough
# that a single record would misrepresent the source.
GET_BY_CITE_DESCRIPTION = (
    'Resolve a printed cite -- "1.2", "a)", "Anejo B", "Artículo 14" -- '
    "exactly as it appears on the page, to every record that prints it. "
    "Returns addresses only -- id, document, PDF page, ancestor heading chain "
    "-- never legal text, because the same cite is often printed by several "
    "records and this tool returns all of them rather than guessing which one "
    "was meant; call `get` on whichever candidate id is the right one. A cite "
    "that matches nothing in the corpus returns an empty list, not an error. "
    "`doc` optionally filters the candidates to one document -- it helps when "
    "the collision happens to cross documents, but most ambiguity is inside a "
    "single document and survives the filter. This is the loop's `expand` "
    "step: use it to follow a pointer found in a `get` result (e.g. "
    '"según la tabla 1.2") one hop, not to repeat the sweep.'
)

# States the no-range rule and why up front (#62): the cost of a range call is
# invisible at the call site and unbounded once the corpus grows, so a long
# article must be walked one page at a time rather than pulled in one call.
GET_PAGE_DESCRIPTION = (
    "Return every record on one PDF page, in reading order, each carrying its "
    "id so anything spotted is immediately gettable via `get`. Off-loop: use it "
    "when the ancestor chain does not reach context that sits beside a "
    "provision on the page instead of above or below it. There is no page-range "
    "parameter -- a provision spanning several pages is walked one page at a "
    "time, on purpose, because a range call's token cost is invisible at the "
    "call site and can be enormous (one article here spans 37 pages). A page "
    "with no records returns an empty list; a page number outside the document "
    "is an error, not a silent empty result."
)


@dataclass(frozen=True)
class WireSection:
    """One `RankedSection`, its ancestor chain replaced by indices into the
    sibling `SearchResponse.ancestors` pool (#87). Everything else is
    unchanged from `RankedSection` -- this is a wire-only re-encoding, not a
    change to what `search` ranks or returns.
    """

    score: int
    doc: str
    page: int
    #: Root-first, same order `RankedSection.ancestors` held the strings in --
    #: now positions in `SearchResponse.ancestors` instead of the text itself.
    ancestor_ids: list[int]
    section_id: str
    matched_children: list[str]


@dataclass(frozen=True)
class SearchResponse:
    """`search`'s wire shape: ancestor heading strings interned once each,
    referenced by index from every section that shares them (#87) -- sections
    under one heading, or under one another's, no longer each carry their own
    copy of it.
    """

    #: Unique ancestor strings, first-appearance order across `sections`.
    ancestors: list[str]
    sections: list[WireSection]


def _dedupe_ancestors(ranked: list[RankedSection]) -> SearchResponse:
    """Intern `RankedSection.ancestors` strings into a shared pool.

    One entry per distinct heading text, however many sections' chains it
    appears in or at what depth -- a pool over strings rather than over whole
    chains, so two sections whose chains overlap only partway (share a
    grandparent but not a parent) still dedupe the shared part.
    """
    pool: dict[str, int] = {}
    sections = []
    for r in ranked:
        ids = []
        for heading in r.ancestors:
            idx = pool.setdefault(heading, len(pool))
            ids.append(idx)
        sections.append(
            WireSection(
                score=r.score,
                doc=r.doc,
                page=r.page,
                ancestor_ids=ids,
                section_id=r.section_id,
                matched_children=r.matched_children,
            )
        )
    return SearchResponse(ancestors=list(pool), sections=sections)


def build_server(substrate: Substrate) -> MCPServer:
    """Register `search` against an already-loaded substrate.

    Split from `main` so a test can build a server over the fixture corpus
    without going through `load_substrate`'s real-file resolution.
    """
    server = MCPServer("normativa")

    @server.tool(description=SEARCH_DESCRIPTION)
    def search(terms: list[str]) -> SearchResponse:
        return _dedupe_ancestors(_search(terms, substrate))

    @server.tool(description=GET_DESCRIPTION)
    def get(ids: list[str]) -> GetResponse:
        return _get(ids, substrate)

    @server.tool(description=GET_BY_CITE_DESCRIPTION)
    def get_by_cite(cite: str, doc: str | None = None) -> list[CiteCandidate]:
        return _get_by_cite(cite, substrate, doc)

    @server.tool(description=GET_PAGE_DESCRIPTION)
    def get_page(doc: str, page: int) -> list[PageRecord]:
        return _get_page(doc, page, substrate)

    return server


def main() -> None:
    """Load the substrate and serve `search` over streamable HTTP.

    `load_substrate()` raises `SubstrateError` on a malformed corpus, and
    nothing here catches it: startup must fail loudly rather than serve as
    though the corpus had no hits (#56, #59).
    """
    substrate = load_substrate()
    server = build_server(substrate)
    server.run(
        transport="streamable-http",
        host=HOST,
        port=PORT,
        streamable_http_path=STREAMABLE_HTTP_PATH,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[f"{HOST}:{PORT}"],
        ),
    )


if __name__ == "__main__":
    main()
