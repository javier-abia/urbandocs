# Recovering the list markers that address every normative provision

Resolves [#18](https://github.com/javier-abia/urbandocs/issues/18). Measured against
`documentos/documentos-docling/docling-tuned/` (docling 2.115.0) with ground truth taken
from rendered pages of the source PDFs.

## Summary

The markers are **not lost in export and not lost in layout analysis — they are lost in
OCR**, and only in the OCR'd half of one document. Three findings, in descending order of
consequence:

1. **The tuned markdown fabricates markers.** Where docling has no marker, its markdown
   serializer numbers the list anyway, from a counter. On HABITABILIDAD p.20 the source
   prints `1.` then `a) b) c)` then `2.`; the markdown emits `1. 2. 3. 4. 5. 6. 7. 8. 9. 2.`
   — plausible, sequential, and wrong. A confidently wrong marker is worse than a missing
   one: it makes *"artículo 14 punto 2"* resolve to the wrong provision. **The markdown
   cannot be the retrieval substrate.** Only `ListItem.marker` in the JSON is evidence.
2. **Markers are recoverable glyph-exact by a second OCR engine.** Tesseract reads the
   marker column on pages where EasyOCR emitted nothing. Over HABITABILIDAD pp.1–94 this
   recovers **238 markers where docling had 29**, agreeing with all 29 docling kept, in
   **~3.5 min at no cost** (no GPU, no API, no re-conversion). Of the items that should
   carry an ordinal marker, **238 of 248 (96%)** are recovered; the remaining 10 are
   disclosed below.
3. **The recovered markers detect the silent clause drops of
   [#17](https://github.com/javier-abia/urbandocs/issues/17).** A marker printed on the page
   where no docling item starts means the provision's leading line — marker included — was
   eaten. There are **24 such orphan-marker sites** — 20 of them a clean `a)`/`b)`/`d)`
   shape, 4 noise (a page number, a measurement) — and two are hand-verified against the
   page. This is a deterministic detector for a defect that until now announced itself in no
   way.

The other two documents do not have this hole. DccSUA and DOG_2025 are text-layer parses and
their markers survive; they just need parsing out of the item text (see
[Where the markers are, per document](#where-the-markers-are-per-document)).

## Where do the markers actually go?

They are in the `DoclingDocument` — the schema has the field — but on OCR'd pages it is
almost always empty:

| Document | Pipeline | `list_item` | non-empty `marker` |
|---|---|---:|---:|
| HABITABILIDAD | OCR (pp.1–94) | 378 | 29 |
| DccSUA | text-layer | 359 | 72 |
| DOG_2025 | text-layer | 27 | 27 |

Export is not the culprit. The markdown serializer *does* emit `marker` when it is
populated — `- a) No tendrá juntas que presenten un resalto…` in DccSUA proves it. The loss
is upstream, in the OCR pass, and the item's own geometry records it: on HABITABILIDAD p.20,
the two items whose marker docling captured have `bbox.l ≈ 70` (the box starts at the
marker), while the two whose marker it dropped have `bbox.l ≈ 83.5` (the box starts after
it). The ~13pt gutter between them is where the glyph is.

The glyph is legible. Tesseract on p.20, with no Spanish model and no tuning, returns
`1.` `2.` `3.` `4.` `a)` `b)` `c)` — every marker on the page, including both that docling
dropped.

## Recover from the model, or re-derive?

**Read them. Do not re-derive.**

Re-derivation by ordinal continuity — number the items 1..n within each article, by indent
level — was prototyped and scored against the 29 surviving markers as a held-out set. It
agreed on **17 of 29**. The failures are not tuning problems:

- **The style is not a function of the indent level.** The corpus enumerates with `1.`,
  `a)`, `A.`, and `D.` at indistinguishable indents. A counter has to be told which alphabet
  to use, and the page is the only thing that knows.
- **A dropped sibling silently misnumbers everything after it.** On p.22, p.25 and p.26 the
  re-derived ordinal ran one behind the truth, in every case because an earlier item had
  been lost to a #17 clause drop. This is the disqualifying failure: re-derivation converts
  a *missing* provision into a *misnumbered* one, and every citation downstream of it is
  confidently wrong with nothing to signal it.

Reading the glyph has neither problem, and it fails loudly: when the marker cannot be read,
nothing is written.

### What the recovery pass does

`scripts/recover_list_markers.py`. Renders each page at 200 dpi, runs tesseract in TSV mode,
takes the leftmost word of each line, and keeps it if it falls in the marker gutter
(`60 < l < 140` pt) and matches the marker shape. Each surviving marker is spliced onto the
docling `list_item` whose bbox starts on the same line (`|Δy| ≤ 8` pt) at or right of it
(`-8 < Δx < 45` pt). docling bboxes are bottom-origin and tesseract's are top-origin; the
splice converts.

Marker recovery is a **closed-vocabulary** problem — digits, single letters, `.` and `)` —
which buys two things a full-text OCR pass does not get:

- **Confusables collapse deterministically.** Tesseract reads `c)` as `¢)` nine times over
  pp.1–94; since `¢` is not in the marker alphabet, the mapping back is unambiguous. Sixteen
  such repairs were applied, none of them a judgement call.
- **The result is self-checking.** Adjacent recovered markers should increment by one or
  restart at one. Over the corpus, **162 of 170 adjacent pairs are continuous**. The eight
  breaks are diagnostic rather than noise: five are a skipped ordinal (`a) → c)`) marking a
  provision lost to a #17 drop, one is the genuine `2, 2` defect in the source's own p.85
  index, and one is a false positive — the unit `m.` at the head of a line, read as a
  marker. That is the residual false-positive rate: **1 in 238**, and continuity is what
  exposes it.

The recovered values distribute as an articulado should — `a)` 47, `b)` 44, `c)` 35, `d)` 19,
`1.` 16, `2.` 16, tailing off — which is a further sanity check that the pass is reading
structure and not scavenging digits out of the prose.

Language does not matter — `-l eng` is enough, since the markers are digits and Latin
letters. The pass is therefore independent of the tesseract `spa` + `equ.traineddata` setup
that [#21](https://github.com/javier-abia/urbandocs/issues/21) needs for comparison
operators, though both are the same kind of second-engine bbox splice and belong in the same
ingest stage.

### Coverage

Of 378 `list_item`s on HABITABILIDAD pp.1–94:

| | count | |
|---|---:|---|
| marker recovered | 238 | spliced from the page |
| self-addressing | 55 | text already begins `A.1.1.`, `B.2.4` — the id is in the text |
| unordered bullet | 42 | no address to recover |
| continuation fragment | 18 | starts mid-sentence: the head line was dropped (#17) |
| TOC / front matter | 15 | index entries, no marker in the source |
| **unrecovered** | **10** | disclosed below |

So 238 of the 248 items that should carry an ordinal marker (96%) get one, and all 29
markers docling captured independently agree with the spliced value — zero disagreements.

The 10 unrecovered: one item on p.40, four on p.67 (a list wrapped around a figure, where
tesseract's line segmentation fails), and five on p.93 (a Galician-language annex form).
None sit in the articulado's binding prose.

### The orphan markers are located clause drops

HABITABILIDAD p.69 (`B.2.4 Ascensores`) prints five provisions, `a)` through `e)`. The
recovery pass splices `a)`, `c)` and `e)`, and reports `b)` and `d)` as orphans — a marker on
the page with no docling item starting on its line. Against the rendered page, both are
confirmed #17 drops:

| | source begins | docling has |
|---|---|---|
| `b)` | *Excepcionalmente, cuando la puerta de acceso a todas las viviendas esté situada a menos de 8 m…* | *…de desnivel con respeto al portal del edificio…* |
| `d)` | *Si el desnivel es de 25 m o mayor, el número mínimo de ascensores será de dos…* | *…número de viviendas ubicadas en plantas altas sea menor de 15.* |

Each lost its entire leading line, and the marker went with it. The text that survives reads
as well-formed prose, so nothing in the output announces the loss — which is exactly the
defect #17 describes. The gutter is what makes it visible: the page says there is a `b)`
here, and the model has no provision starting there.

Note what this costs if ignored. A `d)` whose threshold clause (*"Si el desnivel es de 25 m
o mayor"*) has been eaten still reads as a complete, quotable rule — with its condition
removed.

## Reconciling tuned vs tweaked

The ticket proposed splicing the `docling-tweaked` run's markers onto the tuned run's text.
**Do not.** The tweaked markdown's visible numbering is largely the same serializer
fabrication described above — on Artículo 14 it renders `a) b) c)` as `2. 3. 4.` and a list
of five cross-references as `5.`–`9.`. What is genuine in the tweaked run is only the
*duplicated inline* token (`2. 2 Esta exigencia queda limitada…` — the second `2` is the
real OCR read), which is a strictly worse signal than reading the gutter directly, and it
arrives without coordinates.

The tweaked run keeps its value for the reason
[#14](https://github.com/javier-abia/urbandocs/issues/14) recorded, but it is not a marker
source.

Two further defects in the tuned markdown surfaced while checking this, both independent of
markers:

- **Body order is not reading order.** On p.20 the JSON's bbox order gives
  `A.1.1, A.1.2, A.2.1, A.3.1, A.4` (matching the page); the markdown emits
  `A.1.1, A.2.1, A.1.2, …`. The bbox-sort repair already noted in the map's fog is needed
  for correctness, not just tidiness.
- **The source itself is not internally consistent.** HABITABILIDAD p.85 prints its Anexo II
  index as `1, 2, 2, 3` with sub-items `2.1, 2.2, 3.1, 3.2, 3.3, 3.4`. This is a defect in
  the published decree, not in the conversion, and it constrains the id design below.

## Where the markers are, per document

The three documents need three different reads, and only one needs OCR:

- **HABITABILIDAD pp.1–94** (OCR) — marker absent from the model; recover by the gutter
  splice above.
- **HABITABILIDAD pp.95–106** (native tail) — markers are present as *separate text items*
  in a fixed left column (`l ≈ 177`) with the body at `l ≈ 195`. They need attaching by
  geometry, not OCR.
- **DccSUA** (text-layer) — markers survive **inline at the head of the item text**:
  `1 La anchura de cada tramo será de 0,80 m, como mínimo.` The source prints them bare,
  with no `.` or `)` (confirmed against `pdftotext -layout`). 162 of 359 items carry one
  inline; another 72 are in the `marker` field (`a)`, `b)`, …); the remaining 126 are
  unordered bullets with the dash inline. Nothing is lost — it needs parsing, not recovery.
- **DOG_2025** (text-layer) — 27 of 29 items have a populated `marker`. No hole.

The corpus makes ~510 marker-based cross-references (`apartado X`, `punto N`, `artículo N`,
`letra X`), so this addressing is load-bearing across all three documents, not a
HABITABILIDAD quirk.

## The addressable unit

The output the navigable index ([#5](https://github.com/javier-abia/urbandocs/issues/5)) and
the citation guarantee ([#8](https://github.com/javier-abia/urbandocs/issues/8)) need is a
**provision id**: an ordered path of the addressing tokens as *printed*, rooted at the
document.

```
HABITABILIDAD · artículo 14 · punto 1 · letra c)
DccSUA        · SUA 1 · apartado 4.1 · punto 2
HABITABILIDAD · anexo I · A.1.1
```

Four rules make it usable, and each is forced by something measured above:

1. **Every component is transcribed, never generated.** A component exists only if a glyph
   for it was read off the page — from `marker`, from the inline head of the text, or from
   the gutter splice. No positional counters anywhere in the pipeline. (Forced by the
   re-derivation failure: 17/29.)
2. **"Unaddressed" is a first-class state, not a gap to fill.** The 10 unrecovered items and
   the 18 drop victims get an id that terminates at their nearest *addressable ancestor* —
   `artículo 14 · punto 1 · (unnumbered item, p.20)` — never a guessed ordinal. The agent
   must be able to say "this rule is in artículo 14 punto 1, on page 20" and stop there.
3. **Ids locate; they do not uniquely identify.** p.85 prints `2` twice. The id is therefore
   always paired with the page, and the page is part of the citation rather than an
   optional convenience — which is also what #8 needs to land an architect on the right
   place to verify.
4. **Resolution is relative.** *"del apartado c) del punto 1 de ese mismo artículo"* only
   resolves against the citing provision's own id. This is why the unit is a path and not a
   flat label: the engine walks up from where it is standing.

Self-addressing items (`A.1.1.`, `B.2.4`) already carry their path in their text and should
be parsed into the same shape rather than treated as a separate scheme — the corpus cites
them exactly like the rest (*"los puntos A.1.1 y B.1.3 del anexo I"*).

## What this constrains

- **[#4](https://github.com/javier-abia/urbandocs/issues/4) — the ingestion substrate.** The
  tuned markdown is disqualified as the substrate: it fabricates markers, and it reorders
  the body. Ingest must read the JSON. The conversion script gains a fourth pass alongside
  the repairs from #11 and #21: the marker splice, which is the same second-engine
  bbox-splice machinery #21 already requires.
- **[#5](https://github.com/javier-abia/urbandocs/issues/5) — the navigable index.** The
  index can address below article level, on 96% of markable provisions, and must represent
  the other 4% as explicitly unaddressed.
- **[#8](https://github.com/javier-abia/urbandocs/issues/8) — the citation guarantee.** A
  citation can now name what it cites. It must also carry the page, because ids repeat.
- **[#17](https://github.com/javier-abia/urbandocs/issues/17) — silent clause drops.** 24
  orphan-marker sites are located drop candidates, plus 18 items that begin mid-sentence. Between
  them the defect is no longer silent.

## Reproducing

```
python3 scripts/recover_list_markers.py \
    --pdf documentos/HABITABILIDAD.pdf \
    --json documentos/documentos-docling/docling-tuned/HABITABILIDAD.json \
    --last-page 94 --out markers.json
```

Needs `pdftoppm` (poppler) and `tesseract` with any Latin model. ~3.5 min for 94 pages,
~150 MB of rendered pages, no GPU and no API. Emits the recovered markers keyed by
`self_ref`, the orphan markers, and the continuity breaks.
