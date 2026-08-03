# docling-convert — Stage 1

PDF → tuned `DoclingDocument` JSON. Slow (~20 min for HABITABILIDAD), run once per
document, needs an ML toolchain. Its output is **committed** to this repo under
`documentos/documentos-docling/docling-tuned/`, which is what lets Stage 2
(`scripts/ingest.py`) rebuild the substrate in seconds with nothing but python.

Kept as a self-contained project with its own `pyproject.toml` and `uv.lock`
rather than folded into the root one, so the pinned environment that produced the
committed artifacts stays reproducible and the root project stays
dependency-free.

```bash
cd tools/docling-convert
uv run main.py --dst /tmp/staging          # convert every PDF in ../../documentos
uv run main.py --force --dst /tmp/staging  # reconvert artifacts that already exist
```

Whether a document goes through OCR is decided by probing its text layer, not by
filename: HABITABILIDAD's median is 5.5 extractable characters per page against
DccSUA's 3,569.

**Do not pass `--full-page-ocr`.** Under `force_full_page_ocr=True` the layout
model parks all OCR text as children of a top-level `PictureItem`, so list items
stop existing as list items — a run with it on recovered 44 markers where the
hybrid document yields 238 — and it overwrites HABITABILIDAD's pp.95–106 native
text layer, which is the ground truth
[#21](https://github.com/javier-abia/urbandocs/issues/21) measured operator
recovery against.

## After conversion

docling's OCR engine is EasyOCR, and three measured defects on HABITABILIDAD are
not fixable by any docling setting — EasyOCR's character set has no `≥`/`≤` glyph
at all, and its region OCR drops lines without a trace. `scripts/repair_ocr.py`
patches them with a second engine (tesseract) and gates the result:

```bash
python3 scripts/repair_ocr.py --doc HABITABILIDAD
```

That script needs no GPU and no ML packages. See its docstring for the four
passes and what each one is measured against.
