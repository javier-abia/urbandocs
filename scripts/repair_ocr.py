#!/usr/bin/env python3
"""Repair the three measured OCR defects in a tuned docling document.

Runs *after* Stage 1 (`tools/docling-convert/main.py`) and needs no GPU, no ML
packages and no reconversion -- only tesseract and a PDF renderer. docling's OCR
engine is EasyOCR, and none of these three is fixable by a docling setting:

  A  lines it dropped silently   65 lines on 34 of HABITABILIDAD's 94 OCR'd
                                 pages, plus same-row losses where a TOC entry
                                 kept its marker and lost its title (#17)
  B  comparison operators        `latin_g2` has no `≥`/`≤` glyph at all, so the
                                 document holds zero of them (#21)
  C  list markers                29 of 248 markable items kept theirs, and this
                                 corpus cross-references *by marker* (#18)

then a gate:

  D  line-coverage acceptance    fails if ink that reads as text is still
                                 uncovered after A (#17)

Nothing here rewrites text that is already present and complete. Pass A only
*adds* -- whole lines docling never saw, and words missing from the end of a line
it did see. A wholesale replacement would regress every measurement on the map
for no measured gain.

No document in the corpus needs this today. HABITABILIDAD, the scanned edition
these three defects were measured on, was replaced by the natively-typeset DOG
decree (#39, #41), so every document now converts under the `text-layer` profile
and this script exits on the profile check. It stays for the next scanned PDF the
corpus takes on -- the defects are EasyOCR's, not that document's.

Usage:
    python3 scripts/repair_ocr.py --doc <NAME> --dry-run
    python3 scripts/repair_ocr.py --doc <NAME>
"""

from __future__ import annotations

import argparse
import csv
import difflib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PDF_DIR = REPO / "documentos"
TUNED = REPO / "documentos/documentos-docling/docling-tuned"

TESSDATA = os.environ.get("TESSDATA_PREFIX", "/usr/share/tessdata")

DPI = 200
PT = 72.0 / DPI

# `²` comes back from no engine and folds to `m2` at ingest, which the source
# itself writes in places (#21).
OPERATORS = {"≥", "≤"}

# Tesseract word confidence below this is noise rather than a reading.
MIN_CONF = 40

# An item is only extended when the page holds at least this many more words
# inside its own bbox than the item has. Two absorbs ordinary tokenisation
# disagreement; the measured same-row losses are whole titles.
EXTEND_MARGIN = 3

# Tallest band, in pixels at the coverage script's 150 dpi, that can still be a
# dropped text line. Body lines measure 10-15 px; five of them is generous and
# still an order of magnitude below a full-page graphic.
MAX_DROP_BAND_PX = 75


# --------------------------------------------------------------------------- #
# tesseract
# --------------------------------------------------------------------------- #

def tess(image: Path, lang: str, psm: str, oem: str | None = None,
         tsv: bool = False) -> str:
    """Run tesseract. Flags go *before* the image.

    tesseract treats trailing bare words as config names, so a flag after the
    output base gets swallowed -- and asking for `tsv` from a tessdata directory
    that holds only `*.traineddata` produces no output at all, silently, because
    `tsv` is a config file that lives in `configs/`.
    """
    cmd = ["tesseract", "--tessdata-dir", TESSDATA, "-l", lang, "--psm", psm]
    if oem:
        cmd += ["--oem", oem]
    cmd += [str(image), "stdout"]
    if tsv:
        cmd.append("tsv")
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    return proc.stdout


def render(pdf: Path, page: int, tmp: Path) -> Path:
    png = tmp / f"p{page}.png"
    if not png.exists():
        subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(DPI),
                        "-gray", "-png", str(pdf), str(tmp / f"p{page}")],
                       check=True, capture_output=True)
        made = sorted(tmp.glob(f"p{page}-*.png"))
        if made:
            made[0].rename(png)
    return png


def crop(image: Path, box: tuple[int, int, int, int], dest: Path) -> Path:
    left, top, right, bottom = box
    subprocess.run(["magick", str(image), "-crop",
                    f"{right - left}x{bottom - top}+{left}+{top}", "+repage",
                    str(dest)], check=True, capture_output=True)
    return dest


def page_lines(png: Path) -> list[dict]:
    """Tesseract's reading of a whole page, grouped into lines.

    Each line carries its pixel box and its words. `--psm 3` is full automatic
    page segmentation: this is the *full-page* read #17 found already contains 58
    of the 65 lines region OCR dropped.
    """
    raw = tess(png, "spa", "3", tsv=True)
    if not raw.strip():
        return []
    rows = list(csv.DictReader(io.StringIO(raw), delimiter="\t",
                               quoting=csv.QUOTE_NONE))
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            conf = float(row.get("conf") or -1)
            box = (int(row["left"]), int(row["top"]),
                   int(row["width"]), int(row["height"]))
        except (TypeError, ValueError, KeyError):
            continue
        if conf < MIN_CONF:
            continue
        key = (row.get("block_num"), row.get("par_num"), row.get("line_num"))
        grouped[key].append({"text": text, "box": box})

    lines = []
    for words in grouped.values():
        words.sort(key=lambda w: w["box"][0])
        left = min(w["box"][0] for w in words)
        top = min(w["box"][1] for w in words)
        right = max(w["box"][0] + w["box"][2] for w in words)
        bottom = max(w["box"][1] + w["box"][3] for w in words)
        lines.append({"words": words, "box": (left, top, right, bottom),
                      "text": " ".join(w["text"] for w in words)})
    lines.sort(key=lambda l: (l["box"][1], l["box"][0]))
    return lines


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #

def to_pixels(bbox: dict, height: float) -> tuple[float, float, float, float]:
    """docling BOTTOMLEFT points -> top-left pixels at DPI."""
    top_pt = max(bbox["t"], bbox["b"])
    bottom_pt = min(bbox["t"], bbox["b"])
    return (bbox["l"] / PT, (height - top_pt) / PT,
            bbox["r"] / PT, (height - bottom_pt) / PT)


def to_points(box: tuple[int, int, int, int], height: float) -> dict:
    left, top, right, bottom = box
    return {"l": left * PT, "r": right * PT,
            "t": height - top * PT, "b": height - bottom * PT,
            "coord_origin": "BOTTOMLEFT"}


def centre_inside(word_box, item_px, pad: float = 4.0) -> bool:
    cx = word_box[0] + word_box[2] / 2.0
    cy = word_box[1] + word_box[3] / 2.0
    return (item_px[0] - pad <= cx <= item_px[2] + pad
            and item_px[1] - pad <= cy <= item_px[3] + pad)


def overlaps(a: dict, b: dict, pad: float = 2.0) -> bool:
    a_lo, a_hi = min(a["t"], a["b"]), max(a["t"], a["b"])
    b_lo, b_hi = min(b["t"], b["b"]), max(b["t"], b["b"])
    return not (a["r"] < b["l"] - pad or a["l"] > b["r"] + pad
                or a_hi < b_lo - pad or a_lo > b_hi + pad)


def boxes_by_page(data: dict, keys=("pictures", "tables")) -> dict:
    out = defaultdict(list)
    for key in keys:
        for node in data.get(key, []):
            for prov in node.get("prov") or []:
                out[prov["page_no"]].append(prov["bbox"])
    return out


def items_on(data: dict, page: int) -> list[dict]:
    return [t for t in data.get("texts", [])
            if (t.get("prov") or [{}])[0].get("page_no") == page]


# --------------------------------------------------------------------------- #
# pass A -- recover what region OCR dropped
# --------------------------------------------------------------------------- #

MARKER_START = re.compile(r"^\s*([0-9]{1,2}|[a-zA-Z]|[ivxIVX]{1,4})\s*[.)]\s+")


def recover_dropped_text(pdf: Path, data: dict, pages: list[int], tmp: Path,
                         stats: dict) -> None:
    """Add back the lines and words EasyOCR's region pass lost (#17).

    Two loss classes, both measured:

    - **whole lines**, 65 of them, and not only leading lines -- 7 of 48 are a
      block's *last* line, so "check the first line" is not a repair;
    - **same-row losses**, where the OCR read part of the line: 20 of the 83
      index entries on pp.31-33 survive as a bare marker with the title dropped,
      which is invisible to any check that asks "did anything land on this row".

    Only additive, and **line-driven rather than box-driven**. The first cut
    matched words against each item's own bbox, which structurally cannot see the
    TOC losses: p.31's `A.1.1.` is 26 pt wide because it *is* only the marker, so
    the dropped title lies outside the very box you would search. Working from
    tesseract's line grouping instead asks the right question -- what does this
    row of the page say, and what did docling get from it.

    Extending also widens the item's bbox to the line. Without that the text is
    fixed but the ink stays uncovered, and the acceptance gate keeps reporting a
    loss that is no longer there.
    """
    figures = boxes_by_page(data, ("pictures",))
    sizes = {int(k): v["size"] for k, v in data["pages"].items()}
    next_ref = len(data.get("texts", []))

    for page in pages:
        png = render(pdf, page, tmp)
        if not png.exists():
            continue
        lines = page_lines(png)
        if not lines:
            continue
        size = sizes.get(page) or {"height": 841.92, "width": 595.32}
        height = size["height"]
        page_area = size["height"] * size["width"]
        # A picture covering most of the page is a mis-boxed raster, not a
        # figure. p.95's ADENDA divider is exactly this: docling emits one
        # picture and zero text for the whole page, while plain tesseract reads
        # the heading exactly (#17). Guarding against real figures must not
        # silence a page.
        page_figures = [f for f in figures.get(page, [])
                        if abs(f["r"] - f["l"]) * abs(f["t"] - f["b"]) < 0.5 * page_area]
        items = items_on(data, page)
        boxes = [(item, to_pixels(item["prov"][0]["bbox"], height)) for item in items]

        for line in lines:
            line_top, line_bottom = line["box"][1], line["box"][3]
            line_height = max(1.0, line_bottom - line_top)
            on_row = []
            for item, item_px in boxes:
                overlap = min(line_bottom, item_px[3]) - max(line_top, item_px[1])
                if overlap > 0.5 * line_height:
                    on_row.append((item, item_px))

            if on_row and _extend_on_row(line, on_row, height, stats):
                continue

            # Whatever is still unaccounted for on this row. With no item, that
            # is the whole line; with items that could not absorb it, it is the
            # words none of them covers -- a two-column row, or a provision whose
            # neighbour on the row is a different record. Those land as their own
            # record rather than being merged into someone else's: the position
            # is a fact, the authorship is not.
            for run in _unclaimed_runs(line, on_row):
                if len(run) < 3:
                    continue                  # stray figure ink, not a provision
                box = (min(w["box"][0] for w in run), min(w["box"][1] for w in run),
                       max(w["box"][0] + w["box"][2] for w in run),
                       max(w["box"][1] + w["box"][3] for w in run))
                bbox = to_points(box, height)
                if any(_contained(bbox, f) for f in page_figures):
                    stats["skipped_in_figure"] += 1
                    continue
                text = " ".join(w["text"] for w in run)
                label = "list_item" if MARKER_START.match(text) else "text"
                data["texts"].append({
                    "self_ref": f"#/texts/{next_ref}",
                    "parent": {"$ref": "#/body"},
                    "children": [],
                    "content_layer": "body",
                    "label": label,
                    "prov": [{"page_no": page, "bbox": bbox,
                              "charspan": [0, len(text)]}],
                    "orig": text,
                    "text": text,
                    "recovered_by": "repair_ocr:full-page-tesseract",
                })
                next_ref += 1
                stats["inserted"] += 1


def _unclaimed_runs(line: dict, on_row: list) -> list[list[dict]]:
    """Consecutive words on a row that no item's own box accounts for."""
    if not on_row:
        return [line["words"]]
    spans = [(item_px[0], item_px[2]) for _, item_px in on_row]
    runs, current = [], []
    for word in line["words"]:
        centre = word["box"][0] + word["box"][2] / 2.0
        if any(left - 4 <= centre <= right + 4 for left, right in spans):
            if current:
                runs.append(current)
                current = []
        else:
            current.append(word)
    if current:
        runs.append(current)
    return runs


def _extend_on_row(line: dict, on_row: list, height: float, stats: dict) -> bool:
    """Give a single-line item back the rest of its own row.

    Deliberately narrow, because rewriting text that is already correct would
    regress every measurement on the map for no measured gain. All four
    conditions must hold:

    - **exactly one** item on the row -- two means a two-column layout, and
      merging across columns invents a sentence the page does not print;
    - the item is **one line tall**, so this cannot truncate a paragraph whose
      box happens to span the row;
    - the row holds at least `EXTEND_MARGIN` more words than the item has;
    - the row's text **starts with** what the item already says, which is what
      makes this a continuation rather than a different reading of the same ink.
    """
    if len(on_row) != 1:
        return False
    item, item_px = on_row[0]
    line_height = max(1.0, line["box"][3] - line["box"][1])
    if (item_px[3] - item_px[1]) > 1.8 * line_height:
        return False
    have = (item.get("text") or "").strip()
    full = line["text"].strip()
    if len(full.split()) - len(have.split()) < EXTEND_MARGIN:
        return False
    squash = lambda s: re.sub(r"\s+", "", s).lower()
    if not have or not squash(full).startswith(squash(have)):
        return False
    stats["extended"] += 1
    stats["extended_words"] += len(full.split()) - len(have.split())
    item["text"] = full
    item["orig"] = full
    item["prov"][0]["bbox"] = to_points(line["box"], height)
    item["recovered_by"] = "repair_ocr:same-row"
    return True


def _contained(box: dict, outer: dict, pad: float = 2.0) -> bool:
    lo_b, hi_b = min(box["t"], box["b"]), max(box["t"], box["b"])
    lo_o, hi_o = min(outer["t"], outer["b"]), max(outer["t"], outer["b"])
    return (box["l"] >= outer["l"] - pad and box["r"] <= outer["r"] + pad
            and lo_b >= lo_o - pad and hi_b <= hi_o + pad)


# --------------------------------------------------------------------------- #
# pass B -- comparison operators, gated to prose
# --------------------------------------------------------------------------- #

def recover_operators(pdf: Path, data: dict, pages: list[int], tmp: Path,
                      stats: dict) -> None:
    """Splice `≥`/`≤` back in, gated to prose (#21).

    EasyOCR cannot emit them at all -- `latin_g2` has no comparison-with-equality
    glyph, and an allowlist restricts an alphabet rather than extending one.
    `equ.traineddata` has them and loads only under `--oem 0`, which docling has
    no field for, hence a splice rather than a setting.

    **The gate is not optional.** On line art the same pass *manufactures*
    operators: 105 `≤` against a hand-counted truth of 40. So it runs only over
    items outside every `pictures[]` and `tables[]` box, and only ever
    substitutes an operator for a token the main pass read as something else --
    it never inserts, and never rewrites `>` to `≥`, since roughly one comparison
    in eight is genuinely strict.
    """
    blocked = boxes_by_page(data)
    heights = {int(k): v["size"]["height"] for k, v in data["pages"].items()}

    for page in pages:
        items = [t for t in items_on(data, page) if (t.get("text") or "").strip()]
        if not items:
            continue
        png = None
        height = heights.get(page, 841.92)
        for item in items:
            if not any(c.isdigit() for c in item["text"]):
                # An operator always accompanies a number, so a digit-free item
                # cannot carry a threshold. Cost gate, not a correctness one.
                continue
            bbox = item["prov"][0]["bbox"]
            if any(overlaps(bbox, b) for b in blocked.get(page, [])):
                stats["operator_gated"] += 1
                continue
            if png is None:
                png = render(pdf, page, tmp)
                if not png.exists():
                    break
            left, top, right, bottom = to_pixels(bbox, height)
            box = (max(int(left) - 4, 0), max(int(top) - 4, 0),
                   int(right) + 4, int(bottom) + 4)
            if box[2] - box[0] < 6 or box[3] - box[1] < 6:
                continue
            piece = crop(png, box, tmp / "crop.png")
            legacy = tess(piece, "spa+equ", "6", oem="0")
            if not (OPERATORS & set(legacy)):
                continue
            merged = splice_operators(item["text"], legacy)
            if merged != item["text"]:
                item["text"] = merged
                if item.get("orig"):
                    item["orig"] = merged
                stats["operators"] += 1


def splice_operators(base: str, legacy: str) -> str:
    """Token-aligned substitution: only an operator ever moves.

    Everything else keeps the main pass's reading, because `--oem 0` is the
    weaker engine on ordinary prose -- it is here for one glyph class only.
    """
    base_tokens, legacy_tokens = base.split(), legacy.split()
    matcher = difflib.SequenceMatcher(None, base_tokens, legacy_tokens,
                                      autojunk=False)
    out = list(base_tokens)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or (i2 - i1) != (j2 - j1):
            continue
        for offset in range(i2 - i1):
            candidate = legacy_tokens[j1 + offset]
            if candidate in OPERATORS:
                out[i1 + offset] = candidate
    return " ".join(out)


# --------------------------------------------------------------------------- #
# pass C -- list markers
# --------------------------------------------------------------------------- #

def splice_markers(pdf: Path, json_path: Path, last_page: int, tmp: Path,
                   stats: dict) -> None:
    """Recover the markers that address every normative provision (#18).

    The glyph is legible in the ~13 pt gutter the item's own `bbox.l` betrays but
    never reaches `ListItem.marker`. A tesseract read of that gutter recovers 238
    of 248 markable items, agrees with all 29 docling kept, and disagrees with
    none. Re-deriving a marker by counting was prototyped and rejected at 17/29:
    style is not a function of indent, and one sibling lost to a #17 drop
    silently misnumbers every provision after it.
    """
    out = tmp / "markers.json"
    subprocess.run([sys.executable, str(REPO / "scripts/recover_list_markers.py"),
                    "--pdf", str(pdf), "--json", str(json_path),
                    "--last-page", str(last_page), "--out", str(out)],
                   check=True, capture_output=True)
    result = json.loads(out.read_text())
    markers = result.get("markers", {})
    stats["marker_orphans"] = len(result.get("orphans", []) or [])

    data = json.loads(json_path.read_text())
    for item in data.get("texts", []):
        # recover_list_markers.py keys by self_ref and returns {marker, page}.
        entry = markers.get(item.get("self_ref")) or {}
        marker = entry.get("marker", "").strip() if isinstance(entry, dict) else str(entry)
        if marker and not (item.get("marker") or "").strip():
            item["marker"] = marker
            stats["markers"] += 1
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=1))


# --------------------------------------------------------------------------- #
# pass D -- the gate
# --------------------------------------------------------------------------- #

def coverage_gate(json_path: Path, pdf: Path, last_page: int) -> tuple[bool, list]:
    """Fail on ink that reads as text and still is not in the document (#17).

    The class no other measurement reaches: a line dropped from the middle of a
    block reads as well-formed prose, so nothing announces the loss -- but the
    ink is still on the page.
    """
    work = Path(tempfile.mkdtemp(prefix="coverage-"))
    subprocess.run(
        [sys.executable, str(REPO / "scripts/ocr_line_coverage.py"), f"1-{last_page}"],
        capture_output=True, text=True,
        env={**os.environ, "URBANDOCS_REPO": str(REPO), "TESSDATA_PREFIX": TESSDATA,
             "OCR_DOC_JSON": str(json_path), "OCR_DOC_PDF": str(pdf),
             "OCR_WORKDIR": str(work)})
    report_path = work / "line-coverage" / f"report-1-{last_page}.json"
    bands = json.loads(report_path.read_text()) if report_path.exists() else []
    # A dropped *line* is one line tall. p.95's ADENDA divider reports a band
    # spanning the whole page -- 1,754 px against a 15 px text line -- because
    # most of that page is a decorative graphic no item covers. OCR'ing that
    # region returns the page's title, which looks like a dropped line and is
    # not one: the title is in the substrate, sitting in its own item. Height is
    # what tells the two apart.
    prose = [b for b in bands
             if b.get("nwords", 0) >= 3 and not b.get("in_region")
             and (b["band"][1] - b["band"][0]) <= MAX_DROP_BAND_PX]
    shutil.rmtree(work, ignore_errors=True)
    return not prose, prose


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # No default: the document this was written against has left the corpus, and
    # a stale default would fail on a missing path rather than say why.
    ap.add_argument("--doc", required=True)
    ap.add_argument("--tuned", type=Path, default=TUNED)
    ap.add_argument("--pages", default=None,
                    help="OCR page range, e.g. 1-95. Default: from pipeline.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what each pass would change, write nothing")
    ap.add_argument("--skip-gate", action="store_true")
    ap.add_argument("--accept-residue", action="store_true",
                    help="promote despite surviving bands, recording them in "
                         "the pipeline record as disclosed residue")
    args = ap.parse_args(argv)

    doc = args.doc
    pdf = PDF_DIR / f"{doc}.pdf"
    src = args.tuned / f"{doc}.json"
    cfg_path = args.tuned / f"{doc}.pipeline.json"
    for path in (pdf, src, cfg_path):
        if not path.exists():
            sys.exit(f"missing {path}")

    cfg = json.loads(cfg_path.read_text())
    if cfg.get("profile") != "ocr":
        sys.exit(f"{doc} has profile {cfg.get('profile')!r}; nothing to repair")

    if args.pages:
        first, _, last = args.pages.partition("-")
        ranges = [[int(first), int(last or first)]]
    else:
        ranges = cfg.get("ocr_page_ranges")
        if not ranges:
            sys.exit(f"{cfg_path.name} has no ocr_page_ranges; pass --pages")
    pages = [p for a, b in ranges for p in range(a, b + 1)]
    last_page = max(b for _, b in ranges)

    data = json.loads(src.read_text())
    in_range = set(pages)

    def tally(doc: dict) -> dict:
        """Counters scoped to the OCR range.

        Corpus-wide counts would be read as a repair that did nothing: the native
        tail already holds 92 `≥` and 40 `≤`, while pp.1-94 hold zero (#14). The
        tail is the ground truth, not the target.
        """
        scoped = [t for t in doc.get("texts", [])
                  if (t.get("prov") or [{}])[0].get("page_no") in in_range]
        return {"texts": len(scoped),
                "markers": sum(1 for t in scoped if (t.get("marker") or "").strip()),
                "ge": sum((t.get("text") or "").count("≥") for t in scoped),
                "le": sum((t.get("text") or "").count("≤") for t in scoped),
                "tail_texts": len(doc.get("texts", [])) - len(scoped)}

    before = tally(data)

    stats = defaultdict(int)
    promoted = False
    work = Path(tempfile.mkdtemp(prefix=f"repair-{doc}-"))
    staged = work / f"{doc}.json"
    try:
        print(f"[{doc}] pass A -- recovering dropped text over pp."
              f"{pages[0]}-{pages[-1]}", file=sys.stderr)
        recover_dropped_text(pdf, data, pages, work, stats)
        print(f"[{doc}] pass B -- operator recovery", file=sys.stderr)
        recover_operators(pdf, data, pages, work, stats)
        staged.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        print(f"[{doc}] pass C -- marker splice", file=sys.stderr)
        splice_markers(pdf, staged, last_page, work, stats)
        data = json.loads(staged.read_text())

        ok, leftover = (True, [])
        if not args.skip_gate:
            print(f"[{doc}] pass D -- coverage gate", file=sys.stderr)
            ok, leftover = coverage_gate(staged, pdf, last_page)

        after = tally(data)
        if after["tail_texts"] != before["tail_texts"]:
            print(f"WARNING: {before['tail_texts'] - after['tail_texts']} items "
                  f"changed outside the OCR range -- the native tail must not be "
                  f"touched", file=sys.stderr)

        print(f"\n{doc} pp.{pages[0]}-{pages[-1]}: text items "
              f"{before['texts']} -> {after['texts']} "
              f"(+{stats['inserted']} inserted, {stats['extended']} extended by "
              f"{stats['extended_words']} words)", file=sys.stderr)
        print(f"  markers   {before['markers']} -> {after['markers']} "
              f"({stats['marker_orphans']} orphan markers = drop sites)",
              file=sys.stderr)
        print(f"  ≥ / ≤     {before['ge']}/{before['le']} -> {after['ge']}/{after['le']} "
              f"({stats['operators']} items spliced, {stats['operator_gated']} "
              f"gated out as line art or table)", file=sys.stderr)
        print(f"  gate      {'clean' if ok else f'{len(leftover)} bands still uncovered'}",
              file=sys.stderr)
        for band in leftover[:10]:
            print(f"    p{band['page']} {band['ocr'][:70]!r}", file=sys.stderr)

        if args.dry_run:
            print(f"\ndry run: {src} unchanged (staged at {staged})", file=sys.stderr)
            return 0
        if not ok and not args.accept_residue:
            print(f"\nGATE FAILED -- {src} unchanged. Staged at {staged}",
                  file=sys.stderr)
            return 1
        shutil.copy2(staged, src)
        promoted = True
        cfg["repair_ocr"] = {"passes": ["dropped-text", "operators", "markers"],
                             "pages": ranges, "inserted": stats["inserted"],
                             "extended": stats["extended"],
                             "operators": stats["operators"],
                             "markers": after["markers"],
                             # Bands the passes could not close, carried on the
                             # record rather than filtered away or silently
                             # tolerated -- the same disclosure-not-repair rule
                             # the substrate applies to everything else (#27).
                             "residual_uncovered": [
                                 {"page": b["page"], "ocr": b["ocr"]}
                                 for b in leftover]}
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
        print(f"\npromoted -> {src}", file=sys.stderr)
        return 0
    finally:
        # Keep the staged output whenever it was not promoted -- a dry run, or a
        # gate failure. Deleting the thing the failure message points at makes
        # the failure impossible to investigate.
        if args.dry_run or not promoted:
            print(f"(work dir kept: {work})", file=sys.stderr)
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
