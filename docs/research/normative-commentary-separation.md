# Separating normative text from Ministry commentary

Resolves [#12](https://github.com/javier-abia/urbandocs/issues/12). Measured against
`documentos/documentos-docling/docling-tuned/` (docling 2.115.0). Prototype:
`scripts/classify_commentary.py`.

## Answer in one line

The numbered-heading heuristic from #3 **fails**. The **left edge of each block's
`prov.bbox`** works, and on DccSUA it is exact on every page inspected — 7 pages,
123 blocks, 0 errors after one fix.

## Why the heading heuristic fails

#3 proposed splitting DccSUA's 326 headings into "numbered/structural = normative"
and "unnumbered prose title = commentary". Cross-checked against the left-edge
classification over all 369 tuned section headers:

| | left edge says normative | left edge says commentary |
|---|---|---|
| **numbered heading** | 160 | 0 |
| **unnumbered heading** | 33 | 176 |

The numbered half is clean — **no numbered heading is commentary**, so that half of the
heuristic holds. The unnumbered half does not: **33 of 209 unnumbered headings are
normative** (16%), and they are not edge cases. They are the cover, the `Introducción` /
`Artículo 12` preamble, and — the damaging one — 30 entries of **Anejo A Terminología**
(pp. 61–73), which are prose titles (`Alojamiento accesible`, `Ascensor accesible`, …)
and fully binding: the DB's definitions of *itinerario accesible*, *ascensor accesible*
and the rest live there and are cited by the articulado.

That 33 is the *best case*, after tuning the numbering pattern to also accept
`Anejo`/`Apéndice`/roman numerals/`B.1.1.1.3`-style anejo numbering; the naive
"starts with a digit" reading of #3 leaves 52. The residue does not shrink further —
a glossary entry has no number to find.

So the heuristic silently drops the glossary out of the normative corpus. It also
cannot classify anything that is *not* a heading, which is most of the document.

## The signal that works: bbox left edge

DccSUA states its own convention on p. 2:

> Los comentarios […] figuran con este tipo de letra, **con esta sangría** y con una
> línea vertical fina en el margen izquierdo.

Font and the margin rule are lost (`TextItem.formatting` is empty), but the *sangría*
— the indent — survives as `prov.bbox.l`. The distribution is sharply bimodal:

```
71pt  438 blocks   normative body
89pt   94          normative nested list, level 2
93pt   23          normative nested list, level 3
108pt  13          normative nested list, level 4
──────────────── 34pt of empty space ────────────────
148pt 606 blocks   commentary body
161pt  15          commentary nested / quoted
```

Threshold at the midpoint of the gap: **125pt**. It is derived per-document, not
hardcoded — the script takes the two most common left values, ignores values carried
by <0.5% of blocks, and splits the widest remaining gap.

### Two rules on top of the threshold

1. **Centred blocks do not obey it.** A `caption` is centred, so its left edge tracks
   the block's *width*, not its indent — `Tabla B.3 Dimensión de la retícula` sits at
   231pt on a page with no commentary on it. Captions inherit the class of the nearest
   aligned block instead. This was the only error class found in validation, and fixing
   it took the error rate to zero. Figures (`pictures`) are centred the same way and
   are out of scope for content anyway.
2. **`tables` carry a usable left edge.** They are not centred, and the one table
   embedded in a commentary block (p. 2, the version list) lands at 147pt while all 22
   normative tables land at 64–108pt.

### Guard: the rule is document-specific

The script refuses to classify when the two dominant margins are <20pt apart, because
below that the bimodality is ordinary list nesting, not a commentary block. DOG_2025
(10pt) and HABITABILIDAD (12pt) both trip the guard — correctly, see below.

## Error rate

**DccSUA: 0 errors across 7 pages verified block-by-block against the rendered PDF**
(pp. 2, 23, 31, 37, 59, 61, 76 — chosen to cover interleaving, tables, formulas,
footnotes, glossary and front matter). Page 31 is the hard case — four normative
paragraphs each followed by its own commentary block — and is perfect.

Of the 1,285 classified blocks the only structurally ambiguous one is the p. 23 table
caption at 123pt, 2pt below the threshold; the caption-inheritance rule takes it out of
the left-edge path entirely, so it is classified correctly for the right reason.

**The dangerous direction — commentary read as normative — was not observed at all.**
Commentary is typeset rigidly at 147.5pt/161pt; nothing at those margins is binding and
nothing binding appears there.

### The one known miss: front matter

Page 2 is a third class. It is neither normative nor commentary — it is the publication
history and the legend, and it says of itself *"Este texto consolidado no tiene valor
jurídico"*. It is typeset on its own inset grid at 142pt, which is on the commentary
side of the threshold, so all 16 of its blocks are labelled commentary.

This is the safe direction (non-binding text labelled non-binding), and the script
detects and reports the page rather than hiding it: any page whose own dominant margin
is on the commentary side but differs from the document-wide commentary margin gets
flagged. The symmetric case — front matter typeset at a *smaller* third margin — is
**not** detectable this way, since below the threshold a third margin is
indistinguishable from a nested-list indent. DccSUA has no such page.

## The other two documents

- **DOG_2025** — no commentary edition at all; zero occurrences of "comentario" in the
  text. The guard is what should fire here, and does.
- **HABITABILIDAD** — *is* a commentary edition, but its legend (p. 5) says commentary
  is marked *"con este tipo de letra, color y con una línea vertical en el margen
  izquierdo"*. **No sangría.** The indent signal does not exist in this document, and
  the two signals that do — font colour and the vertical rule — are both destroyed by
  OCR. Its `prov.bbox` is unusable for a second reason: coordinates run to `r=1155pt`
  on a 595pt-wide page, so OCR boxes are being emitted in image-pixel space rather than
  page space. It also fragments to ~34 blocks/page, i.e. line-level, not paragraph-level.

  HABITABILIDAD therefore needs a different signal. The promising one is that the
  document is a *scan*: colour and the vertical margin rule are still present in the
  page pixels, even though nothing carries them into the doc model. Recovering them
  means sampling the rendered page image — per-line ink colour, or detecting the
  vertical rule — and joining back by bbox. Untested; tracked separately.

## What this unblocks

Normative/commentary separation on DccSUA is recoverable by **post-processing the
existing tuned JSON**. It does not force a different extraction pass, and it does not
depend on anything docling currently drops. The ingestion substrate decision (#4) can
assume every block carries a `normative | commentary` tag, derived at ingest from
`prov.bbox.l` — for indent-marked documents. For colour-marked documents the tag has
to come from the page image, which is a different pipeline stage and a cost the
substrate design has to account for.

## Reproducing

```bash
python3 scripts/classify_commentary.py documentos/documentos-docling/docling-tuned/DccSUA.json
python3 scripts/classify_commentary.py documentos/documentos-docling/docling-tuned/DccSUA.json --dump-page 31
python3 scripts/classify_commentary.py documentos/documentos-docling/docling-tuned/DccSUA.json --emit /tmp/dccsua.jsonl
```
