#!/usr/bin/env python3
"""Acceptance gate over `corpus/corpus.tsv`.

Stage 2 is fast and rerun on every change (#28), so the bands that decide whether
a rebuild is *good* have to be re-assertable in seconds rather than re-measured
by hand. This is that assertion.

The bands are #41's, measured on Decreto 128/2023 in
[#39](https://github.com/javier-abia/urbandocs/issues/39) and re-asserted here on
the ingested substrate rather than on the Stage 1 JSON -- 54 of the 65 `²` live
in tables, so a check that reads only body text would pass on a corpus whose
tables had been dropped.

Usage:
    uv run -m urbandocs.check_corpus
    uv run -m urbandocs.check_corpus --corpus /tmp/corpus.tsv
"""

from __future__ import annotations

import argparse
import collections
import csv
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from urbandocs import paths

if TYPE_CHECKING:
    from collections.abc import Sequence

DECREE = "dog-habitabilidad"

# The OCR'd corpus this replaced held zero of every one of these across pp.1-95
# (#39). They are the reason the swap was taken.
SYMBOL_BANDS = [("²", 65), ("≥", 3), ("±", 1)]

# The angle thresholds exist nowhere in the OCR'd corpus: EasyOCR has no degree
# glyph, and unlike `m²` the *number* died with the symbol (#39).
ANGLE_BANDS = {"15º": 2, "45º": 1, "60º": 2, "90º": 2}

# Present in the OCR'd corpus, absent from the decree -- they read as plausible
# rules and were never in the source (#39).
#
# The negative lookahead is load-bearing: the decree writes `7 m 2` (docling
# splits the superscript), which is an *area*. Without it this check reports a
# false failure on a correct corpus.
PHANTOMS = [
    (r"\b1,5\s*m(?!\s*[²2m])\b", "1,5 m"),
    (r"\b120\s*m(?!\s*[²2m])\b", "120 m"),
    (r"\b30\s*cm\b", "30 cm"),
    (r"\b7\s*m(?!\s*[²2m])\b", "7 m"),
]

# Page furniture that must never land inside a record. `Pág. NNNNN` is
# deliberately absent from this list -- it is the official citation page and is
# kept (#8, #14).
FURNITURE = ["ISSN", "CVE-DOG", "Depósito legal", "DOG Núm"]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="uv run -m urbandocs.check_corpus",
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

    rows = list(csv.DictReader(corpus.open(), delimiter="\t"))
    decree = [r for r in rows if r["doc"] == DECREE]
    if not decree:
        sys.exit(f"no {DECREE} records in {corpus}")
    text = " ".join(r["text"] for r in decree)

    failures: list[str] = []

    def band(name: str, got: int, want: int) -> None:
        ok = got >= want
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {got} (want >= {want})")
        if not ok:
            failures.append(name)

    print(f"{len(rows)} records, {len(decree)} in {DECREE}")

    print("\nsymbols the OCR'd corpus had zero of")
    for sym, want in SYMBOL_BANDS:
        band(sym, text.count(sym), want)
    band("º/°", text.count("º") + text.count("°"), 10)

    print("\nangle thresholds")
    found = collections.Counter(
        re.sub(r"^[±<>≥≤]", "", m.replace(" ", ""))
        for m in re.findall(r"[±<>≥≤]?\s*\d+\s*[º°]", text)
    )
    for angle, want in ANGLE_BANDS.items():
        band(angle, found.get(angle, 0), want)

    print("\nphantom values (must be absent)")
    for pattern, name in PHANTOMS:
        hits = re.findall(pattern, text)
        ok = not hits
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {len(hits)}")
        if not ok:
            failures.append(f"phantom {name}")

    print("\npage furniture (must be absent) and the printed page (must survive)")
    for pattern in FURNITURE:
        n = sum(1 for r in decree if pattern in r["text"])
        print(f"  [{'PASS' if not n else 'FAIL'}] {pattern}: {n}")
        if n:
            failures.append(pattern)
    n_pag = sum(1 for r in decree if re.match(r"^Pág\.\s*\d+$", r["text"]))
    print(f"  [{'PASS' if n_pag else 'FAIL'}] Pág. records kept: {n_pag}")
    if not n_pag:
        failures.append("Pág. records")

    print("\nprovenance (every range native -- the OCR programme is retired)")
    prov = list(
        csv.DictReader(corpus.with_name("corpus.provenance.tsv").open(), delimiter="\t")
    )
    for r in prov:
        ok = r["source"] == "native"
        print(
            f"  [{'PASS' if ok else 'FAIL'}] {r['doc']} pp.{r['page_from']}-"
            f"{r['page_to']}: {r['source']}"
        )
        if not ok:
            failures.append(f"provenance {r['doc']}")

    print("\nancestor chain of the hand-verified provision")
    by = {r["id"]: r for r in rows}
    for r in decree:
        if "60º" not in r["text"]:
            continue
        chain, cur, seen = [], r, set()
        while (
            cur["parent_id"] and cur["parent_id"] in by and cur["parent_id"] not in seen
        ):
            seen.add(cur["parent_id"])
            cur = by[cur["parent_id"]]
            chain.append(cur["cite"] or cur["text"][:24])
        ok = chain[:2] == ["A.2.2", "A.2"]
        print(f"  [{'PASS' if ok else 'FAIL'}] {r['id']}: {' < '.join(chain)}")
        if not ok:
            failures.append(f"chain {r['id']}")

    print()
    if failures:
        print(f"FAIL: {', '.join(failures)}")
        return 1
    print("PASS: all bands")
    return 0


if __name__ == "__main__":
    sys.exit(main())
