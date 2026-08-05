# The conversion + ingest pipeline

Resolves [#28](https://github.com/javier-abia/urbandocs/issues/28). Builds what
[#4](https://github.com/javier-abia/urbandocs/issues/4) and
[#32](https://github.com/javier-abia/urbandocs/issues/32) specified: a two-stage,
committed, rerunnable pipeline from PDF to `corpus.tsv`.

No new design decisions were open going in. Three came up anyway, all forced by
the corpus rather than chosen, and they are in [§4](#4-what-the-corpus-forced).

---

## 1. The two stages

| | Stage 1 — `tools/docling-convert/main.py` + `scripts/repair_ocr.py` | Stage 2 — `scripts/ingest.py` |
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

`repair_ocr.py` writes into a temp dir and **only promotes into `docling-tuned/`
once the acceptance gate passes**. Those artifacts are the measured input behind
every decision on the map; a half-finished pass must never overwrite them.

---

## 2. Stage 1, pass by pass

The converter itself is `tools/docling-convert/main.py`, moved into the repo
unchanged — it is what produced the committed artifacts, and it was outside
version control, which is half of what this ticket was about. Profile probe,
`HeadingHierarchyOptions(enabled=True)`, `TableFormerMode.ACCURATE`, formula
enrichment, `save_as_json`, and a `model_dump_json(serialize_as_any=True)`
pipeline record are all its own.

### Not full-page OCR — the mistake worth recording

The first attempt replaced EasyOCR with `TesseractCliOcrOptions(force_full_page_ocr=True)`,
reading #17's "full-page tesseract is the source of the text" as a docling
setting. It is not, and the evidence is unambiguous:

- under `force_full_page_ocr=True` the layout model parks all OCR text as
  children of a top-level `PictureItem`, so list items stop being list items —
  that run recovered **44 markers where the hybrid document yields 255**;
- docling has one OCR setting per document and cannot express a page range, so
  it also overwrites pp.96–106, whose native text layer is measurably cleaner
  (#11) and is the ground truth #21 checked operator recovery against.

What #17 asks for is that the *text of the OCR'd pages* come from a full-page
tesseract read. That is a splice over a page range, not a conversion mode. So
the three repairs are post-passes in `scripts/repair_ocr.py`, which needs no GPU,
no ML packages and no reconversion.

### A — recover what region OCR dropped (#17)

Line-driven, not box-driven. The first cut matched tesseract words against each
item's own bbox and structurally could not see the measured TOC losses: p.31's
`A.1.1.` is 26 pt wide because it *is* only the marker, so the dropped title lies
outside the very box you would search. Working from tesseract's line grouping
asks the right question — what does this row say, and what did docling get from
it. Two outcomes, both additive:

- **extend** a single-line item to its whole row, when exactly one item sits on
  the row and the row's read *starts with* what the item already says. The bbox
  widens with the text, or the fix and the acceptance gate disagree;
- **insert** whatever words on the row no item accounts for, as their own record.
  Position is a fact that was measured; which provision the words belong to is
  not, so they are not merged into a neighbour.

**+117 inserted, 17 extended by 113 words** over pp.1–95, against #17's measured
floor of 65 dropped lines.

### B — comparison operators, gated to prose (#21)

`equ.traineddata` loads only under `--oem 0`, which docling has no field for.
Three properties, all in the code: it runs only over items outside every
`pictures[]` and `tables[]` box, because on line art the same pass *manufactures*
operators (105 `≤` against a hand-counted truth of 40); it aligns the two reads
token by token and **only ever substitutes an operator**, never inserting and
never rewriting `>` to `≥`; and it skips digit-free items as a cost gate.

**3 spliced, 216 items gated out.** That is the expected shape, not a shortfall:
#21's 24 `≥` + 17 `≤` were measured *ungated*, and it found only ~6 of 41 were
prose — the rest are figure labels, which are out of scope.

### C — list markers (#18)

`scripts/recover_list_markers.py` unchanged, merged onto items whose `marker` is
empty. **29 → 255**, and 4 orphan gutter markers, which are drop *detectors*.

### D — acceptance gate (#17)

`scripts/ocr_line_coverage.py` over the repaired pages, failing on uncovered ink
that reads as text. This is the class no other measurement reaches: a line
dropped from the middle of a block reads as well-formed prose, so nothing
announces the loss — but the ink is still on the page.

It gained two environment overrides (`OCR_DOC_JSON`, `OCR_DOC_PDF`) so it can
gate any document, and the gate scores a band only if it is **≤ 75 px tall** at
150 dpi. p.95's ADENDA divider reports a band spanning the whole page — 1,754 px
against a 15 px text line — because most of that page is a decorative graphic no
item covers; OCR'ing that region returns the page title, which looks like a
dropped line and is not one. The title is in the substrate, in its own item.

The gate took the run from **18 → 4 → 1** surviving bands, each round exposing a
different defect in pass A. It is strict by default.

### The residue, disclosed rather than hidden

One band survives: p.31's `Iluminación, ventilación natural y relación con el
exterior.`, a contents-page entry that lands in the substrate without its first
word. Tesseract's full-page pass does not read `Iluminación,` at **any**
confidence; the gate sees it because the gate crops one line and runs `--psm 7`,
and line-level segmentation reads what page-level segmentation skips.

Rather than tune OCR parameters until one row on a contents page lands — #17
already ruled the contents pages out as an index spine, and #32 deleted the index
tier entirely — the band is recorded in `HABITABILIDAD.pipeline.json` under
`repair_ocr.residual_uncovered`. Promotion past a failing gate requires an
explicit `--accept-residue`; the default still blocks, so a future regression
fails the build.

### Verification

- `main.py` re-run end to end on DOG_2025 reproduces the committed artifact
  exactly — 331 texts, 13 tables, 75 pictures, 25 pages — in 177 s.
- The native tail pp.96–106 is **byte-identical** before and after repair, 2,407
  items, checked in code rather than by eye.

---

## 3. Stage 2, and the three defects it had to fix

`corpus.tsv`, eight columns, one flat table for the whole corpus:

```
id  doc  page  cite  parent_id  label  text  norm
```

**4,924 records, 613 section headers** across the three documents. (613 is the
same section count #32's prototype reached by a different route, which is a
useful coincidence rather than a check — the prototype approximated a section as
"nearest preceding header".)

| | records | headers | list items | tables | pictures |
|---|---|---|---|---|---|
| DccSUA | 1,306 | 369 | 359 | 23 | 31 |
| DOG_2025 | 338 | 21 | 29 | 13 | 75 |
| HABITABILIDAD | 3,280 | 223 | 436 | 5 | 76 |

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

### What the marker recovery bought the substrate

Unaddressed list items fall from **505 to 315**, and the chain #4 argued the
whole substrate on is now real:

```
HAB:p20:art14        Artículo 14   section_header
HAB:p20:art14.1      1.            list_item
HAB:p20:art14.1.a    a)            list_item   parent HAB:p20:art14.1
HAB:p20:art14.1.b    b)            list_item   parent HAB:p20:art14.1
HAB:p20:art14.1.c    c)            list_item   parent HAB:p20:art14.1
```

`a)`'s encimera requirement applies only under `1.`'s no-new-rooms condition, and
`1.` is now in `a)`'s ancestor chain. `cite` keeps the printed `a)`; `id` drops
the trailing punctuation, because `art14.1.a)` reads as a typo.

### The geometry, re-derived

`scripts/section_geometry.py` over the real `corpus.tsv`:

```
ancestor distance   p50 14   p75 66   p90 131   p95 170   p99 210   max 250
window recall       ±10 45.2%   ±30 61.3%   ±60 73.7%
cross-section bleed ±10 28.8%   ±30 45.4%   ±60 56.0%
boundary check      0 children sitting past their section's end
```

#32 measured `±30` recall at 58.5% and bleed at 42.6% off the ad-hoc probe;
against the real substrate they are **61.3%** and **45.4%**. The conclusion is
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
# Stage 1a -- conversion. Needs docling; run once per document.
cd tools/docling-convert && uv run main.py --dst /tmp/staging

# Stage 1b -- OCR repair. Needs tesseract with spa/equ/eng traineddata, and a
# tessdata directory that also carries tesseract's own configs/ and
# tessconfigs/ -- asking for TSV from a directory of bare *.traineddata files
# produces no output at all, silently.
export TESSDATA_PREFIX=/path/to/tessdata
python3 scripts/repair_ocr.py --doc HABITABILIDAD --dry-run
python3 scripts/repair_ocr.py --doc HABITABILIDAD --accept-residue

# Stage 2 -- needs nothing but python
python3 scripts/ingest.py --stats
python3 scripts/section_geometry.py
```
