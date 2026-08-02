#!/usr/bin/env python3
"""Measure how much the navigable index actually routes (issue #5).

The measurement turns on which part of a query is the routing key. A permit
question is not "altura libre" but "altura libre *de los trasteros*": the entity
localizes, the attribute is corpus-wide, since every section of a dimensional
norm talks about heights and widths. Routing on the attribute measures nothing.

So each probe is an (entity, attribute) pair. Ground truth is every body item
containing both. Routing is simulated as literal matching of the entity against
the section's L2 line — which understates a real agent, since an agent reads the
digest rather than matching it, so the recall reported here is a floor.

    python3 scripts/eval_index_routing.py
    python3 scripts/eval_index_routing.py --misses
"""

import argparse
import importlib.util
import pathlib
import re

BUILDER = pathlib.Path(__file__).parent / "build_navigable_index.py"

# (label, entity pattern, attribute pattern)
PROBES = [
    ("trastero + altura", r"trastero", r"altura"),
    ("rampa + pendiente", r"rampa", r"pendiente"),
    ("escalera + ancho", r"escalera", r"ancho|anchura|huella"),
    ("estancia + superficie", r"estancia", r"superficie"),
    ("garaje + ancho", r"garaje|aparcamiento", r"ancho|anchura"),
    ("cocina + superficie", r"cocina", r"superficie"),
    ("ascensor + dimensión", r"ascensor", r"dimensi|ancho"),
    ("baño + ventilación", r"baño|aseo", r"ventila"),
]


def load_builder():
    spec = importlib.util.spec_from_file_location("bni", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def span(section):
    if section["start"] == section["end"]:
        return f"p{section['start']}"
    return f"p{section['start']}-{section['end']}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--misses", action="store_true", help="print every unrouted provision")
    args = parser.parse_args()

    bni = load_builder()
    by_doc = {doc: bni.load_sections(doc) for doc in bni.DOCS}

    sections = {}
    for doc, items in by_doc.items():
        for section in items:
            sections[f"{doc}:{span(section)}"] = section

    digests = {}
    for doc, items in by_doc.items():
        for line in bni.build_l2(items):
            ref, title, terms = line.split(" | ")
            digests[ref] = (title, terms)

    print(f"{'query':<24} {'routed':>7} {'truth':>6} {'found':>6} {'recall':>7}")
    total_truth = total_found = 0
    misses = []

    for label, entity, attribute in PROBES:
        ent = re.compile(entity, re.I)
        attr = re.compile(attribute, re.I)

        routed = {
            ref for ref, (title, terms) in digests.items()
            if ent.search(title) or ent.search(terms)
        }

        truth = found = 0
        for ref, section in sections.items():
            for body in section["body"]:
                if ent.search(body) and attr.search(body):
                    truth += 1
                    if ref in routed:
                        found += 1
                    else:
                        misses.append((label, ref, digests[ref], body))

        total_truth += truth
        total_found += found
        recall = f"{found / truth * 100:.0f}%" if truth else "n/a"
        print(f"{label:<24} {len(routed):>7} {truth:>6} {found:>6} {recall:>7}")

    overall = total_found / total_truth * 100 if total_truth else 0
    print(f"{'TOTAL':<24} {'':>7} {total_truth:>6} {total_found:>6} {overall:>6.0f}%")

    if args.misses:
        print("\n=== unrouted provisions ===")
        seen = set()
        for label, ref, digest, body in misses:
            if (label, ref) in seen:
                continue
            seen.add((label, ref))
            print(f"[{label}] {ref} :: {digest[0][:55]}")
            print(f"    digest: {digest[1]}")
            print(f"    text:   {body[:140]}")


if __name__ == "__main__":
    main()
