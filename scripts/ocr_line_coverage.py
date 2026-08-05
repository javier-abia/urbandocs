#!/usr/bin/env python3
"""2D line-coverage diff for HABITABILIDAD: ink the tuned OCR left behind.

Same idea as the row-wise pass, but coverage is per *pixel column*, not per row:
an item bbox covers only the columns it spans. That catches losses on a row the
OCR did touch — a TOC line whose marker survived and whose title vanished.

For each page: render at 150 dpi, mark ink columns per row, subtract the columns
covered by any docling item's prov.bbox, keep rows with a substantial uncovered
ink run, group them into bands, then crop each band and OCR it to see what it says.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ.get("URBANDOCS_REPO", Path(__file__).resolve().parent.parent))
# Defaults are HABITABILIDAD, the one document with an `ocr` profile. Overridable
# so scripts/convert.py can run this as the acceptance gate for any document it
# OCRs.
PDF = Path(os.environ.get("OCR_DOC_PDF", REPO / "documentos" / "HABITABILIDAD.pdf"))
DOC = Path(os.environ.get(
    "OCR_DOC_JSON",
    REPO / "documentos/documentos-docling/docling-tuned/HABITABILIDAD.json"))
TESSDATA = os.environ.get("TESSDATA_PREFIX", "/usr/share/tessdata")

DPI = 150
SCALE = DPI / 72.0
INK = 160          # pixel < INK is ink
RUN_GAP = 18       # px of white tolerated inside one ink run (inter-word space)
MIN_GAP_INK = 40   # px of uncovered ink in a row before the row counts as a gap row
MERGE_GAP = 3      # blank rows tolerated inside a band
MIN_BAND_H = 6     # discard bands thinner than this
PAD = 2            # px of slack around each item bbox

TABLE = bytes(1 if i < INK else 0 for i in range(256))
WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}")


def read_pgm(path):
    data = path.read_bytes()
    tok, i = [], 0
    while len(tok) < 4:
        while data[i : i + 1].isspace():
            i += 1
        if data[i : i + 1] == b"#":
            while data[i] != 0x0A:
                i += 1
            continue
        j = i
        while not data[j : j + 1].isspace():
            j += 1
        tok.append(data[i:j])
        i = j
    i += 1
    w, h = int(tok[1]), int(tok[2])
    return w, h, data[i : i + w * h]


def ink_runs(mapped):
    """Maximal runs of ink columns, merging white gaps of <= RUN_GAP."""
    out = []
    start = end = None
    for m in re.finditer(b"\x01+", mapped):
        a, b = m.start(), m.end()
        if start is None:
            start, end = a, b
        elif a - end <= RUN_GAP:
            end = b
        else:
            out.append((start, end))
            start, end = a, b
    if start is not None:
        out.append((start, end))
    return out


def subtract(runs, covered):
    """runs minus covered, both lists of (a, b) half-open intervals."""
    out = []
    for a, b in runs:
        pieces = [(a, b)]
        for ca, cb in covered:
            nxt = []
            for pa, pb in pieces:
                if cb <= pa or ca >= pb:
                    nxt.append((pa, pb))
                    continue
                if pa < ca:
                    nxt.append((pa, min(ca, pb)))
                if pb > cb:
                    nxt.append((max(cb, pa), pb))
            pieces = nxt
            if not pieces:
                break
        out.extend(pieces)
    return out


def to_px(bbox, page_h):
    t, b = max(bbox["t"], bbox["b"]), min(bbox["t"], bbox["b"])
    return (bbox["l"] * SCALE, (page_h - t) * SCALE,
            bbox["r"] * SCALE, (page_h - b) * SCALE)


def load_doc():
    d = json.load(open(DOC))
    pages = {int(k): v["size"] for k, v in d["pages"].items()}
    items, regions = {}, {}
    for kind, key in (("picture", "pictures"), ("table", "tables")):
        for i, it in enumerate(d.get(key, [])):
            for pr in it.get("prov", []):
                p = pr["page_no"]
                regions.setdefault(p, []).append(
                    (to_px(pr["bbox"], pages[p]["height"]), kind, f"#/{key}/{i}"))
    for i, it in enumerate(d["texts"]):
        for pr in it.get("prov", []):
            p = pr["page_no"]
            items.setdefault(p, []).append(
                (to_px(pr["bbox"], pages[p]["height"]), it.get("label"),
                 it.get("text", ""), f"#/texts/{i}"))
    return pages, items, regions


def ocr_crop(pgm, x0, y0, x1, y1, out, pw, ph):
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(pw, int(x1)), min(ph, int(y1))
    w, h = x1 - x0, y1 - y0
    if w < 8 or h < 4:
        return None
    out.unlink(missing_ok=True)
    r = subprocess.run(
        ["magick", str(pgm), "-crop", f"{w}x{h}+{x0}+{y0}", "+repage",
         "-bordercolor", "white", "-border", "10", str(out)],
        capture_output=True, check=False)
    if r.returncode != 0 or not out.exists():
        return None
    env = dict(os.environ, TESSDATA_PREFIX=TESSDATA)
    p = subprocess.run(["tesseract", str(out), "stdout", "-l", "spa", "--psm", "7"],
                       capture_output=True, text=True, env=env)
    out.unlink(missing_ok=True)
    return None if p.returncode != 0 else " ".join(p.stdout.split())


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "1-94"
    a, _, b = arg.partition("-")
    work = Path(os.environ.get("OCR_WORKDIR", "/tmp")) / "line-coverage"
    work.mkdir(parents=True, exist_ok=True)
    pages, items, regions = load_doc()
    report = []
    for p in range(int(a), int(b or a) + 1):
        stem = work / f"r{p}"
        subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p), "-r", str(DPI),
                        "-gray", str(PDF), str(stem)], capture_output=True, check=False)
        got = sorted(work.glob(f"r{p}-*.pgm"))
        if not got:
            print(f"page {p}: render failed", file=sys.stderr)
            continue
        pgm = got[0]
        w, h, px = read_pgm(pgm)
        its = items.get(p, [])
        cov_rows = [[] for _ in range(h)]
        for (r, *_x) in its:
            for y in range(max(0, int(r[1]) - PAD), min(h, int(r[3]) + PAD + 1)):
                cov_rows[y].append((r[0], r[2]))
        gaps = [None] * h
        for y in range(h):
            mapped = px[y * w : (y + 1) * w].translate(TABLE)
            if 1 not in mapped:
                continue
            left = subtract(ink_runs(mapped), cov_rows[y])
            total = sum(b_ - a_ for a_, b_ in left)
            if total >= MIN_GAP_INK:
                gaps[y] = left
        y = 0
        while y < h:
            if gaps[y] is None:
                y += 1
                continue
            start, gap = y, 0
            segs = []
            while y < h:
                if gaps[y] is not None:
                    gap = 0
                    segs.extend(gaps[y])
                else:
                    gap += 1
                    if gap > MERGE_GAP:
                        break
                y += 1
            end = y - gap
            if end - start < MIN_BAND_H or not segs:
                continue
            x0 = min(s[0] for s in segs)
            x1 = max(s[1] for s in segs)
            if x1 - x0 < 20:
                continue
            txt = ocr_crop(pgm, x0 - 4, start - 4, x1 + 4, end + 4,
                           work / f"c-p{p:03d}-y{start:04d}.png", w, h)
            if txt is None:
                continue
            in_region = [k for (r, k, _ref) in regions.get(p, [])
                         if r[1] - 6 <= start and end <= r[3] + 6
                         and r[0] - 6 <= x0 and x1 <= r[2] + 6]
            row = {"page": p, "band": [start, end], "x": [x0, x1],
                   "in_region": in_region, "ocr": txt,
                   "nwords": len(WORD.findall(txt))}
            report.append(row)
            print(json.dumps(row, ensure_ascii=False))
        pgm.unlink()
    (work / f"report-{arg}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"--- {len(report)} uncovered bands over pages {arg}", file=sys.stderr)


if __name__ == "__main__":
    main()
