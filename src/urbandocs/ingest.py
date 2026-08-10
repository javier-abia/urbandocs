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
    uv run -m urbandocs.ingest                     # writes corpus/corpus.tsv
    uv run -m urbandocs.ingest --out /tmp/c.tsv --stats
"""

# TODO: Create a plan on how to facilitate the modification of the script on
# new versions of docling output.

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from urbandocs import paths

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# Named shapes instead of bare `dict`/`list`: ty treats missing-type-argument
# as an error (#48), and a bare `dict` silently turns off checking downstream.

#: A node of docling's JSON, straight off `json.loads`. Untyped on purpose --
#: the schema is the converter's, not ours; reads use `.get()` with defaults.
Node = dict[str, Any]

#: A bounding box in docling's BOTTOMLEFT coordinates: `l`, `r`, `t`, `b`.
Box = dict[str, float]


class Row(TypedDict):
    """One corpus record, keyed by `COLUMNS`.

    A TypedDict rather than `dict[str, object]`, so fields keep their real
    types (`page` is `int`, the rest are `str`) instead of reading as `object`.
    """

    id: str
    doc: str
    page: int
    cite: str
    parent_id: str
    label: str
    text: str
    norm: str


class ProvRow(TypedDict):
    """One row of `corpus.provenance.tsv`: a page range and how it was extracted."""

    doc: str
    page_from: int
    page_to: int
    source: str


DOCS = ["DccSUA", "DOG_2025", "dog-habitabilidad", "PGOM"]

# Short code used in ids, hand-set because ids are read aloud in citations;
# an unlisted doc falls back to its first three alphanumerics upper-cased.
# `dog-habitabilidad` is pinned to `D128` rather than the derived `DOG`
# (would collide with DOG_2025) or `HAB` (stale after Decreto 128/2023
# renumbered every page) (#39, #41).
DOC_CODES = {"DccSUA": "SUA", "DOG_2025": "DOG", "dog-habitabilidad": "D128"}


def doc_code(doc: str) -> str:
    """The short key minted into ids and, per #57, the `doc` column -- so a
    citation like `D128:p43:§6` agrees with its row's `doc` field (#42)."""
    return DOC_CODES.get(doc) or re.sub(r"[^A-Za-z0-9]", "", doc)[:3].upper()


COLUMNS = ["id", "doc", "page", "cite", "parent_id", "label", "text", "norm"]

# Label-based, not containment-based: `furniture.children` is empty in all
# three documents (#14). DOG_2025's `Pág.` markers are labelled `text`, so
# they survive this filter, which is what #8 wants.
FURNITURE_LABELS = {"page_header", "page_footer"}

# The one furniture residue the label filter misses: both Diario Oficial docs
# print a running `DOG Núm. NNN` masthead labelled `text`, not `page_header`
# (49 pages of Decreto 128/2023, 21 of DOG_2025). Matched on its own shape,
# not `Núm.`, so the neighboring `Pág. NNN` page citation survives (#8, #14).
# On 6 pages it's appended to the trailing body paragraph instead of standing
# alone, so it's stripped from the end of the field rather than matched whole.
RUNNING_HEADER_RE = re.compile(r"\s*DOG\s+N[uú]m\.\s*[\d.]+\s*$")

# Private-use codepoints are a fixed Symbol-font mapping, verified in context
# (#14). Decoding them recovers the character the page prints; it asserts
# nothing about meaning, so it applies to `text` as well as `norm`.
SYMBOL_MAP = {"\uf0b1": "±", "\uf061": "α", "\uf044": "Δ", "\uf06d": "μ"}

# Subscripts split by extraction in body text (`R d` for `Rd`), while the same
# document holds the correct `R _ { d }` inside its LaTeX (#14). Rejoined in
# `norm` only; query-side normalization runs the same function, so both
# spellings reach the same key.
SUBSCRIPT_PAIRS = [("R", "d"), ("C", "1"), ("B", "o"), ("U", "d"), ("R", "c")]

# Line-break hyphens (`super -ficie`) split terms the sweep depends on and
# must be rejoined; parenthetical dashes (`espacios libres -públicos o
# privados- que`) must not be. Discriminator: parenthetical dashes pair (open
# + close), line-break hyphens never close. Window (200) is set above the
# longest observed pair (55 chars, measured across the corpus's 219 sites)
# (#32, #41).
DASH_PAIR_WINDOW = 200
DASH_OPEN_RE = re.compile(r"(?<=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])\s+-(?=[a-záéíóúüñ])")
DASH_CLOSE_RE = re.compile(r"(?<=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])-(?=[\s,.;:)]|$)")


def rejoin_hyphens(s: str) -> str:
    """Close line-break hyphens, leave paired parenthetical dashes standing.

    Runs on `norm` only. `text` keeps what the page prints, because a citation
    promises a location and never that the string matches glyph for glyph (#8);
    rewriting the verbatim text to make it searchable would trade the one
    guarantee the engine does make for the one it does not.
    """
    protected = set()
    for m in DASH_OPEN_RE.finditer(s):
        close = DASH_CLOSE_RE.search(s, m.end(), m.end() + DASH_PAIR_WINDOW)
        if close:
            protected.add(m.start())
            protected.add(close.start())

    out, i = [], 0
    for m in DASH_OPEN_RE.finditer(s):
        if m.start() in protected:
            continue
        out.append(s[i : m.start()])
        i = m.end()
    out.append(s[i:])
    s = "".join(out)

    # Mirrored shape (`simi- lares`), rare (2 sites, DccSUA). Same pairing
    # rule; re-derived since offsets moved after the first pass.
    protected = set()
    for m in DASH_OPEN_RE.finditer(s):
        close = DASH_CLOSE_RE.search(s, m.end(), m.end() + DASH_PAIR_WINDOW)
        if close:
            protected.add(close.start())
    out, i = [], 0
    for m in re.finditer(r"(?<=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])-\s+(?=[a-záéíóúüñ])", s):
        if m.start() in protected:
            continue
        out.append(s[i : m.start()])
        i = m.end()
    out.append(s[i:])
    return "".join(out)


# A section header's printed cite. Ordered: the longest, most specific shapes
# first, so `Artículo 14.` does not match the bare-number rule.
CITE_PATTERNS = [
    # namespace headings -- they open a numbering space rather than sit in one
    (re.compile(r"^(Anejo\s+[A-Z])\b", re.IGNORECASE), "ns", 1),
    (re.compile(r"^(Secci[oó]n\s+[A-Z]*\s*[0-9]+)\b", re.IGNORECASE), "ns", 1),
    (re.compile(r"^(Cap[ií]tulo\s+[IVXLC0-9]+)\b", re.IGNORECASE), "ns", 1),
    (re.compile(r"^(T[ií]tulo\s+[IVXLC0-9]+)\b", re.IGNORECASE), "ns", 1),
    (re.compile(r"^(Art[ií]culo\s+[0-9]+)\b", re.IGNORECASE), "ns", 2),
    # dotted numbering -- `B.2.6.2`, `A.1.1`, `4.1`, `12`
    (re.compile(r"^([A-Z]\.[0-9]+(?:\.[0-9]+)*)\.?(?=[\s.]|$)"), "num", None),
    (re.compile(r"^([0-9]+(?:\.[0-9]+)*)\.?(?=\s|$)"), "num", None),
]

# List markers, as printed: `a)`, `1.`, `iv)`. Nothing here guesses an ordinal --
# an item whose marker cannot be read stays unaddressed rather than being
# numbered by position (#18).
MARKER_RE = re.compile(r"^\s*([0-9]+|[a-zA-Z]|[ivxIVX]+)\s*[.)]\s*$")

# DccSUA/DOG_2025 print the marker inline in `text` (`1 La anchura...`)
# rather than in `marker`, so it needs parsing, not recovery (#18).
INLINE_MARKER_RE = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)*|[a-z]|[ivx]+)\s*[).]?\s+(?=[A-ZÁÉÍÓÚÜÑ])"
)

# Vertical indent step, in points, that separates a nested list item from its
# sibling. HABITABILIDAD prints top-level items at `bbox.l` ~70 and their
# sub-items at ~83.5 -- the same ~13 pt gutter #18 read the eaten markers out of.
INDENT_TOL = 6.0

# A heading docling mislabelled `list_item`: in Decreto 128/2023, 77 of 114
# letter-dotted headings arrive this way, leaving the spine without `A.2`
# etc. and misattributing provisions on pp.19-22 to a stale ancestor (#8).
# Keyed on the letter-dotted shape `parse_cite` already recognises; promotes
# 0 items in DccSUA/DOG_2025's own numbering schemes, and the contents-page
# matches (pp.14-17) are harmless since nesting is by cite prefix (#32).
PROMOTABLE_HEADING_RE = re.compile(r"^[A-Z]\.[0-9]+(?:\.[0-9]+)*\.?\s+\S")
# Guard against a paragraph that merely opens with a cite it is talking about.
# Rejects nothing in the current corpus -- every promoted item is 11-99 chars.
MAX_PROMOTED_HEADING = 100


# --------------------------------------------------------------------------- #
# text repair and normalization
# --------------------------------------------------------------------------- #


def repair(text: str, ocr: bool) -> str:
    """Deterministic repairs on the rendered `text` (#28).

    Not on this list, deliberately: `m2 -> m²` (source itself writes `m2`,
    readers handle it fine, #21); `>` -> `≥` (roughly 1 in 8 comparisons is
    genuinely strict, #21); standalone `0` -> `o` (query-side equivalence
    only, since `0` is also a legitimate digit, #14/#28).
    """
    for bad, good in SYMBOL_MAP.items():
        text = text.replace(bad, good)
    text = text.replace("><", "×")
    if ocr:
        # OCR encodes `m²` as `m?` (superscript 2 not recognized), never a
        # real `?` in this corpus (#11).
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
    s = rejoin_hyphens(s)
    for head, tail in SUBSCRIPT_PAIRS:
        s = re.sub(rf"\b{head}\s+{tail}\b", f"{head}{tail}", s)
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    # unit folding -- all three spellings occur (107 / 67 / 35 corpus-wide)
    return re.sub(r"\bm\s*[²2?]", "m2", s)


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #


def top_key(prov: Node) -> float:
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


def inside(box: Box, outer: Box, pad: float = 2.0) -> bool:
    """Is `box` contained in `outer`? Both must be BOTTOMLEFT."""
    if not box or not outer:
        return False
    lo_b, hi_b = min(box["t"], box["b"]), max(box["t"], box["b"])
    lo_o, hi_o = min(outer["t"], outer["b"]), max(outer["t"], outer["b"])
    return (
        box["l"] >= outer["l"] - pad
        and box["r"] <= outer["r"] + pad
        and lo_b >= lo_o - pad
        and hi_b <= hi_o + pad
    )


# --------------------------------------------------------------------------- #
# cites and the heading spine
# --------------------------------------------------------------------------- #


def parse_cite(text: str) -> tuple[str | None, str | None, int | None]:
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
    s = re.sub(r"^Art[ií]?culo\s*", "art", s, flags=re.IGNORECASE)
    s = re.sub(r"^Anejo\s*", "anejo", s, flags=re.IGNORECASE)
    s = re.sub(r"^Secci[oó]?n\s*", "sec", s, flags=re.IGNORECASE)
    s = re.sub(r"^Cap[ií]?tulo\s*", "cap", s, flags=re.IGNORECASE)
    s = re.sub(r"^T[ií]?tulo\s*", "tit", s, flags=re.IGNORECASE)
    # Trailing punctuation (`a)`, `1.`) belongs to the printed cite, not the
    # address: `cite` keeps it, `id` strips it.
    return re.sub(r"\s+", "", s).rstrip(".)")


# Rank of an unnumbered heading on the spine. Higher than any namespace rank, so
# it is always the innermost thing on the stack and never parents a numbered
# heading.
UNNUMBERED = 99


class Spine:
    """The heading stack, nested by printed cite rather than by adjacency.

    Nesting by most-recent-header was the prototype's defect (#32): docling's
    `section_header` label carries no nesting level, so `B.2.6.2` came back
    as a sibling's child instead of `B.2.6`'s. This reads the cite instead
    and discards `SectionHeaderItem.level` outright (#14).
    """

    def __init__(self) -> None:
        # (parts, rank, id): parts is [] for a namespace heading; rank is
        # None for dotted numbering, which `push_numbered` reads to tell
        # "still in this numbering space" from "hit the namespace above it".
        self.stack: list[tuple[list[str], int | None, str]] = []

    def parent(self) -> str:
        return self.stack[-1][2] if self.stack else ""

    def push_numbered(self, cite: str, ident: str) -> str:
        parts = cite.split(".")
        while self.stack:
            parts_top, rank_top, _ = self.stack[-1]
            if rank_top == UNNUMBERED:
                self.stack.pop()  # a leaf never parents a
                continue  # numbered heading
            if rank_top is not None:
                break  # namespace: stop here
            if parts[: len(parts_top)] == parts_top and len(parts_top) < len(parts):
                break  # proper prefix: parent
            self.stack.pop()
        parent = self.parent()
        self.stack.append((parts, None, ident))
        return parent

    def push_namespace(self, rank: int, ident: str) -> str:
        while self.stack:
            _, rank_top, _ = self.stack[-1]
            if rank_top is not None and rank_top < rank:
                break  # coarser namespace: parent
            self.stack.pop()
        parent = self.parent()
        self.stack.append(([], rank, ident))
        return parent

    def push_unnumbered(self, ident: str) -> str:
        """An unnumbered heading is a leaf of the nearest numbered ancestor.

        Not incidental: 33 of DccSUA's 209 unnumbered headings are binding
        normative text, including Anejo A Terminología (#12).
        """
        while self.stack and self.stack[-1][1] == UNNUMBERED:
            self.stack.pop()
        parent = self.parent()
        self.stack.append(([], UNNUMBERED, ident))
        return parent


# --------------------------------------------------------------------------- #
# ingest
# --------------------------------------------------------------------------- #


def load_provenance(doc: str, *, tuned: Path) -> list[tuple[int, int, str]]:
    """Per-page-range extraction source, from the Stage 1 pipeline record.

    Ranges are explicit rather than a document-level flag, which would
    disclaim HABITABILIDAD's native tail -- #21's own ground truth (#27).
    `tuned` is a parameter, not a module global, so tests can use different
    fixture roots in one process (#46).
    """
    cfg = json.loads((tuned / f"{doc}.pipeline.json").read_text())
    if cfg.get("profile") != "ocr":
        return []
    ranges = cfg.get("ocr_page_ranges")
    if not ranges:
        sys.exit(
            f"{doc}.pipeline.json has profile 'ocr' but no ocr_page_ranges; "
            f"rerun scripts/convert.py or backfill the measured ranges"
        )
    return [(int(a), int(b), "ocr") for a, b in ranges]


def ingest_doc(
    doc: str, rows: list[Row], stats: dict[str, int], *, tuned: Path
) -> None:
    data = json.loads((tuned / f"{doc}.json").read_text())
    code = doc_code(doc)
    ocr_ranges = load_provenance(doc, tuned=tuned)

    def is_ocr(page: int) -> bool:
        return any(a <= page <= b for a, b, _ in ocr_ranges)

    # Text inside a figure region is a figure label, not body text (#3): 18 of
    # 24 children of one HABITABILIDAD heading were figure noise. A box that
    # swallows a `section_header`/`list_item` is a mis-boxed page raster, not
    # a real figure -- containment alone would have eaten 2,670 of
    # HABITABILIDAD's 3,887 text items; this test brings that down to 505.
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
    # Figure positions stay in scope even though content doesn't (#3); pictures
    # carry no text (56/56 in HABITABILIDAD pp.1-94 are empty placeholders, #27).
    for pic in data.get("pictures", []):
        prov = (pic.get("prov") or [{}])[0]
        if not prov:
            continue
        items.append((prov.get("page_no", 0), top_key(prov), "picture", pic, prov))
    # Reading order: page, then line, then left-to-right. The left tie-break
    # matters -- without it, a heading split across boxes on one line can come
    # back reordered, since same-line `t` values are near-identical.
    items.sort(
        key=lambda x: (
            x[0],
            round(x[1] / LINE_BAND),
            x[4].get("bbox", {}).get("l", 0.0),
        )
    )

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
            # Printed cites aren't always unique (HABITABILIDAD p.85's Anexo
            # II index repeats "2"): `id` stays unique, `cite` keeps what the
            # page prints (#4).
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
        if (
            kind == "text"
            and label != "caption"
            and any(inside(bbox, f) for f in figures.get(page, []))
        ):
            stats["figure_labels"] += 1
            continue
        if kind == "text" and any(inside(bbox, b) for b in table_boxes.get(page, [])):
            stats["in_table"] += 1
            continue

        ocr = is_ocr(page)

        if kind == "picture":
            cite = table_cite(node)
            caption = " ".join(
                (c.get("text") or "")
                for c in node.get("captions") or []
                if isinstance(c, dict)
            ).strip()
            ident = make_id(page, cite_path(cite) if cite else None)
            rows.append(
                row(ident, code, page, cite, spine.parent(), "picture", caption, ocr)
            )
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
            rows.append(row(ident, code, page, cite, parent, "table", text, ocr))
            stats["tables"] += 1
            continue

        raw = (node.get("text") or "").strip()
        if not raw:
            stats["empty"] += 1
            continue

        stripped = RUNNING_HEADER_RE.sub("", raw)
        if stripped != raw:
            stats["running_header"] += 1
            raw = stripped.strip()
            if not raw:
                continue

        if (
            label in ("list_item", "text")
            and len(raw) <= MAX_PROMOTED_HEADING
            and PROMOTABLE_HEADING_RE.match(raw)
        ):
            label = "section_header"
            stats["promoted_headings"] += 1

        if label == "section_header":
            cite, ckind, rank = parse_cite(raw)
            ident = make_id(page, cite_path(cite) if cite else None)
            # `parse_cite`'s slots are correlated (`num` always carries a
            # cite, `ns` always carries a rank) but the type is a plain
            # tuple, so the invariant is asserted here rather than left implicit.
            if ckind == "num":
                assert cite is not None
                parent = spine.push_numbered(cite_path(cite), ident)
            elif ckind == "ns":
                assert rank is not None
                parent = spine.push_namespace(rank, ident)
            else:
                parent = spine.push_unnumbered(ident)
                stats["unnumbered_headings"] += 1
            rows.append(
                row(ident, code, page, cite or "", parent, "section_header", raw, ocr)
            )
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
            # Nest sub-items under their own item, by indent, so a qualifier
            # like `art14.1.a` stays under `art14.1` in the ancestor chain
            # (#4). Indent is the surviving signal: `formatting` is empty
            # corpus-wide and the marker glyph often goes missing (#14, #18).
            left = bbox.get("l", 0.0)
            while list_stack and list_stack[-1][0] >= left - INDENT_TOL:
                list_stack.pop()
            if list_stack:
                parent = list_stack[-1][1]

        if cite:
            base = parent.split(":", 2)[2] if parent.count(":") >= 2 else ""
            path = (
                f"{base}.{cite_path(cite)}"
                if base and not base.startswith("§")
                else cite_path(cite)
            )
        else:
            path = None
            if label == "list_item":
                # Extracted faithfully even with no recoverable marker --
                # addressability is a source fact, not an extraction defect
                # (#27). Gets a positional id; empty `cite` marks it unaddressed (#4).
                stats["unaddressed_items"] += 1
        ident = make_id(page, path)
        if label == "list_item":
            list_stack.append((bbox.get("l", 0.0), ident))
        rows.append(row(ident, code, page, cite, parent, label, raw, ocr))
        stats["body"] += 1


def serialize_table(node: Node) -> str | None:
    """One record per table -- atomic on read (#4), cells inline for search
    since #32 dropped the separate `<DOC>.cells.tsv` projection.

    Returns None where the grid doesn't resolve, e.g. p.50 merges two
    logical tables (#4, decision 4).
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


def table_cite(node: Node) -> str:
    for cap in node.get("captions") or []:
        text = (cap.get("text") or "") if isinstance(cap, dict) else ""
        cite, _, _ = parse_cite(text)
        if cite:
            return cite
    return ""


def row(
    ident: str,
    doc: str,
    page: int,
    cite: str,
    parent: str,
    label: str,
    raw: str,
    ocr: bool,
) -> Row:
    text = repair(raw, ocr)
    return {
        "id": ident,
        "doc": doc,
        "page": page,
        "cite": cite,
        "parent_id": parent,
        "label": label,
        "text": text,
        "norm": normalize(text),
    }


def write_tsv(
    path: Path, columns: list[str], rows: Sequence[Mapping[str, object]]
) -> None:
    """Plain TSV -- no quoting, no escaping, so `awk -F'\\t'` and `cut` just
    work with the line-oriented shell tools that read the substrate (#33).
    Fields are stripped of tabs/newlines here as a backstop, rather than
    quoted, since `repair()`/`normalize()` already collapse whitespace.
    """
    with path.open("w") as fh:
        fh.write("\t".join(columns) + "\n")
        for r in rows:
            fh.write(
                "\t".join(
                    str(r.get(c, ""))
                    .replace("\t", " ")
                    .replace("\n", " ")
                    .replace("\r", " ")
                    for c in columns
                )
                + "\n"
            )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="uv run -m urbandocs.ingest",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repo root; defaults to $URBANDOCS_ROOT or the enclosing repo",
    )
    ap.add_argument("--tuned", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--docs", nargs="*", default=DOCS)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args(argv)

    # Resolved after parsing, not as argparse defaults: a default evaluated at
    # import time would make the module unimportable outside a repo (#46).
    tuned = args.tuned or paths.tuned_dir(args.root)
    out = args.out or paths.corpus_tsv(args.root)

    rows: list[Row] = []
    stats: defaultdict[str, int] = defaultdict(int)
    prov_rows: list[ProvRow] = []
    for doc in args.docs:
        before = len(rows)
        ingest_doc(doc, rows, stats, tuned=tuned)
        code = doc_code(doc)
        n_pages = len(json.loads((tuned / f"{doc}.json").read_text())["pages"])
        ocr = load_provenance(doc, tuned=tuned)
        if ocr:
            covered = sorted(ocr)
            prov_rows += [
                {"doc": code, "page_from": a, "page_to": b, "source": "ocr"}
                for a, b, _ in covered
            ]
            cursor = 1
            for a, b, _ in covered:
                if cursor < a:
                    prov_rows.append(
                        {
                            "doc": code,
                            "page_from": cursor,
                            "page_to": a - 1,
                            "source": "native",
                        }
                    )
                cursor = b + 1
            if cursor <= n_pages:
                prov_rows.append(
                    {
                        "doc": code,
                        "page_from": cursor,
                        "page_to": n_pages,
                        "source": "native",
                    }
                )
        else:
            prov_rows.append(
                {"doc": code, "page_from": 1, "page_to": n_pages, "source": "native"}
            )
        if args.stats:
            print(f"{doc}: {len(rows) - before} records", file=sys.stderr)

    out.parent.mkdir(parents=True, exist_ok=True)
    write_tsv(out, COLUMNS, rows)

    prov_path = out.with_name("corpus.provenance.tsv")
    prov_rows.sort(key=lambda r: (r["doc"], r["page_from"]))
    write_tsv(prov_path, ["doc", "page_from", "page_to", "source"], prov_rows)

    print(f"{len(rows)} records -> {out}", file=sys.stderr)
    print(f"{len(prov_rows)} ranges -> {prov_path}", file=sys.stderr)
    if args.stats:
        for k in sorted(stats):
            print(f"  {k}: {stats[k]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
