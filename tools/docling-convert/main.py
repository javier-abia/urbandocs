"""Convert the PDFs in ../documentos/ with a tuned docling pipeline.

For each PDF this writes, into the destination directory:

    <stem>.json           the DoclingDocument (the substrate; markdown is a lossy view)
    <stem>.md             markdown, for diffing against the naive baseline
    <stem>.pipeline.json  the exact pipeline options and probe metrics used

plus a run-level ``run.json`` recording the docling package versions, so a conversion
can be reproduced.

Whether a PDF is run through OCR is decided by probing its text layer, not by
hardcoding filenames -- see ``needs_ocr``.
"""

import argparse
import json
import statistics
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pypdfium2 as pdfium
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    HeadingHierarchyOptions,
    PdfPipelineOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ContentLayer, ImageRefMode

PACKAGES = ("docling", "docling-core", "docling-parse", "docling-ibm-models")

# A page with fewer than this many extractable characters is treated as having no
# usable text layer. The corpus separates by three orders of magnitude (median 3569
# and 2660 chars/page for the born-digital PDFs vs 6 for the raster one), so the
# exact value is not sensitive.
MIN_CHARS_PER_PAGE = 100
SPARSE_PAGE_FRACTION = 0.5
PROBE_SAMPLE_PAGES = 40


def probe_text_layer(pdf_path, sample=PROBE_SAMPLE_PAGES):
    """Measure how much extractable text each of a sample of pages carries."""
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        n = len(doc)
        if n <= sample:
            idx = range(n)
        else:
            idx = [int(i * (n - 1) / (sample - 1)) for i in range(sample)]
        lengths = [
            len(doc[i].get_textpage().get_text_bounded().strip()) for i in idx
        ]
    finally:
        doc.close()

    sparse = sum(1 for length in lengths if length < MIN_CHARS_PER_PAGE)
    return {
        "pages": n,
        "sampled": len(lengths),
        # Median, not mean: a handful of text-bearing pages (cover, annexes) in an
        # otherwise scanned document would drag the mean well above the threshold.
        "median_chars": statistics.median(lengths),
        "sparse_fraction": round(sparse / len(lengths), 3),
    }


def needs_ocr(metrics):
    return metrics["sparse_fraction"] >= SPARSE_PAGE_FRACTION


def build_pipeline_options(ocr, force_full_page_ocr):
    options = PdfPipelineOptions()

    options.do_ocr = ocr
    if ocr:
        options.ocr_options = EasyOcrOptions(
            lang=["es"],
            # Hybrid by default: OCR only the bitmap regions and leave any real text
            # layer alone. Forcing full-page OCR on a document that has *some* real
            # text corrupts those pages.
            force_full_page_ocr=force_full_page_ocr,
        )

    options.do_table_structure = True
    options.table_structure_options = TableStructureOptions(
        do_cell_matching=True,
        mode=TableFormerMode.ACCURATE,
    )

    options.do_formula_enrichment = True

    # Off by default, which leaves every heading at level 1 and flattens the document.
    # Style inference additionally needs the parsed pages to still be around when the
    # heading-hierarchy stage runs.
    options.heading_hierarchy_options = HeadingHierarchyOptions(enabled=True)
    options.generate_parsed_pages = True

    return options


def package_versions():
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    return versions


def convert(pdf, dst_dir, options, ocr, force):
    stem = pdf.stem
    json_path = dst_dir / f"{stem}.json"
    md_path = dst_dir / f"{stem}.md"

    if not force and json_path.exists() and md_path.exists():
        print(f"SKIP  {pdf.name} (already converted; use --force to redo)")
        return False

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    result = converter.convert(str(pdf))
    document = result.document

    document.save_as_json(json_path, image_mode=ImageRefMode.PLACEHOLDER)

    text = document.export_to_markdown(
        page_break_placeholder="<!-- page-break -->",
        # Running headers carry "Pag. NNNNN", the official citation page, and live in
        # the furniture layer, which the markdown export drops by default.
        included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE},
        # Under full-page OCR the layout model parks all OCR text as children of a
        # top-level PictureItem, where the markdown export cannot see it.
        traverse_pictures=ocr,
    )
    md_path.write_text(text, encoding="utf-8")

    print(f"  OK  {json_path.name}, {md_path.name} ({len(text)} chars)")
    return True


def main():
    default_src = Path(__file__).resolve().parent.parent / "documentos"

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=default_src)
    parser.add_argument(
        "--dst",
        type=Path,
        default=None,
        help="output directory (default: <src>/documentos-docling/docling-tuned)",
    )
    parser.add_argument(
        "--force", action="store_true", help="reconvert even if output exists"
    )
    parser.add_argument(
        "--ocr",
        action="append",
        default=[],
        metavar="NAME",
        help="force OCR for this PDF (filename or stem), overriding the probe",
    )
    parser.add_argument(
        "--no-ocr",
        action="append",
        default=[],
        metavar="NAME",
        help="forbid OCR for this PDF (filename or stem), overriding the probe",
    )
    parser.add_argument(
        "--full-page-ocr",
        action="store_true",
        help="use force_full_page_ocr for OCR documents (fallback if hybrid is thin)",
    )
    args = parser.parse_args()

    src_dir = args.src
    dst_dir = args.dst or src_dir / "documentos-docling" / "docling-tuned"
    dst_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(src_dir.glob("*.pdf"))
    if not pdfs:
        print("No PDFs found in", src_dir)
        return

    forced_ocr = {Path(n).stem for n in args.ocr}
    forced_no_ocr = {Path(n).stem for n in args.no_ocr}
    overlap = forced_ocr & forced_no_ocr
    if overlap:
        parser.error(f"both --ocr and --no-ocr given for: {', '.join(sorted(overlap))}")

    versions = package_versions()
    print("docling versions:", ", ".join(f"{k}={v}" for k, v in versions.items()))

    run = {"versions": versions, "documents": {}}

    for pdf in pdfs:
        stem = pdf.stem
        metrics = probe_text_layer(pdf)

        if stem in forced_ocr:
            ocr, decided_by = True, "override:--ocr"
        elif stem in forced_no_ocr:
            ocr, decided_by = False, "override:--no-ocr"
        else:
            ocr, decided_by = needs_ocr(metrics), "probe"

        profile = "ocr" if ocr else "text-layer"
        print(
            f"CONV  {pdf.name} [{profile}, by {decided_by}] "
            f"median {metrics['median_chars']:.0f} ch/pg, "
            f"{metrics['sparse_fraction']:.0%} sparse pages"
        )

        options = build_pipeline_options(ocr, args.full_page_ocr)

        record = {
            "profile": profile,
            "decided_by": decided_by,
            "probe": metrics,
            "thresholds": {
                "min_chars_per_page": MIN_CHARS_PER_PAGE,
                "sparse_page_fraction": SPARSE_PAGE_FRACTION,
                "probe_sample_pages": PROBE_SAMPLE_PAGES,
            },
            # serialize_as_any: the option sub-models are declared by their abstract
            # base types, so a plain dump emits {} for table_structure_options and
            # ocr_options and the manifest would record nothing useful.
            "pipeline_options": json.loads(
                options.model_dump_json(serialize_as_any=True)
            ),
        }

        try:
            converted = convert(pdf, dst_dir, options, ocr, args.force)
        except Exception as e:
            print(f"  FAIL {e}")
            record["error"] = str(e)
            run["documents"][stem] = record
            continue

        if converted:
            (dst_dir / f"{stem}.pipeline.json").write_text(
                json.dumps(record, indent=2, default=str), encoding="utf-8"
            )
        run["documents"][stem] = record

    (dst_dir / "run.json").write_text(
        json.dumps(run, indent=2, default=str), encoding="utf-8"
    )
    print("Done.", dst_dir)


if __name__ == "__main__":
    main()
