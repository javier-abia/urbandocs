# urbandocs

[![CI](https://github.com/javier-abia/urbandocs/actions/workflows/ci.yml/badge.svg)](https://github.com/javier-abia/urbandocs/actions/workflows/ci.yml)

**Source-traceable retrieval over construction-permit normativa, exposed to AI agents through MCP.**

When a technical architect reviews an *expediente* (a construction-permit
file), relevant provisions can be spread across municipal planning rules,
regional requirements, and national building codes. Finding a passage is only
part of the task: its conditions, surrounding structure, and source location
matter too.

urbandocs turns extracted documents into a searchable, structured corpus. An
agent can find relevant sections, read provisions with their context, follow
printed cites, and return citations a person can verify against the source PDF.
The engine retrieves evidence; the architect decides how it applies.

## Architecture

```text
PDF documents
    │  Docling + selective OCR (separate toolchain)
    ▼
Committed extraction JSON
    │  Python ingestion: repair, normalize, preserve hierarchy
    ▼
corpus.tsv + provenance sidecar
    │  Load and validate at startup
    ▼
Retrieval functions → MCP server → Calling agent → Architect verifies citations
```

The substrate is a flat TSV table with one record per addressable unit:
a provision, heading, table, or figure position. Records carry an ID, printed
cite, parent ID, PDF page, extracted text, and normalized search text.

Search uses literal word-prefix matching over normalized text and ranks
sections by the number of distinct search terms matched. It returns sections
matching at least two terms, without a rank-based top-N cutoff. Search results
contain addresses; legal text is fetched separately when the agent reads a
result. The retrieval engine requires neither embeddings nor model API calls.

The committed inputs cover six documents: `DB-SI`, `DccSUA`, `PGOM`,
`DOG_2025`, `dog-habitabilidad`, and `ley-suelo-galicia`.

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/) and Python 3.14 or later.
Run commands from the repository root. `uv` can provision the required Python
interpreter.

```sh
git clone https://github.com/javier-abia/urbandocs.git
cd urbandocs
uv sync --locked

# Build from committed extraction JSON; no PDF conversion needed.
uv run -m urbandocs.ingest
uv run -m urbandocs.check_structure
uv run -m urbandocs.check_corpus

# Start the MCP server.
uv run -m urbandocs.server
```

Connect an MCP client supporting Streamable HTTP to
`http://127.0.0.1:8848/mcp`. The server binds to loopback and has DNS-rebinding
protection. Authentication for shared access belongs at the gateway; the
[deployment runbook](docs/ops/deploy-runbook.md) describes the LiteLLM setup.

### MCP tools

| Tool | Purpose |
| --- | --- |
| `search(terms)` | Rank matching sections and return their addresses and matched record IDs. |
| `get(ids)` | Read records with their ancestor headings and direct children. |
| `get_by_cite(cite, doc=None)` | Resolve a printed cite to all candidate addresses, optionally within one document. |
| `get_page(doc, page)` | Inspect every record on one PDF page in reading order. |

For a question about door width, an agent might start with
`search(terms=["anch", "puert"])`, then pass selected result IDs to `get`.
If a provision points to a table, `get_by_cite` finds candidate addresses and
`get` reads the selected one. `get_page` supplies nearby context when the
hierarchy alone is insufficient.

Use at least two search terms, with each necessary content word submitted
separately as a stem of at least three characters. A single-term search returns
no sections. The full calling contract is in the
[MCP tool descriptions](src/urbandocs/server.py).

## Quality and evaluation

Run the four development gates from the repository root:

```sh
uv run ruff check
uv run ruff format --check
uv run ty check
uv run pytest
```

Install commit hooks with `uv run pre-commit install`. GitHub Actions runs
pre-commit, type checking, and tests, plus a separate corpus job that rebuilds
twice, compares both outputs, and checks structural and content invariants.

The [evaluation harness](evals/README.md) runs a model through the real MCP
toolset against gold questions and answers. A separate model grades answers
and required citations; Langfuse records experiments, traces, latency, token
usage, and tool-call counts. It has its own dependencies and requires model,
gateway, and Langfuse configuration. Local retrieval and unit tests need no
model credentials.

## Design decisions and limits

- **Citations guarantee a location.** OCR and extraction can alter text or lose
  symbols. Returned text must be checked against the source PDF when fidelity
  matters.
- **Printed cites can be ambiguous.** A cite such as `1.2` may occur more than
  once. Resolution returns every candidate rather than choosing silently.
- **Search is lexical.** Term selection and synonym coverage affect results.
  Sweeping the corpus does not establish that every governing provision was found.
- **The corpus is a snapshot.** It covers committed inputs and does not
  automatically establish that they are the latest applicable normativa.
- **Evidence needs professional interpretation.** The engine does not decide
  compliance or distinguish all non-binding commentary from normative text.

Measured investigations and tradeoffs are recorded in
[research notes](docs/research/), including
[extraction fidelity](docs/research/tuned-extraction-fidelity.md),
[citation guarantees](docs/research/citation-guarantee.md), and
[search cutoff experiments](docs/research/search-cap-benchmark.md).

## Repository guide

| Path | Contents |
| --- | --- |
| [`src/urbandocs/`](src/urbandocs/) | Ingestion, corpus validation, retrieval, and MCP transport. |
| [`tests/`](tests/) | Unit tests and a committed fixture corpus. |
| [`documentos/`](documentos/) | Committed document extraction artifacts. |
| `corpus/` | Generated retrieval substrate; ignored by Git. |
| [`tools/docling-convert/`](tools/docling-convert/README.md) | PDF conversion and OCR with an independent toolchain. |
| [`evals/`](evals/README.md) | Agent evaluation and Langfuse experiment tracking. |
| [`docs/research/`](docs/research/) | Investigations supporting engineering decisions. |
| [`CONTEXT.md`](CONTEXT.md) | Domain vocabulary and citation contract. |

To extend the corpus, see [Adding a document](docs/agents/adding-a-document.md).
Contributor conventions and toolchain details are in [AGENTS.md](AGENTS.md).

## License

See [LICENSE](LICENSE) for the GNU General Public License v3 terms.
