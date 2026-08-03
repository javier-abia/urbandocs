# The conversion + ingest pipeline

Resolves [#28](https://github.com/javier-abia/urbandocs/issues/28). Builds what
[#4](https://github.com/javier-abia/urbandocs/issues/4) and
[#32](https://github.com/javier-abia/urbandocs/issues/32) specified: a two-stage,
committed, rerunnable pipeline from PDF to `corpus.tsv`.

No new design decisions were open going in. Three came up anyway, all forced by
the corpus rather than chosen, and they are in [§4](#4-what-the-corpus-forced).

---

## 1. The two stages

| | Stage 1 — `scripts/convert.py` | Stage 2 — `scripts/ingest.py` |
|---|---|---|
| Input | `documentos/*.pdf` | `docling-tuned/*.json` |
| Output | `docling-tuned/*.json` + `.md` + `.pipeline.json` | `corpus/corpus.tsv` + `corpus.provenance.tsv` |
| Cost | ~3 min (text-layer) / ~20 min (OCR) | seconds |
| Needs | docling, tesseract + `spa`/`equ`/`eng`, pdftoppm | python only |
| Run | once per document | on every change |

The split is the point. Stage 1's output is **committed** — the `.gitignore` now
un-excludes `documentos/documentos-docling/docling-tuned/*.json` while still
excluding the source PDFs — so anyone can rebuild the substrate without an ML
toolchain, which is the owner's 2026-07-31 steer made structural.

Stage 1 writes into `.conversion-stage/` and **only promotes into
`docling-tuned/` once the acceptance gate passes**. Those artifacts are the
measured input behind every decision on the map; a half-finished conversion
must never overwrite them.

---

## 2. Stage 1, pass by pass

**Profile probe.** Per-document text density decides `text-layer` vs `ocr`
(#13). Reproduced: DccSUA and DOG_2025 `text-layer`, HABITABILIDAD `ocr`.

**docling.** Layout, tables, figure regions, formula enrichment. On the `ocr`
profile the engine is `TesseractCliOcrOptions(force_full_page_ocr=True)`, not
EasyOCR region output — region OCR silently dropped 65 lines on 34 of the 94
OCR'd pages, and 58 of those 65 are already present in a full-page tesseract
read ([#17](https://github.com/javier-abia/urbandocs/issues/17)).

**Operator recovery**, gated to prose. `equ.traineddata` loads only under
`--oem 0`, and docling has no `--oem` field, so this is a bbox splice after the
fact ([#21](https://github.com/javier-abia/urbandocs/issues/21)). Three
properties matter and all three are in the code:

- it runs only over text items outside every `pictures[]` and `tables[]` box,
  because on line art the same pass *manufactures* operators (105 `≤` against a
  hand-counted truth of 40);
- it aligns the two reads token by token and **only ever substitutes an
  operator** — it never inserts, and never rewrites `>` to `≥`;
- it skips digit-free items, which is a cost gate rather than a correctness one:
  an operator always accompanies a number.

**Marker splice.** `scripts/recover_list_markers.py`, already the working
reference from [#18](https://github.com/javier-abia/urbandocs/issues/18), run as
a pass and merged onto items whose `marker` is empty.

**Acceptance gate.** `scripts/ocr_line_coverage.py` over the converted pages,
failing the build on uncovered ink that reads as text (≥3 words, outside every
known region). This is the class no other measurement reaches: a line dropped
from the *middle* of a block reads as well-formed prose, so nothing announces
the loss — but the ink is still on the page.

`ocr_line_coverage.py` gained two environment overrides (`OCR_DOC_JSON`,
`OCR_DOC_PDF`) so it can gate any document rather than only HABITABILIDAD.

### Verification

Stage 1 was re-run end to end on DOG_2025 and reproduces the committed artifact
exactly — 331 texts, 13 tables, 75 pictures, 25 pages — in 177 s.

---

## 3. Stage 2, and the three defects it had to fix

`corpus.tsv`, eight columns, one flat table for the whole corpus:

```
id  doc  page  cite  parent_id  label  text  norm
```

**4,820 records, 613 section headers** across the three documents. (613 is the
same section count #32's prototype reached by a different route, which is a
useful coincidence rather than a check — the prototype approximated a section as
"nearest preceding header".)

| | records | headers | list items | tables | pictures |
|---|---|---|---|---|---|
| DccSUA | 1,306 | 369 | 359 | 23 | 31 |
| DOG_2025 | 338 | 21 | 29 | 13 | 75 |
| HABITABILIDAD | 3,176 | 223 | 419 | 5 | 76 |

#32 listed three prototype defects for this ticket. All three are fixed and each
is now checkable by re-running `scripts/section_geometry.py`.

**1. `parent_id` from cite-prefix nesting, not header adjacency.** The load-bearing
one: #32's whole argument for `parent_id` over a `±N` window rests on the chain
being real. Before, the parent walk climbed *siblings* —
`B.2.6.2 Vías de circulación` came back as a child of `B.2.6.1 Área de acceso`.
Now the spine is a stack keyed on the printed cite, and `SectionHeaderItem.level`
is discarded outright (#14: the emitted tree is inverted).

```
B.2.6    p71 -> B.2          (7 children)
B.2.6.1  p72 -> B.2.6        (11 children)
B.2.6.2  p74 -> B.2.6        (4 children)
B.2.6.3  p76 -> B.2.6        (6 children)
B.2.6.4  p77 -> B.2.6        (1 child)
```

Two rules the corpus needed beyond prefix matching: a **namespace heading**
(`Anejo A`, `Sección SUA 1`, `Artículo 14`, `Capítulo V`) opens a fresh numbering
space rather than sitting in one, and an **unnumbered heading is a leaf** that
never parents a numbered one — it attaches to the nearest numbered ancestor but
is popped by the next numbered heading. Unnumbered headings are not incidental:
33 of DccSUA's 209 are binding, including all 30 entries of Anejo A Terminología
([#12](https://github.com/javier-abia/urbandocs/issues/12)).

**2. Children stop at the section boundary.** The prototype's children included
the *next* section's header. `section_geometry.py` now asserts the invariant
directly — every header lying between a parent and one of its children must be a
descendant of that parent — and reports **0 children sitting past their section's
end**.

**3. Figure-label items are out of the body.** `máx`, `Q;`, `eje`,
`<30 cm PLANTA` sit physically between two headers and inherited the parent.
**515 dropped.** See §4 for the qualification this needed.

### The geometry, re-derived

`scripts/section_geometry.py` over the real `corpus.tsv`:

```
ancestor distance   p50 14   p75 67   p90 133   p95 171   p99 210   max 250
window recall       ±10 45.4%   ±30 61.0%   ±60 73.0%
cross-section bleed ±10 29.1%   ±30 45.4%   ±60 55.7%
boundary check      0 children sitting past their section's end
```

#32 measured `±30` recall at 58.5% and bleed at 42.6% off the ad-hoc probe;
against the real substrate they are **61.0%** and **45.4%**. The conclusion is
unchanged and, if anything, sharper: two records in five still do not see their
governing header inside a 61-record window, and nearly half of that window
belongs to some other section. `parent_id` is one column and gets it right every
time.

### The trace query, on the real substrate

#32's trace query — *dimensiones de las rampas de circulación* — was the case
that killed the L1 index, and the prototype put its two targets at ranks 8 and 9
of 613. Against `corpus.tsv`, with a real `parent_id`, the same sweep-and-rank
puts them at **1 and 2**:

```bash
awk -F'\t' 'NR>1{n=0; if($8~/dimension/)n++; if($8~/rampa/)n++; if($8~/circulaci/)n++;
  if(n>0){k=$5; h[k]++; if(n>b[k])b[k]=n}}
  END{for(k in b) printf "%d\t%d\t%s\n", b[k], h[k], k}' corpus/corpus.tsv \
  | sort -k1,1nr -k2,2nr | head

3  3  HAB:p74:§3            <- Dimensiones de las rampas de circulación
3  3  HAB:p74:B.2.6.2       <- B.2.6.2 Vías de circulación y distribución
3  1  HAB:p101:C.12
2  8  SUA:p27:§7
```

That is a single query, not a recall figure —
[#30](https://github.com/javier-abia/urbandocs/issues/30) is still the
instrument. It does confirm that grouping by the real chain rather than by
header adjacency moves the target up, not down.

**One correction for [#33](https://github.com/javier-abia/urbandocs/issues/33):**
the `\b` word-boundary in #32's `awk` one-liners **silently returns zero rows**
under GNU awk, where `\b` is a backspace escape and the word boundary is `\y`.
`$8 ~ /\brampa/` gives 0 hits; `/rampa/` and `/\yrampa/` both give 73. A sweep
that silently returns nothing is the worst failure mode this engine has, and it
is now a live consideration for the executor bakeoff rather than a footnote.

---

## 4. What the corpus forced

Three things #28's contract did not anticipate.

### Containment alone destroys a rasterised document

"Drop text whose bbox falls inside a `pictures[]` bbox" is correct for DccSUA
(12 items) and DOG_2025 (0). On HABITABILIDAD it eats **2,670 of 3,887 text
items** — most of the articulado — because in a fully bitmap-rendered document
the layout model boxes whole regions as pictures and the OCR'd body text lands
inside them.

The discriminator: **a picture box that swallows a `section_header` or a
`list_item` is not a figure**, it is a mis-boxed page raster. That disqualifies
**7 boxes of 182 corpus-wide** and brings the drop to 515, which is the figure
noise the rule was aimed at. Captions are exempt from the filter — they are how
the agent points at a figure it cannot read (#3).

Pictures themselves land as records, carrying no text: **182 of them**, matching
#27's finding that HABITABILIDAD's are empty placeholders. Figure *positions*
stay in scope; figure *content* does not.

### Reading order needs a left tie-break, not just `bbox.t`

Sorting by page then `bbox.t` alone leaves boxes on the same line unordered, and
a heading split across three boxes comes back scrambled —
`B.2.6.3. de aparcamiento. Áreas` for a page printing
`B.2.6.3. Áreas de aparcamiento`. Sorting by (page, 4 pt line band, `bbox.l`)
fixes it. With that in place HABITABILIDAD p.20 emits
`A.1.1, A.1.2, A.2.1` — the printed order, against the JSON's own
`A.1.1, A.2.1, A.1.2` (#18, #8).

### List items must nest, or the qualifier leaves the chain

#28 said tables and body items carry a `parent_id`; it did not say what a
sub-item's parent is. Flattening every list item onto its heading breaks the
example the substrate decision was argued on: `art14.1.a`'s encimera applies
only under `art14.1`'s no-new-rooms condition, so `art14.1` has to be in
`art14.1.a`'s ancestor chain.

Indent is the signal that survived. `formatting` is empty corpus-wide (#14) and
the marker glyph is often the thing that went missing (#18), but HABITABILIDAD
prints top-level items at `bbox.l ≈ 70` and their sub-items at `≈ 83.5` — the
same ~13 pt gutter #18 read the eaten markers out of. A per-section indent stack
gives `HAB:p21:art15.1` a child at `HAB:p21:§1` even though that child's marker
was eaten.

This is **not** #18's rejected re-derivation: nothing here guesses an ordinal.
An item whose marker cannot be read gets a positional `§n` id and an empty
`cite`, which is what says it is unaddressed.

### Marker parsing, where there is no marker hole

DccSUA and DOG_2025 print the marker inline at the head of the item text
(`1 La anchura…`), which docling leaves in `text` and out of `marker`. #18 called
this "parsing, not recovery"; parsing it addresses **175 more items**, cutting
unaddressed items from 680 to **505**, and produces ids of exactly #4's shape:
`SUA:p28:4.3.4.1`.

---

## 5. Two contradictions in the ticket, and how they were resolved

**`standalone 0 → o`.** #28's repair list has it; #28's own "Out of this ticket"
says the `0`≡`o` equivalence is "query-side only, never an ingest rewrite", and
#14 gives the reason — `0` is also a legitimate digit. Resolved toward the
explicit exclusion: **`text` is not rewritten**, and `norm` does not fold it
either, so the equivalence stays a query-side expansion as #32 recorded it.

**Tables: one record or one per row.** #28 says "rows land in `corpus.tsv` as
records"; #27 counts "2 records of ~5,900" for HABITABILIDAD's 2 OCR'd tables,
which only holds if a table is one record. Resolved toward atomic: #4's read
contract is "tables atomic on read", and #32 dropped the separate
`<DOC>.cells.tsv` projection, so the cells have to be searchable inside the
table's own record. Cells are serialized `cell | cell ¶ row`.

---

## 6. Provenance

`corpus.provenance.tsv` — `doc`, `page_from`, `page_to`, `source`:

```
DOG_2025        1    25   native
DccSUA          1    79   native
HABITABILIDAD   1    94   ocr
HABITABILIDAD  95   106   native
```

Per page range, not per document: a document-level flag would disclaim
HABITABILIDAD's native tail, which is #21's own ground truth (#27). Stage 1
derives the ranges per page from text density and writes them into
`<DOC>.pipeline.json`; Stage 2 refuses to ingest an `ocr`-profile document that
has none rather than guessing.

No record stores a fidelity flag. Every OCR axis keys on `doc` + `page` +
`label`, all three of which ride on every returned record, so the trust vector is
a function of stored columns and is derived at render time (#27).

---

## Reproducing

```bash
# Stage 1 -- needs docling + tesseract with spa/equ/eng traineddata
export TESSDATA_PREFIX=/path/to/tessdata
python3 scripts/convert.py --doc HABITABILIDAD --stage-only

# Stage 2 -- needs nothing but python
python3 scripts/ingest.py --stats
python3 scripts/section_geometry.py
```
