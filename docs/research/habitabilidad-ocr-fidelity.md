# Can OCR recover HABITABILIDAD's bitmap-rendered normative text?

Research asset for [#11](https://github.com/javier-abia/urbandocs/issues/11). Grounds the ingestion-substrate decision ([#4](https://github.com/javier-abia/urbandocs/issues/4)).

**Measured against** `documentos/documentos-docling/docling-tuned/HABITABILIDAD.json` (docling 2.115.0, `ocr` profile, EasyOCR `lang=["es"]`, `force_full_page_ocr=false`, table mode `accurate`) — the artifact produced by [#13](https://github.com/javier-abia/urbandocs/issues/13). Ground truth = the source PDF pages rendered with `pdftoppm` and read directly.

## Verdict

**OCR works. The corpus is no longer blind on this document — but its text is not verbatim-quotable, and it silently drops normative clauses.**

106/106 pages carry text; 33,433 words; median 251 words/page. Pages 12, 20, 55, 88 — which extracted 0 words before — now yield full articulado. That is the coverage win, and it is real.

Three defect classes stand between that and a citation:

| Class | Severity | Repairable? |
|---|---|---|
| A. Silent clause drops | **Disqualifying for "the corpus is complete"** | No — needs a detection pass |
| B. Character-level corruption | High, but systematic | Yes — deterministic rules |
| C. Structure loss (list markers, table headers) | High — breaks cross-references | Partly |

Recommendation: **ingest it, repair class B at ingest, and do not promise verbatim quotes for this document** — the citation guarantee ([#8](https://github.com/javier-abia/urbandocs/issues/8)) must resolve to a page-anchored *image crop* the human can eyeball, not to a text span the agent claims is exact. Class A must be measured before the engine can claim coverage.

## A. Silent clause drops — the blocking finding

Whole leading lines of paragraphs go missing. Sampled two pages against the render and found three:

- **p. 55 item b)** — the entire opening clause *"Cuando la ventilación sea natural deberá realizarse directamente desde el espacio exterior"* is absent. `grep "Cuando la ventilación sea natural"` over the whole corpus: **0 hits.** The remainder is also scrambled — it begins `"0 desde un En este caso, …"` and ends `"… 1,50 m?. patio."`, with `patio.` orphaned to the end.
- **p. 55 item c)** — truncated at *"…un conducto de entrada de aire en la parte"*. The tail *"inferior del patio con una superficie mínima de 0,20 m² que tomará el aire del exterior del edificio"* is gone. **A dimension-bearing normative clause, lost.**
- **p. 88 item g)** — opens at *"es imposible que la estancia mayor…"*; the lead *"Cuando la configuración del solar o el edificio no permita la condición de vivienda exterior, ya que"* is gone.

Rate proxy — fraction of prose/list items ≥6 words that begin with a lowercase letter (a paragraph that starts mid-sentence):

| Document / region | Items | Starts lowercase |
|---|---|---|
| HABITABILIDAD pp. 1–94 (OCR) | 569 | 44 (**7.7 %**) |
| DccSUA (text layer) | 814 | 29 (3.6 %) |
| DOG_2025 (text layer) | 165 | 8 (4.8 %) |

≈ 4 points above baseline ≈ **~20+ passages missing their opening clause** across the document. These failures are *silent*: the extracted paragraph reads as well-formed prose, so neither the agent nor the reader can tell a clause was removed. That is worse than a garbled character, which announces itself.

One more coverage gap: **p. 95 extracts nothing.** It is the ADENDA section divider — white text on a solid blue field (*"ADENDA. Fichas gráficas de diseño de edificios de viviendas en Galicia"*). The section boundary is therefore invisible in the extraction. Pages 96, 104, 105, 106 are genuinely blank (verified by render).

## B. Character-level corruption — systematic, therefore repairable

Diffed p. 20 word-for-word against the render:

| Source | OCR | Count (pp. 1–94) |
|---|---|---|
| `m²` | `m?` | 25 occurrences; **0 correct `m²` anywhere in the OCR region** |
| conjunction `o` | `0` (`"NHV-2010 0 con"`, `"ducha 0 bañera"`) | 191 |
| `y` | `Y` | pervasive |
| `artículo 11º` | `artículo 11` | ordinal marker dropped |
| `Artículo 14º.` | `Artículo 14".` | — |
| `1,20 m×0,60 m` | `1,20 mx0,60 m` | `×` → `x` |
| `,` (mid-sentence) | `;` | pervasive |
| `anexo I de las normas` | `anexo de las normas` | **reference identifier dropped** |
| `anexo II` | `anexo Il` | `I` → `l` |
| `baño/aseo` | `bañolaseo` | — |
| `de 1 o 2 estancias` | `de 10 2 estancias` (p. 56) | meaning-changing |

**Dimensions themselves survive.** `1,20 m`, `1,50 m`, `0,60 m`, `2,20 m`, `0,75`, `3,30 m` all read correctly; the digits are reliable. What does not survive is the **unit superscript** (`m²` → `m?`, 100 % failure) and the surrounding grammar. So the *number* is citable and the *string containing it* is not.

`m? → m²` and `standalone 0 between spaces followed by a lowercase word → o` are safe deterministic rewrites and should run at ingest. `anexo I` → `anexo` (a dropped identifier) is **not** repairable — it belongs to class A.

## C. Structure

**Headings / TOC — better than [#3](https://github.com/javier-abia/urbandocs/issues/3) recorded.** #3's "TOC extracts as bare section numbers, titles missing" was a naive-pipeline artifact. The tuned OCR run recovers the TOC in full on pp. 6–7: `Artículo 13. Obras de remodelación de edificios.`, `Artículo 14. Obras de remodelación de viviendas.`, capítulos as their own headers. **The TOC can be rebuilt.** Caveat: roman numerals corrupt (`CAPÍTULO I` → `CAPITULO /`). Heading levels: 223 `section_header`s at L2=116, L6=87, L4=9, L1=6 — the L6 bucket is the same untrustworthy fallback #13 already flagged.

**List markers are gone.** In the tuned output, the `1.` / `2.` / `a)` / `b)` / `c)` markers that number every normative provision are absent — items are bare `list_item` text. Cross-references in this corpus are *marker-addressed* (`"del apartado c) del punto 1 de ese mismo artículo"`, `"artículo 11º punto 2"`), so without markers the engine cannot resolve them, and a citation cannot name the provision below article level. The `docling-tweaked` run *does* keep numbering (`1.`, `2.`, `3.`) but emits duplication artifacts (`"2. 2 Esta exigencia…"`) and drops the `o` outright rather than misreading it — see [#14](https://github.com/javier-abia/urbandocs/issues/14). Neither run is directly usable; markers must be recovered.

**Reading order breaks locally.** On p. 20, list items A.1.1 / A.1.2 / A.2.1 emit in the order A.1.1, A.2.1, A.1.2 — but their `prov.bbox` top coordinates (313, 289, 301) are correct, so **sorting by bbox repairs it**.

**Tables split by regime:**

- *OCR region* — 2 tables (pp. 47, 50), and they are the dimensional core of the norm (Tabla 1, superficie mínima por nº de estancias). Fidelity is poor: header row loses the `1` and `> 5` **column keys**, cells duplicate (`18m2 18m2`), `20 m²` reads as `2Om2` (letter O), every `²` is lost. Values are right; the keys that make them meaningful are not. **Not citable as tables.**
- *Text-layer region* — p. 98 is clean: `3,30 m`, `≥ 12 m²`, headers intact. Same for pp. 102–103 (structurally messy, but that reflects the source layout).

**Figure text leaks into the body stream.** Diagram interiors OCR as loose `text` items (`"coina"`, `"lovadero"`, `"21,2m"` for `≥ 1,2 m`, `"S.U.2 1,50 + 1,50"`). Figure *content* is out of scope, but this noise pollutes search. Every such item's bbox falls inside a `pictures[].prov.bbox`, so it is **deterministically filterable** — and must be filtered. Figure *positions* survive: 76 pictures with page + bbox.

**Page anchoring is exact.** Every text item carries `prov.page_no` + `bbox`; the markdown export uses `<!-- page-break -->` (171 in the file) — the same convention as the text-layer docs and as the existing `buscar-normativa` skill. No off-by-one between OCR and text-layer regions of the same document. PDF page number = `prov.page_no`; the *printed* page number is offset by 4 (PDF p. 20 prints "16").

## Normative vs commentary

The italic/colour discriminator is unavailable (`TextItem.formatting` is empty — #13). **The indent does survive**, in `prov.bbox.l`, and it separated commentary from normative text on every page sampled (20, 47, 55, 56):

- normative list items: `l ≈ 70–85`
- Ministry commentary blocks: `l ≈ 111–112`

Commentary is also usually labelled `text` where the surrounding provisions are `list_item`. Two signals, consistent across four pages — this constrains [#12](https://github.com/javier-abia/urbandocs/issues/12) favourably: the heuristic has something to work with, but it is geometric, so it needs validating against the deeper indent levels (sub-items at `l ≈ 97–99` sit between the two bands).

## Cost

Local EasyOCR, CPU, 4 threads, `enable_remote_services: false` → **no API cost, no data leaves the machine** (relevant: municipal documents).

Wall-clock, from the #13 run's artifact mtimes: DOG_2025 finished 13:35:22, HABITABILIDAD finished 13:44:44 → **9 min 22 s for 106 OCR pages ≈ 5.3 s/page**. The text-layer path runs ~1.1 s/page. Whole 3-doc corpus ≈ 10 min.

That is cheap enough that OCR does **not** need to be a one-time manual ingestion — it can live inside a rerunnable conversion script and be re-run whenever the pipeline changes. Scaling: ~50 documents of this size ≈ 4–5 h single-threaded, still an overnight job, not an infrastructure problem.

## The 95–106 tail: splice, don't OCR

Already answered by the run: `force_full_page_ocr=false` means docling used the **native text layer** wherever one exists, and OCR'd only the bitmap regions — so the tail was spliced automatically. The evidence that this is the right call: in pp. 95–106 there are **zero** `m?` corruptions and **8 correct `m²`**, zero `0`-for-`o`, and p. 98's table is clean. Forcing full-page OCR would destroy working text.

**Decision: keep `force_full_page_ocr=false`.** Add p. 95's divider title by hand (or by targeted OCR with inverted contrast).

## What this means for [#4](https://github.com/javier-abia/urbandocs/issues/4)

1. **Ingest HABITABILIDAD.** Coverage beats absence, and the alternative — declaring the document unsearchable — is strictly worse than a document with known, documented defects.
2. **The ingestion contract must include a repair pass** (class B rewrites, bbox-sort for reading order, picture-bbox filtering of figure text). It is deterministic and belongs in the conversion script, not in the query path.
3. **The citation guarantee cannot be "verbatim text" for this document.** Cite file + PDF page + bbox, and make the *rendered page crop* the verifiable artifact. Every item has the bbox needed to produce one.
4. **Per-document fidelity is a first-class property of the index.** The engine should know that HABITABILIDAD is OCR-derived and hedge accordingly — an agent that quotes it as exact is lying.
5. **Class A is unresolved and blocks any completeness claim.** ~20+ passages are missing clauses that no downstream repair can invent.
