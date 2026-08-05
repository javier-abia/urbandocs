#!/usr/bin/env python3
"""Prototype of the sweep + rank phases, run straight off the tuned docling JSON.

Produced the figures in docs/research/cross-document-coverage.md. It exists
because corpus.tsv does not yet (#28), so the section geometry is approximated:
a section is "nearest preceding section_header in bbox order", not the
cite-prefix nesting #32 settled on. Token magnitudes and rank orderings hold;
individual rank numbers will shift once parent_id is real.

Usage:
    python3 scripts/prototype_sweep_rank.py "anch" "libre" "paso" "puert"

Each argument is one query slot, matched as a regex against normalized text.
Sections score by distinct slots matched first, raw hit count second.
"""

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

TUNED = Path(__file__).resolve().parents[1] / "documentos/documentos-docling/docling-tuned"
DOCS = ["DccSUA", "dog-habitabilidad"]

CITE = re.compile(r"^([A-Za-z]?[0-9]+(?:\.[0-9]+)*|[A-Z]\.[0-9](?:\.[0-9])*)")


def normalize(s):
    """The `norm` projection: lowercase, strip accents, collapse whitespace."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def load():
    """Flatten the tuned JSON into (doc, page, section, section_page, text) rows.

    Items are sorted by page then bbox top, because the JSON `texts` array is
    misordered (#8) and reading order is what section attachment depends on.
    """
    records, headings = [], {}
    for doc in DOCS:
        data = json.loads((TUNED / f"{doc}.json").read_text())
        items = []
        for t in data.get("texts", []):
            prov = (t.get("prov") or [{}])[0]
            items.append((prov.get("page_no", 0), -(prov.get("bbox", {}).get("t") or 0), t))
        items.sort(key=lambda x: (x[0], x[1]))

        section, section_page = "(preamble)", 0
        for page, _, t in items:
            text = t.get("text") or ""
            if t.get("label") == "section_header":
                section, section_page = text.strip(), page
                m = CITE.match(section)
                if m:
                    headings.setdefault((doc, m.group(1).rstrip(".")), section)
            records.append((doc, page, section, section_page, text))
    return records, headings


def chain(headings, doc, section):
    """Ancestor chain of a heading, walked up its own printed cite.

    `B.2.5. Trasteros` alone is ambiguous; under `B.2. CONDICIONES DE LOS
    ESPACIOS COMUNES DEL EDIFICIO` it is not. Costs ~1.5 tokens per section.
    """
    m = CITE.match(section)
    if not m:
        return [section]
    parts = m.group(1).replace(".", " ").split()
    out = [headings[(doc, p)] for i in range(1, len(parts))
           if (p := ".".join(parts[:i])) and (doc, p) in headings]
    return out + [section]


def rank(records, slots):
    """Group hits by section, score by distinct slots matched then hit count."""
    sections = defaultdict(lambda: {"hits": 0, "slots": set()})
    for doc, page, section, section_page, text in records:
        norm = normalize(text)
        for i, slot in enumerate(slots):
            if any(re.search(p, norm) for p in slot):
                entry = sections[(doc, section, section_page)]
                entry["hits"] += 1
                entry["slots"].add(i)
    return sorted(sections.items(), key=lambda kv: (-len(kv[1]["slots"]), -kv[1]["hits"]))


def main(argv):
    slots = [a.split("|") for a in argv]
    records, headings = load()
    ranked = rank(records, slots)

    chars = 0
    for (doc, section, page), entry in ranked:
        line = f"{doc} p{page} " + " > ".join(chain(headings, doc, section))
        chars += len(line)

    print(f"sections with >=1 hit: {len(ranked)}")
    print(f"total hits: {sum(e['hits'] for _, e in ranked)}")
    print(f"ranked list with chains: ~{chars // 3} tokens\n")

    seen = set()
    for i, ((doc, section, page), entry) in enumerate(ranked, 1):
        if doc not in seen:
            seen.add(doc)
            print(f"first {doc:14s} at rank {i:4d}  slots={len(entry['slots'])} hits={entry['hits']}")
    print()
    for i, ((doc, section, page), entry) in enumerate(ranked[:15], 1):
        path = " > ".join(chain(headings, doc, section))
        print(f"{i:3d}. {doc:14s} p{page:3d} slots={len(entry['slots'])} hits={entry['hits']:3d}  {path[:90]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
