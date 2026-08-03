#!/usr/bin/env python3
"""Stage 2 ingest: tuned docling JSON -> corpus.tsv.

Fast (seconds) and rerun on every change, against the docling JSON committed by
Stage 1 (`scripts/convert.py`). Never reads the `.md`: the markdown serializer
fabricates list markers from a counter and emits `body` out of reading order
(#18). Item order here comes from `prov.bbox`, because the JSON `texts` array is
misordered too (#8).

Emits one flat corpus-wide table (#32), eight columns:

    id  doc  page  cite  parent_id  label  text  norm

and a sidecar `corpus.provenance.tsv` (doc, page_from, page_to, source) so the
answering layer can derive per-record fidelity from `doc` + `page` + `label`
without any record storing it (#27).

Usage:
    python3 scripts/ingest.py                     # writes corpus/corpus.tsv
    python3 scripts/ingest.py --out /tmp/c.tsv --stats
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TUNED = REPO / "documentos/documentos-docling/docling-tuned"
DOCS = ["DccSUA", "DOG_2025", "HABITABILIDAD"]

# Short code used in ids. Ids are read aloud in citations, so they are hand-set
# rather than derived; any document not listed falls back to its first three
# alphanumerics upper-cased.
DOC_CODES = {"DccSUA": "SUA", "DOG_2025": "DOG", "HABITABILIDAD": "HAB"}

COLUMNS = ["id", "doc", "page", "cite", "parent_id", "label", "text", "norm"]

# Furniture is labelled, not contained -- `furniture.children` is empty in all
# three documents, so the filter is label-based (#14). Verified to eat no body
# text in any document. DOG_2025's official `Pág.` markers are labelled `text`
# and therefore survive, which is what #8 wants.
FURNITURE_LABELS = {"page_header", "page_footer"}

# Private-use codepoints are a fixed Symbol-font mapping, verified in context
# (#14). Decoding them recovers the character the page prints; it asserts
# nothing about meaning, so it applies to `text` as well as `norm`.
SYMBOL_MAP = {"\uf0b1": "±", "\uf061": "α", "\uf044": "Δ", "\uf06d": "μ"}

# Subscripts split by extraction in body text (`R d` for `Rd`), while the same
# document holds the correct `R _ { d }` inside its LaTeX (#14). Rejoined in
# `norm` only; query-side normalization runs the same function, so both
# spellings reach the same key.
SUBSCRIPT_PAIRS = [("R", "d"), ("C", "1"), ("B", "o"), ("U", "d"), ("R", "c")]

# A section header's printed cite. Ordered: the longest, most specific shapes
# first, so `Artículo 14.` does not match the bare-number rule.
CITE_PATTERNS = [
    # namespace headings -- they open a numbering space rather than sit in one
    (re.compile(r"^(Anejo\s+[A-Z])\b", re.I), "ns", 1),
    (re.compile(r"^(Secci[oó]n\s+[A-Z]*\s*[0-9]+)\b", re.I), "ns", 1),
    (re.compile(r"^(Cap[ií]tulo\s+[IVXLC0-9]+)\b", re.I), "ns", 1),
    (re.compile(r"^(T[ií]tulo\s+[IVXLC0-9]+)\b", re.I), "ns", 1),
    (re.compile(r"^(Art[ií]culo\s+[0-9]+)\b", re.I), "ns", 2),
    # dotted numbering -- `B.2.6.2`, `A.1.1`, `4.1`, `12`
    (re.compile(r"^([A-Z]\.[0-9]+(?:\.[0-9]+)*)\.?(?=[\s.]|$)"), "num", None),
    (re.compile(r"^([0-9]+(?:\.[0-9]+)*)\.?(?=\s|$)"), "num", None),
]

# List markers, as printed: `a)`, `1.`, `iv)`. Nothing here guesses an ordinal --
# an item whose marker cannot be read stays unaddressed rather than being
# numbered by position (#18).
MARKER_RE = re.compile(r"^\s*([0-9]+|[a-zA-Z]|[ivxIVX]+)\s*[.)]\s*$")

# DccSUA and DOG_2025 have no marker *hole* -- they print the marker inline at
# the head of the item text (`1 La anchura...`), which docling leaves in `text`
# and out of `marker`. That needs parsing, not recovery (#18); it addresses 158
# of DccSUA's 359 list items that would otherwise have no cite.
INLINE_MARKER_RE = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)*|[a-z]|[ivx]+)\s*[).]?\s+(?=[A-ZÁÉÍÓÚÜÑ])")

# Vertical indent step, in points, that separates a nested list item from its
# sibling. HABITABILIDAD prints top-level items at `bbox.l` ~70 and their
# sub-items at ~83.5 -- the same ~13 pt gutter #18 read the eaten markers out of.
INDENT_TOL = 6.0


# --------------------------------------------------------------------------- #
# text repair and normalization
# --------------------------------------------------------------------------- #

def repair(text: str, ocr: bool) -> str:
    """Deterministic repairs on the rendered `text` (#28).

    Not on this list, deliberately:

    - `m2 -> m²`. The source itself writes `m2` in places, and architects and
      the answering agent both read it correctly (#21, owner steer 2026-07-30).
    - any `>` -> `≥` rewrite. Roughly one comparison in eight is genuinely
      strict; the corpus uses 21 `<` and 13 `>` for real (#21).
    - standalone `0` -> `o`. `0` is also a legitimate digit, so this is a
      query-side equivalence and never an ingest rewrite (#14, #28).
    """
    for bad, good in SYMBOL_MAP.items():
        text = text.replace(bad, good)
    text = text.replace("><", "×")
    if ocr:
        # `m²` reads as `m?` 25 times in HABITABILIDAD and correctly zero times
        # (#11) -- the `?` is the OCR's failure to encode a superscript 2, not a
        # character on the page.
        text = re.sub(r"(?<=\bm)\?", "²", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str) -> str:
    """The `norm` projection -- what `search` matches (#14, in that order).

    `get` returns `text`. Query-side normalization must call this same function,
    or the two sides stop agreeing.
    """
    for bad, good in SYMBOL_MAP.items():
        text = text.replace(bad, good)
    s = re.sub(r"\s+", " ", text).strip()
    # hyphenation rejoin, guarded: `pre- vistas` -> `previstas`, but not
    # `30-40 mm`, where both sides are numeric.
    s = re.sub(r"(?<=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])-\s+(?=[a-zñáéíóúü])", "", s)
    for head, tail in SUBSCRIPT_PAIRS:
        s = re.sub(rf"\b{head}\s+{tail}\b", f"{head}{tail}", s)
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # unit folding -- all three spellings occur (107 / 67 / 35 corpus-wide)
    s = re.sub(r"\bm\s*[²2?]", "m2", s)
    return s


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #

def top_key(prov: dict) -> float:
    """Sort key for reading order: smaller is higher on the page.

    docling emits text bboxes BOTTOMLEFT and table cells TOPLEFT, so the origin
    has to be read off each box rather than assumed.
    """
    bbox = prov.get("bbox") or {}
    t = bbox.get("t") or 0.0
    return -t if bbox.get("coord_origin") == "BOTTOMLEFT" else t


# Vertical tolerance, in points, for calling two boxes the same line. One line of
# this corpus's body text is ~10 pt; 4 pt is wide enough to absorb the baseline
# jitter between boxes on one line and narrow enough not to merge two lines.
LINE_BAND = 4.0


def inside(box: dict, outer: dict, pad: float = 2.0) -> bool:
    """Is `box` contained in `outer`? Both must be BOTTOMLEFT."""
    if not box or not outer:
        return False
    lo_b, hi_b = min(box["t"], box["b"]), max(box["t"], box["b"])
    lo_o, hi_o = min(outer["t"], outer["b"]), max(outer["t"], outer["b"])
    return (box["l"] >= outer["l"] - pad and box["r"] <= outer["r"] + pad
            and lo_b >= lo_o - pad and hi_b <= hi_o + pad)


# --------------------------------------------------------------------------- #
# cites and the heading spine
# --------------------------------------------------------------------------- #

def parse_cite(text: str):
    """Return (printed_cite, kind, rank) for a heading, or (None, None, None).

    `kind` is `num` for dotted numbering, which nests by prefix, or `ns` for a
    namespace heading (`Anejo A`, `Sección SUA 1`, `Artículo 14`), which opens a
    fresh numbering space at `rank`.
    """
    text = text.strip()
    for pattern, kind, rank in CITE_PATTERNS:
        m = pattern.match(text)
        if m:
            return m.group(1).strip(), kind, rank
    return None, None, None


def cite_path(cite: str) -> str:
    """Slug used inside an id. `Artículo 14` -> `art14`, `B.2.6` -> `B.2.6`."""
    s = unicodedata.normalize("NFD", cite)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"^Art[ií]?culo\s*", "art", s, flags=re.I)
    s = re.sub(r"^Anejo\s*", "anejo", s, flags=re.I)
    s = re.sub(r"^Secci[oó]?n\s*", "sec", s, flags=re.I)
    s = re.sub(r"^Cap[ií]?tulo\s*", "cap", s, flags=re.I)
    s = re.sub(r"^T[ií]?tulo\s*", "tit", s, flags=re.I)
    return re.sub(r"\s+", "", s).rstrip(".")


# Rank of an unnumbered heading on the spine. Higher than any namespace rank, so
# it is always the innermost thing on the stack and never parents a numbered
# heading.
UNNUMBERED = 99


class Spine:
    """The heading stack, nested by printed cite rather than by adjacency.

    `parent_id` from most-recent-header was the prototype's load-bearing defect
    (#32): docling's `section_header` label carries no nesting level, so the walk
    climbed siblings -- `B.2.6.2 Vías de circulación` came back as a child of
    `B.2.6.1 Área de acceso`. The numbering already says `B.2.6.2` is a child of
    `B.2.6`, so this reads the cite. `SectionHeaderItem.level` is discarded
    outright; the emitted tree is inverted (#14).
    """

    def __init__(self):
        # entries: (parts, rank, id) -- parts is [] for a namespace heading
        self.stack = []

    def parent(self) -> str:
        return self.stack[-1][2] if self.stack else ""

    def push_numbered(self, cite: str, ident: str) -> str:
        parts = cite.split(".")
        while self.stack:
            parts_top, rank_top, _ = self.stack[-1]
            if rank_top == UNNUMBERED:
                self.stack.pop()                        # a leaf never parents a
                continue                                # numbered heading
            if rank_top is not None:
                break                                   # namespace: stop here
            if parts[: len(parts_top)] == parts_top and len(parts_top) < len(parts):
                break                                   # proper prefix: parent
            self.stack.pop()
        parent = self.parent()
        self.stack.append((parts, None, ident))
        return parent

    def push_namespace(self, rank: int, ident: str) -> str:
        while self.stack:
            _, rank_top, _ = self.stack[-1]
            if rank_top is not None and rank_top < rank:
                break                                   # coarser namespace: parent
            self.stack.pop()
        parent = self.parent()
        self.stack.append(([], rank, ident))
        return parent

    def push_unnumbered(self, ident: str) -> str:
        """An unnumbered heading is a leaf of the nearest numbered ancestor.

        It is not incidental: 33 of DccSUA's 209 unnumbered headings are binding
        normative text, including all 30 entries of Anejo A Terminología, which
        is where the document defines the terms its articulado cites (#12).
        """
        while self.stack and self.stack[-1][1] == UNNUMBERED:
            self.stack.pop()
        parent = self.parent()
        self.stack.append(([], UNNUMBERED, ident))
        return parent


# --------------------------------------------------------------------------- #
# ingest
# --------------------------------------------------------------------------- #

def load_provenance(doc: str) -> list[tuple[int, int, str]]:
    """Per-page-range extraction source, from the Stage 1 pipeline record.

    `*.pipeline.json` is document-level, and a document-level flag would
    disclaim HABITABILIDAD's native tail -- which is #21's own ground truth --
    so the ranges are explicit (#27).
    """
    cfg = json.loads((TUNED / f"{doc}.pipeline.json").read_text())
    if cfg.get("profile") != "ocr":
        return []
    ranges = cfg.get("ocr_page_ranges")
    if not ranges:
        sys.exit(f"{doc}.pipeline.json has profile 'ocr' but no ocr_page_ranges; "
                 f"rerun scripts/convert.py or backfill the measured ranges")
    return [(int(a), int(b), "ocr") for a, b in ranges]


def ingest_doc(doc: str, rows: list, stats: dict):
    data = json.loads((TUNED / f"{doc}.json").read_text())
    code = DOC_CODES.get(doc) or re.sub(r"[^A-Za-z0-9]", "", doc)[:3].upper()
    ocr_ranges = load_provenance(doc)
    pages = {int(k): v for k, v in data["pages"].items()}

    def is_ocr(page: int) -> bool:
        return any(a <= page <= b for a, b, _ in ocr_ranges)

    # Figure regions, per page. Text landing inside one is a figure label, not
    # body: `máx`, `Q;`, `eje`, `<30 cm PLANTA` sit physically between two
    # headers and would otherwise inherit the parent -- 18 of 24 children of one
    # HABITABILIDAD heading were figure noise. Figure *positions* stay in scope;
    # figure *content* does not (#3).
    #
    # A picture box that swallows a `section_header` or a `list_item` is not a
    # figure -- it is a mis-boxed page raster, which is the normal case in a
    # fully bitmap-rendered document. Containment alone would have eaten 2,670 of
    # HABITABILIDAD's 3,887 text items, i.e. most of the articulado; the
    # structural-item test disqualifies 6 boxes of 76 and brings that to 505.
    figures = defaultdict(list)
    for pic in data.get("pictures", []):
        for prov in pic.get("prov") or []:
            figures[prov.get("page_no")].append(prov["bbox"])
    for t in data.get("texts", []):
        if t.get("label") not in ("section_header", "list_item"):
            continue
        prov = (t.get("prov") or [{}])[0]
        if not prov:
            continue
        page_figs = figures.get(prov.get("page_no")) or []
        for box in list(page_figs):
            if inside(prov["bbox"], box):
                page_figs.remove(box)
                stats["figure_boxes_disqualified"] += 1

    # Table regions, so a text item docling also emitted inside a table is not
    # counted twice.
    table_boxes = defaultdict(list)
    for tab in data.get("tables", []):
        for prov in tab.get("prov") or []:
            table_boxes[prov.get("page_no")].append(prov["bbox"])

    items = []
    for t in data.get("texts", []):
        prov = (t.get("prov") or [{}])[0]
        if not prov:
            continue
        items.append((prov.get("page_no", 0), top_key(prov), "text", t, prov))
    for tab in data.get("tables", []):
        prov = (tab.get("prov") or [{}])[0]
        if not prov:
            continue
        items.append((prov.get("page_no", 0), top_key(prov), "table", tab, prov))
    # Figure *positions* are in scope even though figure content is not (#3), so
    # each picture lands as a record the agent can point at. They carry no text
    # -- 56 of 56 in HABITABILIDAD pp.1-94 are empty placeholders (#27) -- which
    # is exactly why the line art's manufactured `≤` never enters the substrate.
    for pic in data.get("pictures", []):
        prov = (pic.get("prov") or [{}])[0]
        if not prov:
            continue
        items.append((prov.get("page_no", 0), top_key(prov), "picture", pic, prov))
    # Reading order: page, then line, then left-to-right within the line. The
    # left tie-break is not cosmetic -- without it `B.2.6.3. Áreas de
    # aparcamiento` comes back as `B.2.6.3. de aparcamiento. Áreas`, because a
    # heading split across three boxes on one line has three near-identical
    # `t` values and no ordering between them.
    items.sort(key=lambda x: (x[0], round(x[1] / LINE_BAND), x[4].get("bbox", {}).get("l", 0.0)))

    spine = Spine()
    list_stack: list[tuple[float, str]] = []
    ids_seen = set()
    positional = defaultdict(int)

    def make_id(page: int, path: str | None) -> str:
        if path is None:
            positional[page] += 1
            path = f"§{positional[page]}"
        ident = f"{code}:p{page}:{path}"
        if ident in ids_seen:
            # The source itself is not internally consistent -- HABITABILIDAD
            # p.85 prints its Anexo II index as `1, 2, 2, 3` -- so a printed cite
            # locates but does not uniquely identify (#4). `id` is ours and
            # stays unique; `cite` keeps what the page prints.
            n = 2
            while f"{ident}~{n}" in ids_seen:
                n += 1
            ident = f"{ident}~{n}"
        ids_seen.add(ident)
        return ident

    for page, _, kind, node, prov in items:
        label = node.get("label")
        if label in FURNITURE_LABELS or node.get("content_layer") == "furniture":
            stats["furniture"] += 1
            continue

        bbox = prov.get("bbox") or {}
        # Captions survive the filter: they are how the agent points at a figure
        # it cannot read (#3).
        if (kind == "text" and label != "caption"
                and any(inside(bbox, f) for f in figures.get(page, []))):
            stats["figure_labels"] += 1
            continue
        if kind == "text" and any(inside(bbox, b) for b in table_boxes.get(page, [])):
            stats["in_table"] += 1
            continue

        ocr = is_ocr(page)

        if kind == "picture":
            cite = table_cite(node)
            caption = " ".join((c.get("text") or "") for c in node.get("captions") or []
                               if isinstance(c, dict)).strip()
            ident = make_id(page, cite_path(cite) if cite else None)
            rows.append(row(ident, doc, page, cite, spine.parent(), "picture",
                            caption, ocr))
            stats["pictures"] += 1
            continue

        if kind == "table":
            text = serialize_table(node)
            if text is None:
                stats["tables_skipped"] += 1
                continue
            cite = table_cite(node)
            parent = spine.parent()
            ident = make_id(page, cite_path(cite) if cite else None)
            rows.append(row(ident, doc, page, cite, parent, "table", text, ocr))
            stats["tables"] += 1
            continue

        raw = (node.get("text") or "").strip()
        if not raw:
            stats["empty"] += 1
            continue

        if label == "section_header":
            cite, ckind, rank = parse_cite(raw)
            ident = make_id(page, cite_path(cite) if cite else None)
            if ckind == "num":
                parent = spine.push_numbered(cite_path(cite), ident)
            elif ckind == "ns":
                parent = spine.push_namespace(rank, ident)
            else:
                parent = spine.push_unnumbered(ident)
                stats["unnumbered_headings"] += 1
            rows.append(row(ident, doc, page, cite or "", parent, "section_header", raw, ocr))
            list_stack.clear()
            stats["headings"] += 1
            continue

        parent = spine.parent()
        marker = (node.get("marker") or "").strip()
        cite = marker if MARKER_RE.match(marker) else ""
        if not cite and label == "list_item":
            m = INLINE_MARKER_RE.match(raw)
            if m:
                cite = m.group(1)

        if label == "list_item":
            # Nest sub-items under their own item, by indent. `art14.1.a`'s
            # encimera applies only under `art14.1`'s no-new-rooms condition, so
            # flattening every item onto its heading would put the qualifier out
            # of the ancestor chain that #4's read contract promises. Indent is
            # the signal that survived: `formatting` is empty corpus-wide (#14)
            # and the marker glyph is often the thing that went missing (#18).
            left = bbox.get("l", 0.0)
            while list_stack and list_stack[-1][0] >= left - INDENT_TOL:
                list_stack.pop()
            if list_stack:
                parent = list_stack[-1][1]

        if cite:
            base = parent.split(":", 2)[2] if parent.count(":") >= 2 else ""
            path = (f"{base}.{cite_path(cite)}"
                    if base and not base.startswith("§") else cite_path(cite))
        else:
            path = None
            if label == "list_item":
                # A provision printed without a recoverable marker is faithfully
                # extracted -- addressability is a fact about the source, not an
                # extraction defect (#27). It still gets a positional id, and its
                # empty `cite` is what says it is unaddressed (#4).
                stats["unaddressed_items"] += 1
        ident = make_id(page, path)
        if label == "list_item":
            list_stack.append((bbox.get("l", 0.0), ident))
        rows.append(row(ident, doc, page, cite, parent, label, raw, ocr))
        stats["body"] += 1


def serialize_table(node) -> str | None:
    """One record per table -- atomic on read (#4), cells inline for search.

    #32 collapsed the substrate to a single `corpus.tsv` and dropped the
    separate `<DOC>.cells.tsv` projection, so the cells have to be searchable
    inside the table's own record. Returns None where the grid does not resolve
    (#4, decision 4): p.50 merges two logical tables.
    """
    data = node.get("data") or {}
    cells = data.get("table_cells") or []
    if not cells:
        return None
    n_rows, n_cols = data.get("num_rows") or 0, data.get("num_cols") or 0
    if not n_rows or not n_cols:
        return None
    grid = [["" for _ in range(n_cols)] for _ in range(n_rows)]
    for c in cells:
        r0, c0 = c.get("start_row_offset_idx", 0), c.get("start_col_offset_idx", 0)
        if 0 <= r0 < n_rows and 0 <= c0 < n_cols:
            grid[r0][c0] = (c.get("text") or "").strip()
    if not any(any(r) for r in grid):
        return None
    return " ¶ ".join(" | ".join(cell for cell in r) for r in grid)


def table_cite(node) -> str:
    for cap in node.get("captions") or []:
        text = (cap.get("text") or "") if isinstance(cap, dict) else ""
        cite, _, _ = parse_cite(text)
        if cite:
            return cite
    return ""


def row(ident, doc, page, cite, parent, label, raw, ocr) -> dict:
    text = repair(raw, ocr)
    return {"id": ident, "doc": doc, "page": page, "cite": cite,
            "parent_id": parent, "label": label, "text": text,
            "norm": normalize(text)}


def write_tsv(path: Path, columns: list[str], rows: list[dict]) -> None:
    """Plain TSV -- no quoting, no escaping, so `awk -F'\\t'` and `cut` just work.

    The substrate is read by line-oriented shell tools (#33), which do not
    implement RFC 4180. Fields are therefore made tab- and newline-free on the
    way in rather than quoted on the way out; `repair()` and `normalize()`
    already collapse whitespace, and this is the backstop.
    """
    with path.open("w") as fh:
        fh.write("\t".join(columns) + "\n")
        for r in rows:
            fh.write("\t".join(
                str(r.get(c, "")).replace("\t", " ").replace("\n", " ").replace("\r", " ")
                for c in columns) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    global TUNED
    ap.add_argument("--tuned", type=Path, default=TUNED)
    ap.add_argument("--out", type=Path, default=REPO / "corpus/corpus.tsv")
    ap.add_argument("--docs", nargs="*", default=DOCS)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args(argv)
    TUNED = args.tuned

    rows: list[dict] = []
    stats = defaultdict(int)
    prov_rows = []
    for doc in args.docs:
        before = len(rows)
        ingest_doc(doc, rows, stats)
        n_pages = len(json.loads((TUNED / f"{doc}.json").read_text())["pages"])
        ocr = load_provenance(doc)
        if ocr:
            covered = sorted(ocr)
            prov_rows += [{"doc": doc, "page_from": a, "page_to": b, "source": "ocr"}
                          for a, b, _ in covered]
            cursor = 1
            for a, b, _ in covered:
                if cursor < a:
                    prov_rows.append({"doc": doc, "page_from": cursor,
                                      "page_to": a - 1, "source": "native"})
                cursor = b + 1
            if cursor <= n_pages:
                prov_rows.append({"doc": doc, "page_from": cursor,
                                  "page_to": n_pages, "source": "native"})
        else:
            prov_rows.append({"doc": doc, "page_from": 1, "page_to": n_pages,
                              "source": "native"})
        if args.stats:
            print(f"{doc}: {len(rows) - before} records", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_tsv(args.out, COLUMNS, rows)

    prov_path = args.out.with_name("corpus.provenance.tsv")
    prov_rows.sort(key=lambda r: (r["doc"], r["page_from"]))
    write_tsv(prov_path, ["doc", "page_from", "page_to", "source"], prov_rows)

    print(f"{len(rows)} records -> {args.out}", file=sys.stderr)
    print(f"{len(prov_rows)} ranges -> {prov_path}", file=sys.stderr)
    if args.stats:
        for k in sorted(stats):
            print(f"  {k}: {stats[k]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
