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
SEARCH_DESCRIPTION = (
    "Sweep the whole normativa corpus for the given terms and return the "
    "complete ranked list of matching sections, never truncated. Submit "
    "every content word of the question as its own term -- entity and "
    'attribute searched separately, e.g. "anchura" and "puerta", never '
    '"anchura de puerta" as one term -- and submit each term as a stem '
    'rather than a full word: "anch" reaches both "ancho" and "anchura"; a '
    "full word reaches only the documents that happen to print that exact "
    "form. A term matching nothing contributes nothing to the result; it is "
    "not an error. Each returned section carries an address only -- "
    "document, PDF page, full ancestor heading chain, section id, and "
    "matched child ids -- never the provision's legal text; call `get` on "
    "the ids that matter to read it."
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
    "the rest of the batch; a large batch is never truncated or refused."
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
    "single document and survives the filter."
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


def build_server(substrate: Substrate) -> MCPServer:
    """Register `search` against an already-loaded substrate.

    Split from `main` so a test can build a server over the fixture corpus
    without going through `load_substrate`'s real-file resolution.
    """
    server = MCPServer("normativa")

    @server.tool(description=SEARCH_DESCRIPTION)
    def search(terms: list[str]) -> list[RankedSection]:
        return _search(terms, substrate)

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
