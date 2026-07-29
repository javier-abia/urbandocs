#!/usr/bin/env python3
"""Prototype: split normative text from Ministry commentary in a DoclingDocument.

Signal: the left edge of each text item's bbox. The "con comentarios del
Ministerio" editions typeset commentary as an indented block (DccSUA p.2 says so
in prose: "figuran con este tipo de letra, con esta sangria y con..."), and that
indentation is the one part of the visual distinction that survives into the
docling JSON (prov.bbox). Font colour and the left margin rule do not.

Usage: classify_commentary.py <doc.json> [--threshold PT] [--dump-page N]
"""

import argparse
import collections
import json

# Left-aligned blocks: their bbox left edge is the typographic indent, so the
# rule applies directly.
ALIGNED_LABELS = ("text", "section_header", "list_item", "formula", "footnote")
# Centred blocks: the left edge tracks the block's *width*, not its indent, so
# the rule is meaningless — these inherit from the nearest aligned neighbour.
CENTRED_LABELS = ("caption",)

# Below this, the two dominant margins are an ordinary nesting indent rather than
# a commentary block, and the rule does not apply. DccSUA's real gap is 34pt.
MIN_GAP_PT = 20


def load_items(path):
    """Walk the document body in reading order, keeping every block that has a
    page-anchored bbox."""
    doc = json.load(open(path))
    by_ref = {}
    for group in ("texts", "tables", "pictures", "groups"):
        for node in doc.get(group, []):
            by_ref[node["self_ref"]] = node

    items = []

    def visit(node):
        for child in node.get("children", []):
            n = by_ref.get(child["$ref"])
            if n is None:
                continue
            label = n.get("label")
            if n.get("prov") and label in ALIGNED_LABELS + CENTRED_LABELS + ("table",):
                p = n["prov"][0]
                items.append(
                    {
                        "ref": n["self_ref"],
                        "label": label,
                        "page": p["page_no"],
                        "left": p["bbox"]["l"],
                        "text": n.get("text") or f"<{label}>",
                    }
                )
            visit(n)

    visit(doc["body"])
    return doc, items


def find_threshold(items, noise_frac=0.005):
    """Pick the midpoint of the widest gap between the two dominant left margins,
    so the threshold is derived from the document, not hardcoded.

    Left values carried by fewer than `noise_frac` of the items are treated as
    noise (stray one-off indents, OCR jitter) and do not close a gap.
    """
    counts = collections.Counter(round(i["left"]) for i in items)
    floor = max(1, noise_frac * len(items))
    modes = [l for l, _ in counts.most_common(2)]
    lo, hi = min(modes), max(modes)
    edges = [lo] + sorted(l for l, c in counts.items() if lo < l < hi and c >= floor) + [hi]
    gap_at, gap_w = None, -1
    for a, b in zip(edges, edges[1:]):
        if b - a > gap_w:
            gap_at, gap_w = (a + b) / 2, b - a
    return gap_at, gap_w, lo, hi


def classify(items, threshold):
    for i in items:
        if i["label"] in CENTRED_LABELS:
            i["kind"] = None  # filled in below
        else:
            i["kind"] = "commentary" if i["left"] >= threshold else "normative"

    # A centred block belongs to whatever block it sits between; prefer the
    # following one (a caption introduces its table in these documents), fall
    # back to the preceding one.
    for n, i in enumerate(items):
        if i["kind"] is not None:
            continue
        after = next((j["kind"] for j in items[n + 1:] if j["kind"]), None)
        before = next((j["kind"] for j in reversed(items[:n]) if j["kind"]), None)
        i["kind"] = after or before or "normative"
        i["inherited"] = True
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--dump-page", type=int, default=None)
    ap.add_argument("--margin", type=float, default=8.0,
                    help="report items within +-MARGIN pt of the threshold as ambiguous")
    ap.add_argument("--emit", metavar="PATH",
                    help="write one JSON object per item (ref, page, kind, text) to PATH")
    args = ap.parse_args()

    doc, items = load_items(args.json_path)
    auto, gap_w, lo, hi = find_threshold(items)
    threshold = args.threshold if args.threshold is not None else auto

    print(f"{doc['name']}: {len(items)} text items over {len(doc['pages'])} pages")
    print(f"  dominant left margins: {lo}pt / {hi}pt   empty gap width {gap_w:.0f}pt")
    if gap_w < MIN_GAP_PT and args.threshold is None:
        print(f"  no indent-marked commentary layer: the two dominant margins are only "
              f"{gap_w:.0f}pt apart (need >={MIN_GAP_PT}pt). Refusing to classify — this is "
              f"either a document with no commentary edition, or one that marks commentary "
              f"by some signal other than indentation. Pass --threshold to override.")
        return

    classify(items, threshold)
    n = collections.Counter(i["kind"] for i in items)
    print(f"  threshold: {threshold:.1f}pt  ->  normative {n['normative']}  commentary {n['commentary']}")

    amb = [i for i in items if abs(i["left"] - threshold) <= args.margin]
    print(f"  ambiguous (within +-{args.margin}pt): {len(amb)}")
    for i in amb[:20]:
        print(f"    p{i['page']} l={i['left']:.0f} {i['label']}: {i['text'][:80]!r}")

    pages = collections.defaultdict(collections.Counter)
    for i in items:
        pages[i["page"]][i["kind"]] += 1
    mixed = [p for p, c in pages.items() if c["normative"] and c["commentary"]]
    print(f"  pages with both kinds: {len(mixed)} / {len(pages)}")

    # A page whose own dominant margin is neither of the document's two modes is
    # typeset to a third grid — front matter, not commentary. The rule cannot
    # see the difference, so flag the page rather than silently labelling it.
    odd = []
    per_page = collections.defaultdict(collections.Counter)
    for i in items:
        if i["label"] not in CENTRED_LABELS:
            per_page[i["page"]][round(i["left"])] += 1
    for p, c in sorted(per_page.items()):
        mode, n_mode = c.most_common(1)[0]
        # Only detectable on the commentary side: below the threshold a third
        # margin is indistinguishable from an ordinary nested-list indent.
        if mode >= threshold and abs(mode - hi) > 4 and n_mode >= 5:
            odd.append((p, mode, n_mode))
    if odd:
        print(f"  pages on a third margin (likely front matter, not commentary): "
              + ", ".join(f"p{p} (l={m}, {n} items)" for p, m, n in odd))

    if args.emit:
        with open(args.emit, "w") as fh:
            for i in items:
                fh.write(json.dumps({k: i[k] for k in ("ref", "page", "label", "kind", "text")},
                                    ensure_ascii=False) + "\n")
        print(f"  wrote {len(items)} classified items to {args.emit}")

    if args.dump_page:
        print(f"\n--- page {args.dump_page} in reading order ---")
        for i in items:
            if i["page"] == args.dump_page:
                tag = "COM" if i["kind"] == "commentary" else "NOR"
                print(f"{tag} l={i['left']:6.1f} {i['label']:15s} {i['text'][:100]!r}")


if __name__ == "__main__":
    main()
