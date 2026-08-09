"""The MCP transport adapter: `search` and `get` exposed over streamable HTTP
(#59, #60).

Holds no retrieval logic of its own -- `urbandocs.search.search` and
`urbandocs.read.get` are already complete without it (#56), same as
`urbandocs.substrate.load_substrate`: this module's whole job is the wire. It
loads the substrate once at startup, fail-loud (#38, #56's own contract),
registers each operation as an MCP tool, and binds loopback-only with
DNS-rebinding protection as the engine's only control (#43) -- the engine
authenticates nobody; identity and attribution are the gateway's virtual keys.

    uv run -m urbandocs.server

Fixed by #43, not re-derived here: streamable HTTP, `127.0.0.1:8848`, path
`/mcp`. Not the LAN, not `0.0.0.0` -- LiteLLM on the same box is the only
caller. `enable_dns_rebinding_protection` stays on with `allowed_hosts` set to
that same loopback host:port and nothing else, because `Origin` validation is
the engine's only remaining control with no auth of its own.
"""

from __future__ import annotations

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from urbandocs.read import GetResponse
from urbandocs.read import get as _get
from urbandocs.search import RankedSection
from urbandocs.search import search as _search
from urbandocs.substrate import Substrate, load_substrate

HOST = "127.0.0.1"
PORT = 8848
STREAMABLE_HTTP_PATH = "/mcp"

# The term floor, shipped as a tool description rather than left as
# documentation (#59): MCP cannot compel a call sequence, so this sentence is
# what stands between the calling agent and #28's worst failure shape -- a
# sweep that silently missed a term and returned a clean, wrong empty list.
# Every content word its own slot, entity and attribute separately, submitted
# as a stem rather than a full word: "anch" reaches both "ancho" and
# "anchura"; "instal" reaches both documents' vocabulary where either full
# word alone reaches only one (#9).
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

# Batching and the two failure shapes this operation must never produce,
# stated up front rather than left implicit (#60): a batch that came back
# short of what was asked, and a rule returned without the context that makes
# it correct -- so the description names both the ancestor chain and the
# children explicitly, not just "context".
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

    return server


def main() -> None:
    """Load the substrate and serve `search` over streamable HTTP.

    `load_substrate()` raises `SubstrateError` on anything short of a
    well-formed corpus -- missing file, bad header, bad column count (#56) --
    and nothing here catches it: a malformed substrate must refuse to start,
    never come up serving as though it were a corpus with no hits (#59's own
    acceptance criterion).
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
