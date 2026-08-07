"""Load `corpus.tsv` into memory: the substrate every engine operation runs over.

Reads the file once, at process start (#56, #58) -- a rebuild is a restart, not
a hot reload -- and builds the `by_id` index and the `parent_id` adjacency
(`children`) that a children lookup needs. `search`'s own ancestor walk climbs
`by_id` directly rather than `children`, which the future `get` (#56, #59) is
the first consumer of; both indices are built here, once, so `load_substrate`
stays the single place `corpus.tsv` is read. 2,455 records / 1.3 MB today;
loading is cheap.

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


def load_substrate(
    root: str | Path | None = None, *, corpus_path: Path | None = None
) -> Substrate:
    """Load `corpus.tsv` and build the in-memory substrate.

    `corpus_path` overrides where the file is read from -- how a test points at
    the fixture corpus without touching `$URBANDOCS_ROOT` (#46) -- and falls
    back to `paths.corpus_tsv(root)` otherwise, the same resolution every other
    entry point in this package uses.
    """
    path = corpus_path or paths.corpus_tsv(root)
    raw_rows = _read_tsv_rows(path, COLUMNS)

    records: list[Row] = []
    by_id: dict[str, Row] = {}
    children: dict[str, list[str]] = defaultdict(list)

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

    return Substrate(records=records, by_id=by_id, children=dict(children))
