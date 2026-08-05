#!/usr/bin/env python3
"""Section geometry over corpus.tsv: why `parent_id` and not a `±N` window.

#32 rejected returning a fixed window of lines around a hit, on three numbers
that came from an ad-hoc probe and were not re-derivable. This is that probe,
committed and run over the real substrate, so the argument stays checkable and
so the ingest fixes it motivated can be verified by re-running it:

  ancestor distance   how far, in records of reading order, a provision sits
                      from the section header that governs it
  window recall       how often a `±N` window actually contains that header
  cross-section bleed how much of that window belongs to a *different* section
  boundary check      whether any record's parent is a header that its own
                      section boundary sits between -- the off-by-one #28
                      records, where a section's children swallowed the *next*
                      section's header

Usage:
    python3 scripts/section_geometry.py                  # corpus/corpus.tsv
    python3 scripts/section_geometry.py --window 10 30 60
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT = REPO / "corpus/corpus.tsv"


def load(path: Path) -> list[dict]:
    with path.open() as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    values = sorted(values)
    return values[min(len(values) - 1, int(round((len(values) - 1) * p)))]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", type=Path, default=DEFAULT)
    ap.add_argument("--window", type=int, nargs="*", default=[10, 30, 60])
    args = ap.parse_args(argv)

    rows = load(args.corpus)
    pos = {r["id"]: i for i, r in enumerate(rows)}
    headers = {r["id"] for r in rows if r["label"] == "section_header"}

    # A record's governing section is its nearest section_header ancestor. Body
    # records hang directly off one; a header's own section is its parent.
    parent = {r["id"]: r["parent_id"] for r in rows}

    def section_of(ident: str) -> str:
        seen = set()
        cur = parent.get(ident, "")
        while cur and cur not in seen:
            if cur in headers:
                return cur
            seen.add(cur)
            cur = parent.get(cur, "")
        return ""

    distances, orphans = [], 0
    section = {}
    for r in rows:
        if r["label"] == "section_header":
            continue
        sec = section_of(r["id"])
        section[r["id"]] = sec
        if not sec:
            orphans += 1
            continue
        distances.append(abs(pos[r["id"]] - pos[sec]))

    print(f"corpus: {len(rows)} records, {len(headers)} section headers, "
          f"{orphans} records with no section header above them")
    print("\nancestor distance (records of reading order between a provision "
          "and its governing header)")
    for p in (0.5, 0.75, 0.9, 0.95, 0.99):
        print(f"  p{int(p * 100):<3d} {percentile(distances, p):5d}")
    print(f"  max  {max(distances) if distances else 0:5d}")

    print("\nwindow recall -- is the governing header inside ±N records?")
    for n in args.window:
        hit = sum(1 for d in distances if d <= n)
        print(f"  ±{n:<3d} {hit / len(distances) * 100:5.1f}%  "
              f"({hit}/{len(distances)})")

    print("\ncross-section bleed -- share of a ±N window belonging to a "
          "different section")
    for n in args.window:
        foreign = total = 0
        for r in rows:
            sec = section.get(r["id"])
            if not sec:
                continue
            lo, hi = max(0, pos[r["id"]] - n), min(len(rows), pos[r["id"]] + n + 1)
            for other in rows[lo:hi]:
                if other["doc"] != r["doc"]:
                    continue
                total += 1
                if section.get(other["id"], other["id"]) != sec:
                    foreign += 1
        print(f"  ±{n:<3d} {foreign / total * 100:5.1f}%  ({foreign}/{total})")

    print("\nboundary check -- a section's children must stop at the next "
          "section")
    children = defaultdict(list)
    for r in rows:
        children[r["parent_id"]].append(r)
    # The invariant: every header lying between a parent header and one of its
    # children must itself be a descendant of that parent. A child sitting past
    # a header that is *not* a descendant means the section's children ran on
    # into the next section -- the prototype's off-by-one, where the boundary
    # marker itself became content.
    def descends_from(ident: str, ancestor: str) -> bool:
        seen, cur = set(), ident
        while cur and cur not in seen:
            if cur == ancestor:
                return True
            seen.add(cur)
            cur = parent.get(cur, "")
        return False

    header_positions = sorted(pos[h] for h in headers)
    by_pos = {pos[r["id"]]: r for r in rows}
    crossings = []
    for head_id, kids in children.items():
        if head_id not in headers:
            continue
        start = pos[head_id]
        for kid in kids:
            end = pos[kid["id"]]
            if end <= start:
                continue
            for hp in header_positions:
                if not (start < hp < end):
                    continue
                between = by_pos[hp]["id"]
                if not descends_from(between, head_id):
                    crossings.append((head_id, between, kid["id"]))
                    break
    print(f"  {len(crossings)} children sitting past their section's end")
    for head_id, between, kid_id in crossings[:10]:
        print(f"    {head_id} -> {kid_id}, past {between}")

    print("\nper-document record counts")
    counts = defaultdict(lambda: defaultdict(int))
    for r in rows:
        counts[r["doc"]][r["label"]] += 1
    for doc in sorted(counts):
        total = sum(counts[doc].values())
        parts = " ".join(f"{k}={v}" for k, v in sorted(counts[doc].items()))
        print(f"  {doc:16s} {total:5d}   {parts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
