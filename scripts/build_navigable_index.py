#!/usr/bin/env python3
"""Prototype of the two-level navigable index (issue #5).

Builds, from the tuned docling JSON, the artifact the agent reads before it
opens any document:

  L1  index/corpus.index      one line per document, always in context
  L2  index/<DOC>.index       one line per section, loaded only for the
                              documents L1 selected

Both levels are derived, never authored: a line is the section's own body text
reduced to its most distinctive terms, so the index routes on the vocabulary
queries actually use rather than on heading titles (see the prototype writeup
in docs/research/navigable-index-prototype.md).

Constraints inherited from the map:
  #14  SectionHeaderItem.level is inverted and must be discarded; the spine is
       the document order of the heading items, not their reported level.
  #14  content_layer == "furniture" is a safe filter and eats no body text.
  #18  the .md serializer fabricates list markers and reorders body, so this
       reads the JSON only.

Usage:
    python3 scripts/build_navigable_index.py
    python3 scripts/build_navigable_index.py --query "altura libre"
"""

import argparse
import collections
import json
import math
import pathlib
import re
import sys

TUNED = pathlib.Path("documentos/documentos-docling/docling-tuned")
OUT = pathlib.Path("index")
DOCS = ["DccSUA", "DOG_2025", "dog-habitabilidad"]

HEADING_LABELS = {"section_header", "title"}
WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{5,}")

# Terms that carry no routing signal: legal-boilerplate verbs and connectives
# frequent enough to crowd out the distinctive vocabulary of every section.
STOPWORDS = {
    "acuerdo", "casos", "condiciones", "considera", "correspondiente",
    "correspondientes", "cualquier", "cuando", "debera", "deberan", "deben",
    "desde", "dicha", "dicho", "entre", "establece", "establecido", "forma",
    "hasta", "menos", "misma", "mismo", "otras", "otros", "partes", "puede",
    "pueden", "segun", "siempre", "sobre", "todas", "todos",
}

TOP_TERMS_L2 = 8
TOP_TERMS_L1 = 25


def load_sections(doc):
    """Split a document into sections: a heading plus the body items under it.

    Section boundaries are heading items in document order. `level` is ignored
    entirely (#14: the emitted tree is inverted), so this is a flat sequence,
    not a tree — the hierarchy is rebuilt downstream from the heading text.
    """
    data = json.loads((TUNED / f"{doc}.json").read_text())
    sections = []
    current = None
    for item in data["texts"]:
        if item.get("content_layer") == "furniture":
            continue
        text = " ".join(item["text"].split())
        page = item["prov"][0]["page_no"] if item.get("prov") else 0
        if item["label"] in HEADING_LABELS:
            current = {
                "doc": doc,
                "title": text,
                "start": page,
                "end": page,
                "body": [],
            }
            sections.append(current)
        elif current is not None:
            current["body"].append(text)
            current["end"] = max(current["end"], page)
    # A heading with no body under it is a contents-page echo of a section that
    # appears again later with its text. It cannot route anything, so drop it.
    return [s for s in sections if s["body"]]


def terms(section):
    return WORD.findall(" ".join(section["body"]).lower())


def build_l2(sections):
    """One line per section, ranked by tf-idf against the other sections."""
    doc_freq = collections.Counter()
    for section in sections:
        for term in set(terms(section)):
            doc_freq[term] += 1
    total = len(sections)

    lines = []
    for section in sections:
        freq = collections.Counter(terms(section))
        scored = {
            term: count * math.log(total / (1 + doc_freq[term]))
            for term, count in freq.items()
            if term not in STOPWORDS
        }
        top = [t for t, _ in sorted(scored.items(), key=lambda kv: -kv[1])][:TOP_TERMS_L2]
        span = f"p{section['start']}" if section["start"] == section["end"] \
            else f"p{section['start']}-{section['end']}"
        lines.append(f"{section['doc']}:{span} | {section['title'][:70]} | {' '.join(top)}")
    return lines


def build_l1(by_doc):
    """One line per document. Terms shared by every document are dropped —
    they describe the corpus, not the document, so they cannot discriminate."""
    per_doc_terms = {doc: collections.Counter() for doc in by_doc}
    for doc, sections in by_doc.items():
        for section in sections:
            per_doc_terms[doc].update(terms(section))

    ubiquitous = set.intersection(*(set(c) for c in per_doc_terms.values()))

    lines = []
    for doc, sections in by_doc.items():
        freq = per_doc_terms[doc]
        top = [
            term for term, _ in freq.most_common()
            if term not in STOPWORDS and term not in ubiquitous
        ][:TOP_TERMS_L1]
        pages = max(s["end"] for s in sections)
        lines.append(f"{doc} | {pages}pp {len(sections)}sec | {' '.join(top)}")
    return lines


def query(by_doc, l2_by_doc, phrase):
    """Demonstrate the locked lookup contract: route via the index, then run a
    corpus-wide exact search as a safety net and surface anything the routing
    missed. The routing is advisory — it decides what to read first, never what
    is allowed to be found."""
    needles = phrase.lower().split()

    routed = set()
    for doc, lines in l2_by_doc.items():
        for line in lines:
            if all(n in line.lower() for n in needles):
                routed.add(line.split(" | ")[0])

    print(f"routed to {len(routed)} sections via the index:")
    for ref in sorted(routed):
        print(f"    {ref}")

    pattern = re.compile(re.escape(phrase), re.I)
    outside = []
    hits = 0
    for doc, sections in by_doc.items():
        for section in sections:
            span = f"p{section['start']}" if section["start"] == section["end"] \
                else f"p{section['start']}-{section['end']}"
            ref = f"{doc}:{span}"
            for body in section["body"]:
                if pattern.search(body):
                    hits += 1
                    if ref not in routed:
                        outside.append((ref, section["title"], body))

    print(f"\ncorpus-wide verification: {hits} hits, {len(outside)} outside the routed set")
    for ref, title, body in outside[:8]:
        print(f"    [{ref}] {title[:60]}")
        print(f"        {body[:150]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", help="demonstrate a lookup instead of writing the index")
    args = parser.parse_args()

    if not TUNED.exists():
        sys.exit(f"missing {TUNED} — run the tuned conversion first (issue #13)")

    by_doc = {doc: load_sections(doc) for doc in DOCS}
    l2_by_doc = {doc: build_l2(sections) for doc, sections in by_doc.items()}

    if args.query:
        query(by_doc, l2_by_doc, args.query)
        return

    OUT.mkdir(exist_ok=True)
    l1 = build_l1(by_doc)
    (OUT / "corpus.index").write_text("\n".join(l1) + "\n")
    print(f"index/corpus.index  {len(l1)} docs  ~{len('\n'.join(l1)) // 4} tokens")
    for doc, lines in l2_by_doc.items():
        (OUT / f"{doc}.index").write_text("\n".join(lines) + "\n")
        print(f"index/{doc}.index  {len(lines)} sections  ~{len(chr(10).join(lines)) // 4} tokens")


if __name__ == "__main__":
    main()
