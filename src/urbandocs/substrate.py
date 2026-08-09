"""Load `corpus.tsv` into memory: the substrate every engine operation runs over.

Reads the file once, at process start (#56, #58) -- a rebuild is a restart, not
a hot reload -- and builds the `by_id` index, the `parent_id` adjacency
(`children`) that a children lookup needs, the `by_cite` index `get_by_cite`
(#61) resolves through, and the `by_page` index `get_page` (#62) resolves
through, plus `ancestor_chain`, the walk `search` and `get` (#56, #58, #60)
both climb `by_id` for; every index is built here, once, so `load_substrate`
stays the single place `corpus.tsv` is read. 2,455 records / 1.3 MB today;
loading is cheap.

Also reads the `corpus.provenance.tsv` sidecar, for `doc_pages` -- each doc's
true page count, from its ranges' `page_to` (they cover 1..n_pages, #56). This
is `get_page`'s only way to tell "no records on this page" from "no such page":
`records` alone stops at the last page that happens to carry one.

Never `csv.reader` (#33, #56): the substrate is plain TSV with no quoting, and
the default dialect silently merges fields on a record that contains a `"` --
29 of them in the current rebuild. Split on tab, by hand.

Startup is fail-loud (#38, #56): a missing file, a mismatched header or a wrong
column count is a refusal to load, never a short corpus served as though it
were a corpus with no hits.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from urbandocs import paths
from urbandocs.ingest import COLUMNS, Row

if TYPE_CHECKING:
    from pathlib import Path


class SubstrateError(RuntimeError):
    """The substrate refused to load.

    Raised rather than returning a partial or empty `Substrate` -- a caller that
    catches this and serves anyway is a choice made in the open, not a corpus
    silently missing rows (#38, #58).
    """


@dataclass(frozen=True)
class Substrate:
    """The corpus in memory, plus the indices `search` and the read operations
    need.

    `records` keeps file order -- the reading order `ingest` derived from
    `prov.bbox` (#8) -- so anything that needs a deterministic tie-break (the
    sweep's ranking, a section's matched-children order) can use position in
    this list rather than inventing its own.
    """

    records: list[Row]
    by_id: dict[str, Row]
    #: parent_id -> ids of its direct children, in file order.
    children: dict[str, list[str]]
    #: printed cite -> ids of every record that prints it, in file order. A
    #: record with an empty `cite` is not keyed here at all -- unreachable by
    #: `get_by_cite`, which is a fact about the source, not an error (#4, #61).
    by_cite: dict[str, list[str]]
    #: (doc, page) -> ids of every record on that page, in file order -- bbox
    #: reading order, since that is what `ingest` sorts `records` into (#8).
    by_page: dict[tuple[str, int], list[str]]
    #: doc -> last page the provenance sidecar's ranges cover, i.e. the
    #: document's true page count -- `get_page`'s bound for "outside the
    #: document" (#62).
    doc_pages: dict[str, int]


def ancestor_chain(record_id: str, substrate: Substrate) -> list[str]:
    """Root-first ancestor text, the record itself excluded.

    Shared by `search`'s section-line ancestors and `get`'s per-record
    ancestors (#58, #60) -- one walk, because a bugfix to the cycle-guard
    belongs in one place, not two. `seen` guards a cycle the same way
    `check_structure.py`'s invariant 7 does elsewhere -- the loader does not
    itself forbid one, so a walk that trusted the chain to terminate could spin
    forever on a corrupt substrate.
    """
    chain: list[str] = []
    seen: set[str] = set()
    cur = substrate.by_id.get(record_id)
    while cur is not None and cur["parent_id"] and cur["parent_id"] not in seen:
        seen.add(cur["parent_id"])
        cur = substrate.by_id.get(cur["parent_id"])
        if cur is None:
            break
        chain.append(cur["text"])
    chain.reverse()
    return chain


def _read_tsv_rows(path: Path, columns: list[str]) -> list[list[str]]:
    """Split every data line on tab; validate header and field count.

    No quoting, no escaping, on either side -- this is the write side of
    `ingest.write_tsv`'s contract (#33), so a plain `str.split("\\t")` is the
    correct reader, not a simplification of one.
    """
    if not path.is_file():
        raise SubstrateError(f"missing substrate: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise SubstrateError(f"empty substrate, not even a header: {path}")

    header = lines[0].split("\t")
    if header != columns:
        raise SubstrateError(f"header mismatch in {path}: got {header}, want {columns}")

    rows: list[list[str]] = []
    for lineno, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != len(columns):
            raise SubstrateError(
                f"{path} line {lineno}: {len(fields)} fields, want {len(columns)}"
            )
        rows.append(fields)
    return rows


#: `corpus.provenance.tsv`'s columns, the write side's own literal (#56,
#: `ingest.py`'s `write_tsv(prov_path, [...])` call).
PROVENANCE_COLUMNS = ["doc", "page_from", "page_to", "source"]


def _load_doc_pages(path: Path) -> dict[str, int]:
    """doc -> highest `page_to` in the provenance sidecar.

    The sidecar's ranges cover 1..n_pages per doc (#56), so the highest
    `page_to` *is* the page count -- not `max(page)` over `records`, which
    understates it on any doc whose last pages carry no record. Contiguity
    from page 1 is not reverified here; `check_structure.py`'s invariant 10
    already gates it corpus-wide (#47).
    """
    doc_pages: dict[str, int] = {}
    for lineno, fields in enumerate(_read_tsv_rows(path, PROVENANCE_COLUMNS), start=2):
        values = dict(zip(PROVENANCE_COLUMNS, fields, strict=True))
        try:
            page_to = int(values["page_to"])
        except ValueError as exc:
            raise SubstrateError(
                f"{path} line {lineno}: page_to {values['page_to']!r} is not an integer"
            ) from exc
        doc_pages[values["doc"]] = max(doc_pages.get(values["doc"], 0), page_to)
    return doc_pages


def load_substrate(
    root: str | Path | None = None, *, corpus_path: Path | None = None
) -> Substrate:
    """Load `corpus.tsv` and its `corpus.provenance.tsv` sidecar, and build the
    in-memory substrate.

    `corpus_path` overrides where the file is read from -- how a test points at
    the fixture corpus without touching `$URBANDOCS_ROOT` (#46) -- and falls
    back to `paths.corpus_tsv(root)` otherwise, the same resolution every other
    entry point in this package uses. The sidecar is always read beside it, at
    `corpus_path.with_name("corpus.provenance.tsv")`.
    """
    path = corpus_path or paths.corpus_tsv(root)
    raw_rows = _read_tsv_rows(path, COLUMNS)
    doc_pages = _load_doc_pages(path.with_name("corpus.provenance.tsv"))

    records: list[Row] = []
    by_id: dict[str, Row] = {}
    children: dict[str, list[str]] = defaultdict(list)
    by_cite: dict[str, list[str]] = defaultdict(list)
    by_page: dict[tuple[str, int], list[str]] = defaultdict(list)

    for lineno, fields in enumerate(raw_rows, start=2):
        values = dict(zip(COLUMNS, fields, strict=True))
        try:
            page = int(values["page"])
        except ValueError as exc:
            raise SubstrateError(
                f"{path} line {lineno}: page {values['page']!r} is not an integer"
            ) from exc

        record: Row = {
            "id": values["id"],
            "doc": values["doc"],
            "page": page,
            "cite": values["cite"],
            "parent_id": values["parent_id"],
            "label": values["label"],
            "text": values["text"],
            "norm": values["norm"],
        }
        if record["id"] in by_id:
            raise SubstrateError(f"{path} line {lineno}: duplicate id {record['id']!r}")

        records.append(record)
        by_id[record["id"]] = record
        if record["parent_id"]:
            children[record["parent_id"]].append(record["id"])
        if record["cite"]:
            by_cite[record["cite"]].append(record["id"])
        by_page[(record["doc"], record["page"])].append(record["id"])

    return Substrate(
        records=records,
        by_id=by_id,
        children=dict(children),
        by_cite=dict(by_cite),
        by_page=dict(by_page),
        doc_pages=doc_pages,
    )
