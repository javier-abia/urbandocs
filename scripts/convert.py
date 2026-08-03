#!/usr/bin/env python3
"""Stage 1 conversion: PDF -> tuned DoclingDocument JSON, rerunnably.

Slow (~20 min for HABITABILIDAD) and run once per document. The tuned artifacts
were previously made by a pipeline that lived outside the repo -- `*.pipeline.json`
recorded the configuration, not the code -- so new normativa could not be added
reproducibly. This is that pipeline.

    probe -> docling -> operator recovery -> marker splice -> coverage gate

Output lands in a staging directory and is only promoted into
`documentos/documentos-docling/docling-tuned/` once the acceptance gate passes,
because those artifacts are a committed permanent input (#4, decision 5): every
downstream measurement on the map was taken against them, so a half-finished
conversion must never overwrite them.

Requires: docling 2.115.0, tesseract 5 with `spa`, `equ` and `eng` traineddata,
and pdftoppm. Point TESSDATA_PREFIX at a tessdata directory holding all three;
`equ` is only distributed in the legacy `tessdata` repo, not `tessdata_best`.

Usage:
    python3 scripts/convert.py --doc HABITABILIDAD
    python3 scripts/convert.py --all --stage-only     # convert, do not promote
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PDF_DIR = REPO / "documentos"
TUNED = REPO / "documentos/documentos-docling/docling-tuned"
DOCS = ["DccSUA", "DOG_2025", "HABITABILIDAD"]

TESSDATA = os.environ.get("TESSDATA_PREFIX", "/usr/share/tessdata")

# Profile probe (#13). A document whose pages carry almost no extractable text is
# a raster: HABITABILIDAD's median was 5.5 characters per page against DccSUA's
# 3,569.
MIN_CHARS_PER_PAGE = 100
SPARSE_PAGE_FRACTION = 0.5
PROBE_SAMPLE_PAGES = 40

DPI = 200
PT = 72.0 / DPI

# Recovered comparison operators. `²` comes back from no engine and folds to
# `m2`, which the source itself writes in places (#21).
OPERATORS = {"≥", "≤"}


# --------------------------------------------------------------------------- #
# probe
# --------------------------------------------------------------------------- #

def page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def probe_profile(pdf: Path) -> dict:
    """Text-density probe: `text-layer` or `ocr`, decided per document (#13)."""
    n = page_count(pdf)
    step = max(1, n // PROBE_SAMPLE_PAGES)
    sampled = list(range(1, n + 1, step))[:PROBE_SAMPLE_PAGES]
    lengths = []
    for page in sampled:
        out = subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), str(pdf), "-"],
            capture_output=True, text=True).stdout
        lengths.append(len(out.strip()))
    lengths.sort()
    median = lengths[len(lengths) // 2] if lengths else 0
    sparse = sum(1 for x in lengths if x < MIN_CHARS_PER_PAGE) / max(1, len(lengths))
    profile = "ocr" if sparse > SPARSE_PAGE_FRACTION else "text-layer"
    return {
        "profile": profile,
        "decided_by": "probe",
        "probe": {"pages": n, "sampled": len(sampled),
                  "median_chars": float(median), "sparse_fraction": round(sparse, 3)},
        "thresholds": {"min_chars_per_page": MIN_CHARS_PER_PAGE,
                       "sparse_page_fraction": SPARSE_PAGE_FRACTION,
                       "probe_sample_pages": PROBE_SAMPLE_PAGES},
    }


def ocr_page_ranges(pdf: Path, profile: str) -> list[list[int]]:
    """Which pages this document's text comes out of OCR.

    Per page, not per document: HABITABILIDAD's tail (pp.95-106) has a real text
    layer and is provably cleaner than OCR'ing it (#11), and it is the ground
    truth #21's operator work was checked against -- a document-level flag would
    disclaim it. This is what `corpus.provenance.tsv` is built from (#27).

    p.95 is the page this rule exists to catch: docling classified the whole page
    as one picture and read nothing from it, while plain tesseract reads it
    exactly, so it must land on the OCR side of the split (#17).
    """
    if profile != "ocr":
        return []
    ranges, start = [], None
    for page in range(1, page_count(pdf) + 1):
        out = subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), str(pdf), "-"],
            capture_output=True, text=True).stdout
        sparse = len(out.strip()) < MIN_CHARS_PER_PAGE
        if sparse and start is None:
            start = page
        elif not sparse and start is not None:
            ranges.append([start, page - 1])
            start = None
    if start is not None:
        ranges.append([start, page_count(pdf)])
    return ranges


# --------------------------------------------------------------------------- #
# docling
# --------------------------------------------------------------------------- #

def run_docling(pdf: Path, profile: str, out_json: Path) -> dict:
    """Convert with docling, tesseract-CLI as the OCR engine on the `ocr` profile.

    **Full-page tesseract is the source of the text, not EasyOCR's region
    output.** Region OCR (`force_full_page_ocr=False`, `confidence_threshold=0.5`)
    silently dropped 65 lines on 34 of HABITABILIDAD's 94 OCR'd pages, without a
    trace on any of them, and 58 of those 65 are already present in a full-page
    tesseract read (#17). Layout, tables and figure regions still come from
    docling; only the characters change hands.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions, TesseractCliOcrOptions)
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_table_structure = True
    opts.table_structure_options.do_cell_matching = True
    opts.table_structure_options.mode = "accurate"
    opts.do_formula_enrichment = True
    opts.generate_parsed_pages = True
    if profile == "ocr":
        opts.do_ocr = True
        opts.ocr_options = TesseractCliOcrOptions(
            lang=["spa"], force_full_page_ocr=True, path=TESSDATA)
    else:
        opts.do_ocr = False

    conv = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    result = conv.convert(str(pdf))
    doc = result.document
    out_json.write_text(json.dumps(doc.export_to_dict(), ensure_ascii=False, indent=1))
    (out_json.with_suffix(".md")).write_text(doc.export_to_markdown())
    return json.loads(opts.model_dump_json())


# --------------------------------------------------------------------------- #
# post-passes
# --------------------------------------------------------------------------- #

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


def tess(image: Path, lang: str, psm: str, oem: str | None = None) -> str:
    cmd = ["tesseract", str(image), "stdout", "-l", lang, "--psm", psm,
           "--tessdata-dir", TESSDATA]
    if oem:
        cmd += ["--oem", oem]
    out = subprocess.run(cmd, capture_output=True, text=True,
                         env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    return out.stdout


def crop(image: Path, box: tuple[int, int, int, int], dest: Path) -> Path:
    left, top, right, bottom = box
    subprocess.run(["convert" if shutil.which("convert") else "magick", str(image),
                    "-crop", f"{right - left}x{bottom - top}+{left}+{top}",
                    "+repage", str(dest)], check=True, capture_output=True)
    return dest


def recover_operators(pdf: Path, data: dict, pages: list[int], tmp: Path) -> int:
    """Splice `≥`/`≤` back in, gated to prose (#21).

    EasyOCR cannot emit them at all -- `latin_g2` has no comparison-with-equality
    glyph, and an allowlist restricts an alphabet rather than extending one -- and
    tesseract's LSTM `spa` is the same story. `equ.traineddata` has them and loads
    only under `--oem 0`, which docling has no field for, hence this splice.

    **The gate is not optional.** On line art the same pass *manufactures*
    operators: 105 `≤` against a hand-counted truth of 40. So it runs only over
    text items outside every `pictures[]` and `tables[]` box, and it only ever
    substitutes an operator for a token the main pass read as something else --
    it never inserts, and it never rewrites `>` to `≥` (roughly one comparison in
    eight is genuinely strict).
    """
    boxes = {}
    for key in ("pictures", "tables"):
        for node in data.get(key, []):
            for prov in node.get("prov") or []:
                boxes.setdefault(prov["page_no"], []).append(prov["bbox"])
    heights = {int(k): v["size"]["height"] for k, v in data["pages"].items()}

    spliced = 0
    for page in pages:
        items = [t for t in data.get("texts", [])
                 if (t.get("prov") or [{}])[0].get("page_no") == page and t.get("text")]
        if not items:
            continue
        png = render(pdf, page, tmp)
        if not png.exists():
            continue
        height = heights.get(page, 841.92)
        for item in items:
            if not any(c.isdigit() for c in item["text"]):
                # An operator always accompanies a number, so a digit-free item
                # cannot be carrying a threshold. This is a cost gate, not a
                # correctness one: it cuts ~3,900 crops to a few hundred.
                continue
            bbox = item["prov"][0]["bbox"]
            if any(_overlaps(bbox, b) for b in boxes.get(page, [])):
                continue                       # line art or table: gate it out
            top = int((height - max(bbox["t"], bbox["b"])) / PT) - 4
            bottom = int((height - min(bbox["t"], bbox["b"])) / PT) + 4
            left, right = int(bbox["l"] / PT) - 4, int(bbox["r"] / PT) + 4
            if bottom - top < 6 or right - left < 6:
                continue
            piece = crop(png, (max(left, 0), max(top, 0), right, bottom),
                         tmp / "crop.png")
            legacy = tess(piece, "spa+equ", "6", oem="0")
            if not (OPERATORS & set(legacy)):
                continue
            merged = _splice_operators(item["text"], legacy)
            if merged != item["text"]:
                item["text"] = merged
                if item.get("orig"):
                    item["orig"] = merged
                spliced += 1
    return spliced


def _overlaps(a: dict, b: dict, pad: float = 2.0) -> bool:
    a_lo, a_hi = min(a["t"], a["b"]), max(a["t"], a["b"])
    b_lo, b_hi = min(b["t"], b["b"]), max(b["t"], b["b"])
    return not (a["r"] < b["l"] - pad or a["l"] > b["r"] + pad
                or a_hi < b_lo - pad or a_lo > b_hi + pad)


def _splice_operators(base: str, legacy: str) -> str:
    """Token-aligned substitution: only an operator ever moves.

    Aligning the two reads token by token and touching only the positions where
    the legacy engine saw `≥`/`≤` keeps the main pass's text everywhere else,
    which matters because `--oem 0` is the weaker engine on ordinary prose.
    """
    base_tokens, legacy_tokens = base.split(), legacy.split()
    matcher = difflib.SequenceMatcher(None, base_tokens, legacy_tokens, autojunk=False)
    out = list(base_tokens)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or (i2 - i1) != (j2 - j1):
            continue
        for offset in range(i2 - i1):
            candidate = legacy_tokens[j1 + offset]
            if candidate in OPERATORS:
                out[i1 + offset] = candidate
    return " ".join(out)


def splice_markers(pdf: Path, json_path: Path, last_page: int, tmp: Path) -> int:
    """Recover the list markers that address every normative provision (#18).

    The marker glyph is legible in the ~13 pt gutter the item's own `bbox.l`
    betrays, but never reaches `ListItem.marker`. A tesseract read of that gutter
    (`-l eng`; markers are language-neutral) recovers 238 of 248 markable items
    and agrees with all 29 docling kept, with zero disagreements. Re-deriving a
    marker by counting was prototyped and rejected at 17/29: style is not a
    function of indent, and one sibling lost to a #17 drop silently misnumbers
    every provision after it.
    """
    out = tmp / "markers.json"
    subprocess.run([sys.executable, str(REPO / "scripts/recover_list_markers.py"),
                    "--pdf", str(pdf), "--json", str(json_path),
                    "--last-page", str(last_page), "--out", str(out)],
                   check=True)
    markers = json.loads(out.read_text()).get("markers", {})
    data = json.loads(json_path.read_text())
    applied = 0
    for item in data.get("texts", []):
        marker = markers.get(item.get("self_ref"))
        if marker and not (item.get("marker") or "").strip():
            item["marker"] = marker
            applied += 1
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return applied


def coverage_gate(json_path: Path, pdf: Path, last_page: int) -> tuple[bool, str]:
    """Fail the build on ink the conversion left behind (#17).

    This is the class no other measurement reaches: a line dropped from the
    *middle* of a block reads as well-formed prose, so nothing announces the
    loss. Coverage geometry sees it because the ink is still on the page.
    """
    work = Path(tempfile.mkdtemp(prefix="coverage-"))
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts/ocr_line_coverage.py"), f"1-{last_page}"],
        capture_output=True, text=True,
        env={**os.environ, "URBANDOCS_REPO": str(REPO), "TESSDATA_PREFIX": TESSDATA,
             "OCR_DOC_JSON": str(json_path), "OCR_DOC_PDF": str(pdf),
             "OCR_WORKDIR": str(work)})
    bands = json.loads((work / "line-coverage" / f"report-1-{last_page}.json").read_text())
    # A band of uncovered ink is only a failure if it *reads as text*. One or two
    # stray words are figure ink the layout model left outside every box; a run
    # of them is a dropped line.
    prose = [b for b in bands if b.get("nwords", 0) >= 3 and not b.get("in_region")]
    report = "\n".join(json.dumps(b, ensure_ascii=False) for b in prose)
    shutil.rmtree(work, ignore_errors=True)
    return not prose, (f"{len(prose)} uncovered bands reading as text "
                       f"(of {len(bands)} total)\n{report}\n{proc.stderr}")


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #

def convert(doc: str, stage: Path, promote: bool) -> dict:
    pdf = PDF_DIR / f"{doc}.pdf"
    if not pdf.exists():
        sys.exit(f"missing {pdf}")
    started = time.time()
    stage.mkdir(parents=True, exist_ok=True)
    out_json = stage / f"{doc}.json"

    record = probe_profile(pdf)
    profile = record["profile"]
    print(f"[{doc}] profile={profile} "
          f"median_chars={record['probe']['median_chars']}", file=sys.stderr)

    record["pipeline_options"] = run_docling(pdf, profile, out_json)
    record["ocr_page_ranges"] = ocr_page_ranges(pdf, profile)
    print(f"[{doc}] docling done, ocr ranges {record['ocr_page_ranges']}",
          file=sys.stderr)

    if profile == "ocr":
        ranges = record["ocr_page_ranges"]
        pages = [p for a, b in ranges for p in range(a, b + 1)]
        last = max((b for _, b in ranges), default=0)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            data = json.loads(out_json.read_text())
            n_ops = recover_operators(pdf, data, pages, tmp)
            out_json.write_text(json.dumps(data, ensure_ascii=False, indent=1))
            print(f"[{doc}] operators spliced into {n_ops} items", file=sys.stderr)
            n_markers = splice_markers(pdf, out_json, last, tmp)
            print(f"[{doc}] markers spliced onto {n_markers} items", file=sys.stderr)
            record["post_passes"] = {"operators_spliced": n_ops,
                                     "markers_spliced": n_markers}
            ok, report = coverage_gate(out_json, pdf, last)
        record["acceptance"] = {"line_coverage_clean": ok}
        (stage / f"{doc}.coverage.txt").write_text(report)
        if not ok:
            print(f"[{doc}] ACCEPTANCE GATE FAILED -- staged, not promoted. "
                  f"See {stage / f'{doc}.coverage.txt'}", file=sys.stderr)
            promote = False

    record["elapsed_seconds"] = round(time.time() - started, 1)
    (stage / f"{doc}.pipeline.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n")

    if promote:
        TUNED.mkdir(parents=True, exist_ok=True)
        for suffix in (".json", ".md", ".pipeline.json"):
            src = stage / f"{doc}{suffix}"
            if src.exists():
                shutil.copy2(src, TUNED / src.name)
        print(f"[{doc}] promoted to {TUNED}", file=sys.stderr)
    return record


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", action="append", dest="docs")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--stage", type=Path, default=REPO / ".conversion-stage")
    ap.add_argument("--stage-only", action="store_true",
                    help="convert into the staging directory, do not promote")
    args = ap.parse_args(argv)

    docs = DOCS if args.all else (args.docs or [])
    if not docs:
        sys.exit("nothing to convert: pass --doc NAME or --all")

    versions = {}
    try:
        import importlib.metadata as meta
        for pkg in ("docling", "docling-core", "docling-parse", "docling-ibm-models"):
            try:
                versions[pkg] = meta.version(pkg)
            except meta.PackageNotFoundError:
                pass
    except ImportError:
        pass

    run = {"versions": versions, "documents": {}}
    for doc in docs:
        run["documents"][doc] = convert(doc, args.stage, not args.stage_only)
    (args.stage / "run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n")
    if not args.stage_only:
        shutil.copy2(args.stage / "run.json", TUNED / "run.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
