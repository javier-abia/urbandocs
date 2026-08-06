#!/usr/bin/env python3
"""Structural invariants over `corpus/corpus.tsv` (#47, map #45).

Every property here held exactly across #41's document swap -- an entire
document replaced, 4924 records down to 2455, every count moving -- so unlike
`check_corpus.py`'s hand-measured bands (which are legitimately re-measured on
the next decree swap), nothing here is ever expected to change. A failure is a
regression in `ingest.py`, not a stale assertion.

No count, bound, or label allowlist is asserted (#47, decision 1): an empty
corpus or a dropped decree already fails `check_corpus.py`, and a closed label
vocabulary doesn't survive a rebuild (`figure_labels` moved 515 -> 10 across
the swap without ingest.py itself gaining a defect). The one roster check here
is structural rather than numeric: it holds for any legitimate corpus and
catches a real hole a count floor would not -- dropping an entire document
passes today's `check_corpus.py` (#47).

Reads `corpus.tsv` and its `corpus.provenance.tsv` sidecar directly, not
`ingest.py --stats`: `--stats` only emits the measurements #47 ruled out of
this gate. Determinism (#47's invariant 13) is not checked here -- it needs
two independent rebuilds to compare, which is the CI job's shape, not this
script's; see the corpus-invariants job.

Usage:
    uv run -m urbandocs.check_structure
    uv run -m urbandocs.check_structure --corpus /tmp/corpus.tsv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from urbandocs import paths
from urbandocs.ingest import COLUMNS, DOCS, normalize

if TYPE_CHECKING:
    from collections.abc import Sequence

Row = dict[str, str]
ProvRow = dict[str, str]


def check(rows: list[Row], prov: list[ProvRow]) -> list[str]:
    """Run all structural invariants plus the doc-roster check; return failures."""
    failures: list[str] = []

    def fail(name: str, detail: str) -> None:
        failures.append(name)
        print(f"  [FAIL] {name}: {detail}")

    def ok(name: str) -> None:
        print(f"  [PASS] {name}")

    by_id: dict[str, Row] = {r["id"]: r for r in rows}

    # 1/2. header and field-count are enforced at read time in `main()`, before
    # `check()` ever runs: a short/long row raises inside csv.DictReader.

    # 3. `id` unique corpus-wide
    ids = [r["id"] for r in rows]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        fail("unique ids", f"{len(dupes)} duplicate ids: {sorted(dupes)[:5]}")
    else:
        ok("unique ids")

    # 4. every non-empty parent_id resolves to a real id
    unresolved = [
        r["id"] for r in rows if r["parent_id"] and r["parent_id"] not in by_id
    ]
    if unresolved:
        fail("parent resolves", f"{len(unresolved)} unresolved: {unresolved[:5]}")
    else:
        ok("parent resolves")

    # 5. a record's parent is in the same doc
    cross_doc = [
        r["id"]
        for r in rows
        if r["parent_id"]
        and r["parent_id"] in by_id
        and by_id[r["parent_id"]]["doc"] != r["doc"]
    ]
    if cross_doc:
        fail("parent same doc", f"{len(cross_doc)} cross-doc: {cross_doc[:5]}")
    else:
        ok("parent same doc")

    # 6. a parent appears before its child in file order
    order = {r["id"]: i for i, r in enumerate(rows)}
    out_of_order = [
        r["id"]
        for r in rows
        if r["parent_id"]
        and r["parent_id"] in order
        and order[r["parent_id"]] >= order[r["id"]]
    ]
    if out_of_order:
        fail("parent before child", f"{len(out_of_order)}: {out_of_order[:5]}")
    else:
        ok("parent before child")

    # 7. no record is its own ancestor (no cycles)
    cyclic: list[str] = []
    for r in rows:
        cur, seen = r, set()
        while cur["parent_id"] and cur["parent_id"] in by_id:
            if cur["parent_id"] in seen or cur["parent_id"] == r["id"]:
                cyclic.append(r["id"])
                break
            seen.add(cur["parent_id"])
            cur = by_id[cur["parent_id"]]
    if cyclic:
        fail("no ancestor cycles", f"{len(cyclic)}: {cyclic[:5]}")
    else:
        ok("no ancestor cycles")

    # 8. norm == normalize(text) for every row
    mismatched = [r["id"] for r in rows if r["norm"] != normalize(r["text"])]
    if mismatched:
        fail("norm derivable from text", f"{len(mismatched)}: {mismatched[:5]}")
    else:
        ok("norm derivable from text")

    # 9. every record's (doc, page) falls inside a provenance range
    ranges: dict[str, list[tuple[int, int]]] = {}
    for p in prov:
        ranges.setdefault(p["doc"], []).append((int(p["page_from"]), int(p["page_to"])))
    outside = [
        r["id"]
        for r in rows
        if not any(a <= int(r["page"]) <= b for a, b in ranges.get(r["doc"], []))
    ]
    if outside:
        fail("page inside provenance", f"{len(outside)}: {outside[:5]}")
    else:
        ok("page inside provenance")

    # 10. provenance ranges per doc are contiguous and start at page 1
    disjoint: list[str] = []
    for doc, spans in ranges.items():
        spans = sorted(spans)
        if spans[0][0] != 1:
            disjoint.append(f"{doc} starts at {spans[0][0]}")
            continue
        cursor = 1
        for a, b in spans:
            if a != cursor:
                disjoint.append(f"{doc} gap/overlap at {a} (expected {cursor})")
                break
            cursor = b + 1
    if disjoint:
        fail("provenance contiguous", "; ".join(disjoint[:5]))
    else:
        ok("provenance contiguous")

    # 11. children stop at the section boundary -- cheaper equivalent form: no
    # child's page precedes its parent's page.
    boundary_crossings = [
        r["id"]
        for r in rows
        if r["parent_id"]
        and r["parent_id"] in by_id
        and int(r["page"]) < int(by_id[r["parent_id"]]["page"])
    ]
    if boundary_crossings:
        fail(
            "no boundary crossings",
            f"{len(boundary_crossings)}: {boundary_crossings[:5]}",
        )
    else:
        ok("no boundary crossings")

    # 12. text is empty iff the record is a picture
    mismatched_pictures = [
        r["id"] for r in rows if (r["text"] == "") != (r["label"] == "picture")
    ]
    if mismatched_pictures:
        fail(
            "text empty iff picture",
            f"{len(mismatched_pictures)}: {mismatched_pictures[:5]}",
        )
    else:
        ok("text empty iff picture")

    # roster: the set of `doc` values equals `ingest.DOCS` (#47, decision 2)
    present = {r["doc"] for r in rows}
    if present != set(DOCS):
        fail("doc roster", f"got {sorted(present)}, want {sorted(DOCS)}")
    else:
        ok("doc roster")

    return failures


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="uv run -m urbandocs.check_structure",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repo root; defaults to $URBANDOCS_ROOT or the enclosing repo",
    )
    ap.add_argument("--corpus", type=Path, default=None)
    args = ap.parse_args(argv)
    corpus = args.corpus or paths.corpus_tsv(args.root)

    if not corpus.exists():
        sys.exit(f"missing {corpus}; run `uv run -m urbandocs.ingest` first")

    with corpus.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames != COLUMNS:
            sys.exit(f"header mismatch: got {reader.fieldnames}, want {COLUMNS}")
        rows: list[Row] = []
        for i, row in enumerate(reader, start=2):
            if None in row or None in row.values():
                sys.exit(f"malformed row (wrong field count) at line {i}: {row}")
            rows.append(row)

    prov_path = corpus.with_name("corpus.provenance.tsv")
    if not prov_path.exists():
        sys.exit(f"missing {prov_path}")
    prov: list[ProvRow] = list(csv.DictReader(prov_path.open(), delimiter="\t"))

    print(f"{len(rows)} records, {len(prov)} provenance ranges")
    failures = check(rows, prov)

    print()
    if failures:
        print(f"FAIL: {', '.join(failures)}")
        return 1
    print("PASS: all structural invariants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
