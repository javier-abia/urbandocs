#!/usr/bin/env python3
"""Count pointers in the corpus, and size an attribute-only corpus-wide search.

Backs the sizing decisions in docs/research/agentic-lookup-loop.md (#6):

  --pointers  how many pointers each document carries, split in-corpus vs
              external. Sizes the N=1 refine round.
  --breadth   how many body items a bare attribute term hits corpus-wide.
              Sizes phase 3's mandated term floor.

A *pointer* names another addressable unit by the cite the page prints
("tabla 1.2", "apartado SUA1 - 4.3.1", "anexo II"). It is in-corpus when the
target is a provision in one of the held documents, external when it names a
norm we do not hold ("Ley 39/2015", "DB SI"). Relative mentions ("el apartado
anterior") carry no address and are not pointers; self-titles are the unit's
own heading and are excluded with the heading labels.

Runs against the tuned docling JSON, which is the only trustworthy read of the
page (#18: the markdown serializer fabricates markers and reorders body).

    python3 scripts/count_pointers.py --pointers
    python3 scripts/count_pointers.py --breadth
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

TUNED = Path("documentos/documentos-docling/docling-tuned")
DOCS = ("DccSUA", "dog-habitabilidad", "DOG_2025")

# Headings are the unit's own title, not a reference to another unit.
HEADING_LABELS = {"section_header", "title", "page_header", "page_footer"}

# A pointer: a unit noun followed by an address the page prints.
POINTER = re.compile(
    r"\b(art[íi]culo|art\.|apartado|tabla|anejo|anexo|secci[óo]n|cap[íi]tulo"
    r"|figura|gr[áa]fico|punto)\s+"
    r"((?:SUA\s*)?[A-Z]{0,4}[\dIVX]+(?:[.\-][\dIVX]+)*|[A-Z])\b",
    re.I,
)

# A norm this corpus does not hold. Looked for just after the pointer, since
# "el artículo 129 de la Ley 39/2015" points outside; "el artículo 12" does not.
EXTERNAL_TARGET = re.compile(
    r"\b(Ley|Real Decreto|RD|Decreto|Reglamento)\s+[\d/]+|\bDB[- ]S[IEH]\b|\bCTE\b",
    re.I,
)
EXTERNAL_WINDOW = 60

# Figures resolve to a page and a position, never to a rule (#3: figure content
# is out of scope), so they are counted apart from provision pointers.
FIGURE_NOUN = re.compile(r"^(figura|gr[áa]fico)$", re.I)

ATTRIBUTES = (
    "altura", "ancho", "anchura", "superficie", "pendiente", "dimension",
    "garaje", "aparcamiento", "rampa", "escalera", "trastero", "cocina",
    "estancia",
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).lower()


def body_items(doc: dict, drop_headings: bool = True):
    """Yield the text of every body item, furniture and headings filtered out.

    The furniture filter is #14's: label-based, and measured to eat no body text
    in any of the three documents.
    """
    for item in doc.get("texts", []):
        if item.get("content_layer") == "furniture":
            continue
        if drop_headings and item.get("label") in HEADING_LABELS:
            continue
        text = (item.get("text") or "").strip()
        if text:
            yield text


def load(name: str) -> dict:
    return json.loads((TUNED / f"{name}.json").read_text())


def count_pointers() -> None:
    totals = {"pointer": 0, "in_corpus": 0, "external": 0, "figure": 0}
    print(f"{'document':16s} {'items':>6s} {'pointers':>9s} {'in-corpus':>10s} "
          f"{'external':>9s} {'figure':>7s} {'items w/ ptr':>13s}")
    for name in DOCS:
        counts = {"pointer": 0, "in_corpus": 0, "external": 0, "figure": 0}
        items = with_pointer = 0
        for text in body_items(load(name)):
            items += 1
            hit = False
            for match in POINTER.finditer(text):
                counts["pointer"] += 1
                hit = True
                if FIGURE_NOUN.match(match.group(1)):
                    counts["figure"] += 1
                elif EXTERNAL_TARGET.search(
                    text[match.end():match.end() + EXTERNAL_WINDOW]
                ):
                    counts["external"] += 1
                else:
                    counts["in_corpus"] += 1
            with_pointer += hit
        for key in totals:
            totals[key] += counts[key]
        share = 100 * with_pointer / max(items, 1)
        print(f"{name:16s} {items:6d} {counts['pointer']:9d} "
              f"{counts['in_corpus']:10d} {counts['external']:9d} "
              f"{counts['figure']:7d} {with_pointer:8d} ({share:4.1f}%)")
    print(f"\n{'TOTAL':16s} {'':6s} {totals['pointer']:9d} "
          f"{totals['in_corpus']:10d} {totals['external']:9d} {totals['figure']:7d}")


def count_breadth() -> None:
    """Hit counts for a bare attribute term, corpus-wide.

    Phase 3 searches every content word of the query on its own, so the worst
    case is a common attribute matched against the whole corpus. This is what
    that costs in snippets.
    """
    texts = [normalize(t) for name in DOCS for t in body_items(load(name),
                                                              drop_headings=False)]
    print(f"body items corpus-wide: {len(texts)}\n")
    for term in ATTRIBUTES:
        hits = sum(1 for t in texts if term in t)
        print(f"  {term:14s} {hits:5d} hits  ({100 * hits / len(texts):4.1f}% of items)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointers", action="store_true",
                        help="count pointers per document (sizes the refine round)")
    parser.add_argument("--breadth", action="store_true",
                        help="count attribute-only hits (sizes phase 3)")
    args = parser.parse_args()
    if not (args.pointers or args.breadth):
        parser.error("pass --pointers or --breadth")
    if args.pointers:
        count_pointers()
    if args.breadth:
        if args.pointers:
            print()
        count_breadth()


if __name__ == "__main__":
    main()
