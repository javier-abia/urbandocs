# Adding a document to the corpus

Written for an agent session with shell access to the repo, no prior context
beyond this file. Follow top to bottom; if a step's output doesn't match what's
described, stop and surface the mismatch rather than improvising past it.

Covers the local, dev-side path: source PDF in, `corpus.tsv` out, ready to
commit. Deploying that commit to the running box is a separate step — see
"Corpus-only change" in `docs/ops/deploy-runbook.md`.

## Why this isn't a drop-in-and-go

`urbandocs.ingest` does not scan `documentos/` — it processes a hardcoded list,
`DOCS` in `src/urbandocs/ingest.py`. The line-by-line *parsing* (heading and
marker regexes, `parent_id` nesting, list indentation, figure filtering) is
general — pattern-matching on Spanish legal-document conventions (`Anejo A`,
`Artículo 14`, `B.2.6`-style numbering), not on any specific file — but which
documents get processed, and what citation prefix each one gets, is an
explicit registry you have to extend by hand.

## Steps

1. **Place the source PDF under `documentos/`.**
   The PDF itself is git-ignored (`.gitignore` un-excludes only
   `documentos/documentos-docling/docling-tuned/*.json` and `*.md`), so this
   step needs no commit — it's local input to Stage 1.

2. **Run Stage 1 — docling conversion:**
   ```sh
   cd tools/docling-convert
   uv run main.py
   ```
   Needs its own ML toolchain (docling, tesseract, pdftoppm — see that
   directory's own `pyproject.toml`/`uv.lock`). Probes the text layer to
   decide native vs. OCR per page, not by filename. Produces
   `<DOC>.json` / `.md` / `.pipeline.json` under
   `documentos/documentos-docling/docling-tuned/`.

   **Never pass `--full-page-ocr`** — it breaks list-item structure (parks OCR
   text under a `PictureItem`) and overwrites any native text-layer pages the
   document has. See that directory's README.

3. **If the document probed as OCR**, run the repair pass before trusting the
   artifact — a dry run first, then promoting only past the acceptance gate:
   ```sh
   export TESSDATA_PREFIX=/path/to/tessdata
   python3 scripts/repair_ocr.py --doc <DOC> --dry-run
   python3 scripts/repair_ocr.py --doc <DOC>
   ```
   `--accept-residue` is required if a known-unfixable band remains after the
   gate — see the script's docstring for the four passes and what each is
   measured against. Skip this step entirely for a document that probed
   text-layer.

4. **Register the document** in `src/urbandocs/ingest.py`:
   ```python
   DOCS = ["DccSUA", "DOG_2025", "dog-habitabilidad", "<NEW_DOC>"]
   ```
   Add a `DOC_CODES` entry too if the derived code — the first three
   alphanumerics, upper-cased — isn't the citation prefix you want (it needs
   to be hand-picked to avoid collisions, the way `dog-habitabilidad` was
   pinned to `D128` rather than the derived `DOG`, which would have collided
   with `DOG_2025`).

5. **Run Stage 2 — ingest:**
   ```sh
   python -m urbandocs.ingest --stats
   ```
   Stdlib only, no ML toolchain, seconds not minutes. Rebuilds
   `corpus/corpus.tsv` and `corpus/corpus.provenance.tsv` from every doc in
   `DOCS`, including the new one.

6. **Run the acceptance gate:**
   ```sh
   uv run -m urbandocs.check_corpus
   ```
   A failure here means don't commit — diagnose first.

7. **Sanity-check the geometry** (optional, not a gate):
   ```sh
   python3 scripts/section_geometry.py
   ```

8. **Commit.** What travels:
   - `documentos/documentos-docling/docling-tuned/<DOC>.json`, `.md` and
     `.pipeline.json`, and the updated `run.json` — every existing document's
     artifacts are tracked, `.pipeline.json` included
   - the `DOCS` (and, if added, `DOC_CODES`) edit in `src/urbandocs/ingest.py`
   - the regenerated `corpus/corpus.tsv` and `corpus/corpus.provenance.tsv`,
     if those are tracked in this checkout

   What does **not** travel: the source PDF.

## After it lands on `main`

The running box doesn't pick this up on its own — see "Corpus-only change
(adding or re-converting a document)" in `docs/ops/deploy-runbook.md` for the
box-side half: `git checkout`, then the normal `ingest`/`check_corpus`/restart
deploy steps.
