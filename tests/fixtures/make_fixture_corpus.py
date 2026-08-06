#!/usr/bin/env python3
"""Build `tests/fixtures/corpus/` -- the committed corpus the unit tests run against.

The fixture is an **excerpt of the real corpus**, not a hand-written one (#49).
Hand-writing would have let the fixture drift into a shape ingest never emits, and
the shapes worth testing are exactly the ones nobody would think to invent: a
seven-deep ancestor chain, an id disambiguated with `~2` because the source prints
the same cite twice, a provision with an empty `cite` because its marker is not
recoverable, `§`-positional ids, a table serialized with ` ¶ ` row separators.

Selection is **whole pages** (plus the ancestor closure of everything on them), so
`get_page` has honest ground truth: for a page in `PAGES`, the fixture holds every
record the real corpus holds. Pages pulled in only as ancestors are partial; the
generated README lists them under "Partial pages".

The output is **committed and frozen**. It is not regenerated when the tests run:
the whole point is a substrate that does not move when the real corpus is rebuilt
(#41 moved every count in the corpus without changing one structural property).
Ids are kept exactly as the real corpus spells them -- rewriting them would destroy
the one thing the fixture exists to carry.

`--check` re-derives the fixture from the current docling JSON and diffs, so a
change to `ingest` that would alter these records fails loudly instead of leaving
the fixture quietly describing an ingest that no longer exists.

Usage:
    uv run python tests/fixtures/make_fixture_corpus.py
    uv run python tests/fixtures/make_fixture_corpus.py --check
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

from urbandocs import ingest, paths

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "corpus"

# Whole pages, chosen for what they carry rather than for being representative.
# Each entry names the shapes it is here for; drop a page only after checking the
# coverage assertion below still passes.
PAGES: dict[str, dict[int, str]] = {
    "DccSUA": {
        32: 'records containing a `"` -- the ones a default csv.reader corrupts',
        75: "tables, captions, a footnote, dotted `B.n.n` cites",
        76: "the corpus's deepest ancestor chain (7), a formula, a second table",
    },
    "dog-habitabilidad": {
        22: "the hand-verified 60º provision under A.2.2 < A.2; unaddressed `§` ids",
        25: "`m²` in body text -- the unit folding `norm` collapses to `m2`",
        32: "ids disambiguated with `~n`: the source prints one cite many times",
    },
    "DOG_2025": {
        1: "a third document; picture records; the official `Pág. NNNNN` marker",
    },
}


def build(tuned: Path) -> tuple[list[ingest.Row], list[ingest.ProvRow]]:
    """Ingest the real documents, then keep the selected pages + ancestor closure."""
    rows: list[ingest.Row] = []
    stats: defaultdict[str, int] = defaultdict(int)
    for doc in PAGES:
        ingest.ingest_doc(doc, rows, stats, tuned=tuned)

    by_id = {r["id"]: r for r in rows}
    order = {r["id"]: i for i, r in enumerate(rows)}

    keep: set[str] = set()
    for r in rows:
        if int(r["page"]) in PAGES.get(r["doc"], {}):
            keep.add(r["id"])

    # Ancestor closure: a chain that dead-ends at a parent_id the fixture does not
    # hold is not a chain, and every consumer of `parent_id` would have to special
    # -case it. Cheap -- the spine is shallow and shared.
    frontier = list(keep)
    while frontier:
        parent = by_id[frontier.pop()]["parent_id"]
        if parent and parent not in keep:
            keep.add(parent)
            frontier.append(parent)

    kept = sorted((by_id[i] for i in keep), key=lambda r: order[r["id"]])

    # Provenance is copied verbatim for the included documents rather than clipped
    # to the kept pages: #27 derives a record's fidelity by finding the range its
    # page falls in, and a clipped range would make that lookup trivially true.
    prov: list[ingest.ProvRow] = []
    for doc in PAGES:
        n_pages = len(json.loads((tuned / f"{doc}.json").read_text())["pages"])
        ocr = ingest.load_provenance(doc, tuned=tuned)
        if ocr:
            cursor = 1
            for a, b, _ in sorted(ocr):
                if cursor < a:
                    prov.append(
                        {
                            "doc": doc,
                            "page_from": cursor,
                            "page_to": a - 1,
                            "source": "native",
                        }
                    )
                prov.append({"doc": doc, "page_from": a, "page_to": b, "source": "ocr"})
                cursor = b + 1
            if cursor <= n_pages:
                prov.append(
                    {
                        "doc": doc,
                        "page_from": cursor,
                        "page_to": n_pages,
                        "source": "native",
                    }
                )
        else:
            prov.append(
                {"doc": doc, "page_from": 1, "page_to": n_pages, "source": "native"}
            )
    prov.sort(key=lambda r: (r["doc"], r["page_from"]))
    return kept, prov


# The shapes #49 requires the fixture to carry. Asserted on every build, so a page
# swap that silently drops one fails here rather than in a test six months later.
def coverage(rows: list[ingest.Row]) -> dict[str, int]:
    by_id = {r["id"]: r for r in rows}

    def depth(r):
        d, cur = 0, r
        while cur["parent_id"] in by_id:
            cur, d = by_id[cur["parent_id"]], d + 1
        return d

    cites = defaultdict(int)
    for r in rows:
        if r["cite"]:
            cites[(r["doc"], r["cite"])] += 1

    return {
        "documents": len({r["doc"] for r in rows}),
        "chain depth >= 5": sum(1 for r in rows if depth(r) >= 5),
        "repeated cite in one doc": sum(1 for n in cites.values() if n > 1),
        "id disambiguated with ~": sum(1 for r in rows if "~" in r["id"]),
        "no cite": sum(1 for r in rows if not r["cite"]),
        "positional § id": sum(1 for r in rows if ":§" in r["id"]),
        'text containing a "': sum(1 for r in rows if '"' in r["text"]),
        "table": sum(1 for r in rows if r["label"] == "table"),
        "caption": sum(1 for r in rows if r["label"] == "caption"),
        "picture": sum(1 for r in rows if r["label"] == "picture"),
        "formula": sum(1 for r in rows if r["label"] == "formula"),
        "footnote": sum(1 for r in rows if r["label"] == "footnote"),
        "m² in text folded to m2 in norm": sum(
            1 for r in rows if "m²" in r["text"] and "m2" in r["norm"]
        ),
        "parent on an earlier page": sum(
            1
            for r in rows
            if r["parent_id"] in by_id and by_id[r["parent_id"]]["page"] != r["page"]
        ),
    }


def render(rows, prov) -> dict[str, str]:
    """The three files the fixture is, as text, so `--check` diffs without writing."""

    def tsv(columns, records):
        buf = io.StringIO()
        buf.write("\t".join(columns) + "\n")
        for r in records:
            buf.write(
                "\t".join(
                    str(r.get(c, ""))
                    .replace("\t", " ")
                    .replace("\n", " ")
                    .replace("\r", " ")
                    for c in columns
                )
                + "\n"
            )
        return buf.getvalue()

    cov = coverage(rows)
    ancestor_only = defaultdict(set)
    for r in rows:
        if int(r["page"]) not in PAGES[r["doc"]]:
            ancestor_only[r["doc"]].add(int(r["page"]))

    lines = [
        "# Fixture corpus",
        "",
        "Generated by `tests/fixtures/make_fixture_corpus.py` -- **do not hand-edit**.",
        "Regenerate with `uv run python tests/fixtures/make_fixture_corpus.py`;",
        "`--check` fails if the current `ingest` would produce something else.",
        "",
        f"{len(rows)} records, {len(prov)} provenance ranges.",
        "",
        "## Whole pages",
        "",
        "`get_page` has complete ground truth for these -- the fixture holds every",
        "record the real corpus holds on them.",
        "",
    ]
    for doc, pages in PAGES.items():
        for page, why in sorted(pages.items()):
            n = sum(1 for r in rows if r["doc"] == doc and int(r["page"]) == page)
            lines.append(f"- `{doc}` p.{page} ({n} records) -- {why}")
    lines += [
        "",
        "## Partial pages",
        "",
        "Pulled in only to complete an ancestor chain. `get_page` on these returns",
        "less than the real corpus would; do not assert page completeness here.",
        "",
    ]
    for doc in sorted(ancestor_only):
        pp = ", ".join(str(p) for p in sorted(ancestor_only[doc]))
        lines.append(f"- `{doc}`: pp. {pp}")
    lines += ["", "## Shapes carried", ""]
    lines += [f"- {k}: {v}" for k, v in cov.items()]
    lines.append("")

    return {
        "corpus.tsv": tsv(ingest.COLUMNS, rows),
        "corpus.provenance.tsv": tsv(["doc", "page_from", "page_to", "source"], prov),
        "README.md": "\n".join(lines),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed fixture is not what this would write",
    )
    args = ap.parse_args(argv)

    tuned = paths.tuned_dir(args.root)
    rows, prov = build(tuned)

    cov = coverage(rows)
    missing = [k for k, v in cov.items() if v < 1]
    if len(rows) and missing:
        print("coverage lost: " + ", ".join(missing), file=sys.stderr)
        return 1

    files = render(rows, prov)

    if args.check:
        bad = []
        for name, want in files.items():
            path = OUT_DIR / name
            if not path.exists() or path.read_text() != want:
                bad.append(name)
        if bad:
            print(
                f"fixture is stale: {', '.join(bad)}\n"
                f"run `uv run python {Path(__file__).name}` and commit the result",
                file=sys.stderr,
            )
            return 1
        print(f"fixture up to date: {len(rows)} records")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (OUT_DIR / name).write_text(text)
    print(f"{len(rows)} records, {len(prov)} ranges -> {OUT_DIR}", file=sys.stderr)
    for k, v in cov.items():
        print(f"  {k}: {v}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
