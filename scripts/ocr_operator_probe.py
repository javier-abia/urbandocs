#!/usr/bin/env python3
"""Re-OCR HABITABILIDAD's articulado with tesseract legacy + equ and count operator sites.

Answers #21: which comparison operators come back, on which pages, at what cost.
The legacy engine (--oem 0) is the only tesseract mode that can load equ.traineddata,
which is the only tested model whose charset contains "≥" and "≤".

Requires spa.traineddata (from tessdata, *not* tessdata_best — the latter is LSTM-only)
and equ.traineddata in $TESSDATA_PREFIX. See docs/research/habitabilidad-operator-recovery.md.

One page in flight at a time: render, OCR, count, delete the PNG.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PDF = REPO / "documentos" / "HABITABILIDAD.pdf"
PAGES = range(1, 95)  # pp.95-106 have a text layer and are spliced natively
DPI = "300"


def main(workdir: Path) -> int:
    if "TESSDATA_PREFIX" not in os.environ:
        print("set TESSDATA_PREFIX to a dir holding spa.traineddata + equ.traineddata")
        return 1
    workdir.mkdir(parents=True, exist_ok=True)
    pages_dir = workdir / "pages"
    pages_dir.mkdir(exist_ok=True)

    rows = []
    t0 = time.time()
    for page in PAGES:
        stem = workdir / f"render{page}"
        subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", DPI,
                        "-png", "-gray", str(PDF), str(stem)], capture_output=True)
        rendered = sorted(workdir.glob(f"render{page}-*.png"))
        if not rendered:
            print(f"page {page}: render failed", file=sys.stderr)
            continue
        png = rendered[0]

        started = time.time()
        proc = subprocess.run(["tesseract", str(png), "stdout", "-l", "spa+equ",
                               "--oem", "0", "--psm", "6"],
                              capture_output=True, text=True)
        text = proc.stdout
        png.unlink()
        (pages_dir / f"p{page:03d}.txt").write_text(text)

        rows.append({"page": page, "seconds": round(time.time() - started, 1),
                     "words": len(text.split()),
                     "ge": text.count("≥"), "le": text.count("≤"),
                     "lt": text.count("<"), "gt": text.count(">"),
                     # "><" is how the legacy engine renders "×" — never a real pair
                     "times_artifact": text.count("><"),
                     "m2": text.count("m2"), "sup2": text.count("²")})
        print(rows[-1], flush=True)

    (workdir / "ocr_operator_probe.json").write_text(json.dumps(rows, indent=1))
    total = lambda key: sum(r[key] for r in rows)
    print(f"\npp.1-94 in {time.time() - t0:.0f}s: {total('words')} words, "
          f"ge={total('ge')} le={total('le')} lt={total('lt')} gt={total('gt')} "
          f"(of which ×-artifacts: {total('times_artifact')}) sup2={total('sup2')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("ocr-probe")))
