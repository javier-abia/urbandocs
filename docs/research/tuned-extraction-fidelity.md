# Extraction fidelity of the tuned docling corpus

Research asset for [#14](https://github.com/javier-abia/urbandocs/issues/14), child of the map
[Map: Agentic normativa-search engine (no-RAG spec)](https://github.com/javier-abia/urbandocs/issues/1).

**Supersedes** `docs/research/docling-extraction-fidelity.md` ([#3](https://github.com/javier-abia/urbandocs/issues/3),
PR [#10](https://github.com/javier-abia/urbandocs/pull/10)), which measured *default-settings markdown*
and flagged its own lossy half as provisional. This document re-measures the same questions against
the tuned artifacts produced by [#13](https://github.com/javier-abia/urbandocs/issues/13).

**Measured against:** `documentos/documentos-docling/docling-tuned/{DccSUA,DOG_2025,HABITABILIDAD}.json`
(`DoclingDocument`, docling 2.115.0), with `docling-default/` as the naive baseline and the source PDFs
in `documentos/` as ground truth. All numbers below are counted from those files. Page renders for the
OCR spot-check were produced with `pdftoppm -r 150`.

---

## Summary

The tuned conversion is the right pipeline and the **JSON is the artifact to build on** — but it is
not uniformly trustworthy, and the untrustworthy part is concentrated in exactly the place the
engine's value lives.

| # | #3 finding | Status against tuned JSON |
|---|---|---|
| 1 | Heading hierarchy: all flat `##` | **Changed — still unusable.** Levels exist but the tree is *inverted*, not merely shallow. |
| 2 | Tables high fidelity, 37, zero ragged | **Confirmed.** 41 tables, zero ragged, headers improved. One DccSUA table de-structured. |
| 3 | OCR needed for HABITABILIDAD | **Fixed on coverage, new defect found.** Digits survive; **thresholds and units do not**. |
| 4 | Grep-hostile text | **Improved, not solved.** Glyph damage is now small and deterministic; whitespace is not. |
| 5 | Running headers inlined as body | **Fixed enough.** Labels are accurate; filtering is safe on all three documents. |
| — | (#12) HABITABILIDAD bboxes in image-pixel space | **Refuted.** See [correction](#correction-to-12-the-bboxes-are-fine). |

**The one finding that should change a design decision:** across the 94 OCR'd pages of HABITABILIDAD —
the entire articulado — there are **zero `≥` and zero `≤` characters and zero `m²`**. Not "mostly
wrong": categorically absent. A dimensional rule is *(operator, number, unit)*; the numbers come
through clean and the other two components do not. See
[§3](#3-ocr-accuracy-digits-are-safe-thresholds-are-not).

---

## 1. Heading hierarchy is not a navigation spine

Levels are populated now, so the naive "all flat `##`" finding is fixed in the literal sense.

| Doc | section_headers | Level distribution |
|---|---|---|
| DccSUA | 369 | L1 16, L2 89, L3 26, L4 32, L5 9, **L6 197** |
| DOG_2025 | 21 | L1 3, L2 17, L3 1 |
| HABITABILIDAD | 223 | L1 6, L2 116, L3 2, L4 9, L5 3, **L6 87** |

The large L6 bucket is the visible symptom. The actual defect is worse: **the level is not a rank.**

### The tree is inverted

Walking DccSUA's headings in document order through Sección SUA 1 (pp. 14–22):

```
p 14 L5   Sección SUA 1 Seguridad frente al riesgo de caídas
p 14 L6     1 Resbaladicidad de los suelos
p 17 L6     3 Desniveles
p 17 L2   3.1 Protección de los desniveles          <-- child of a L6, emitted at L2
p 18 L2   3.2 Características de las barreras de protección
p 18 L4     3.2.1 Altura
p 18 L4     3.2.2 Resistencia
p 18 L2   3.2.3 Características constructivas       <-- sibling of 3.2.1/3.2.2, emitted 2 levels up
p 20 L6     4 Escaleras y rampas
p 20 L2   4.1 Escaleras de uso restringido
```

`3.1` is a child of `3` and sits four levels *above* it. `3.2.3` is a sibling of `3.2.1` and sits two
levels above it. Level 6 is docling's floor, so once the real depth passes it the assignment stops
tracking depth at all.

Cross-tabulating dotted-number depth against assigned level over the 115 numbered DccSUA headings:

| Dotted depth | Levels assigned |
|---|---|
| `N` (e.g. `3`) | L2 ×21, L4 ×2, L6 ×21 |
| `N.N` (e.g. `3.2`) | L2 ×22, L3 ×22 |
| `N.N.N` (e.g. `3.2.1`) | L2 ×1, L3 ×1, L4 ×25 |

Every depth is split across levels, and the splits overlap. 50 of 368 consecutive heading pairs jump
deeper by more than one level.

The same rank also gets different levels in different places: all 9 `Sección SUA n` headings appear
**twice** — at **L1** on pp. 12–13 (the table of contents) and at **L5** on pp. 14–52 (the body). An
index built on levels would nest the whole document under its own TOC.

`Anejo` is L1, `Artículo` is L6, `Índice` is L1. HABITABILIDAD is no better: `Artículo 15` is L4 while
`Artículo 2` and `Artículo 4` are L5.

### What L6 actually contains

In DccSUA, only 22 of 197 L6 headings carry a number or structural keyword. The rest are Ministry
commentary block titles (`Resbaladicidad en aseos`, `Bandas antideslizantes`, `Escaleras de 'tipo
barco'…`) — interleaved with the real article headings (`1 Resbaladicidad de los suelos`) at the
*same* level. Commentary separation is out of scope for this effort, but the consequence for the index
is in scope: **L6 mixes structural and incidental headings, so it cannot be filtered by level either.**

### Consequence for [#5](https://github.com/javier-abia/urbandocs/issues/5)

`SectionHeaderItem.level` must be **discarded**, not repaired. A numbering-based post-pass over the
heading *text* is required.

That post-pass cannot be numbering-only, because
[#12](https://github.com/javier-abia/urbandocs/issues/12) established that 33 of DccSUA's 209
unnumbered headings are binding normative text (the `Artículo 12` preamble and 30 entries of
**Anejo A Terminología**). The shape that satisfies both constraints: **numbering builds the spine;
unnumbered headings attach as leaves of the nearest preceding numbered ancestor.** Nothing is dropped,
and nothing depends on the emitted level.

Two smaller inputs to that design: the TOC copy must be de-duplicated (identical heading text, lower
page number, no body between it and the next heading), and DOG_2025 has no numbered headings at all
(21 headings, zero matching a numbering pattern) — it is a 25-page bulletin whose structure lives in
the text (`2. Extracto ambiental.`), so the spine builder must degrade gracefully to a flat list.

---

## 2. Tables: confirmed high fidelity, one structural loss

| Doc | Tables | Ragged | Empty | With `captions` | No column header |
|---|---|---|---|---|---|
| DccSUA | 23 | **0** | 0 | 15/23 | 4 |
| DOG_2025 | 13 | **0** | 0 | 1/13 | 9 |
| HABITABILIDAD | 5 | **0** | 0 | 2/5 | 1 |

**Zero ragged tables** across all three — every table has a consistent column count across every row.
#3's strongest finding holds.

**The 37 → 36 count is one real loss, not a recount.** DccSUA goes 24 (naive) → 23 (tuned). Comparing
table positions page by page, every naive table has a tuned counterpart except the one on **p. 68**
(`Mecanismos y accesorios` — grifería, espejo, mecanismo heights). Its *content* survives: the strings
`Mecanismos de descarga`, `gerontológico` and `Espejo, altura del borde` are all present on p. 68 as
`list_item` and `text` items. The **table structure** is gone — a two-column normative table demoted to
prose. Content-safe, structure-lossy, and it is a table of accessibility dimensions.

**Headers improved.** Three naive tables had empty or partial header rows that the tuned run recovers:

| Page | Naive header | Tuned header |
|---|---|---|
| 23 | *(empty)* | `Anchura útil mínima (m) en escaleras previstas para…` |
| 50 | *(empty)* | `Cubierta metálica \| Cubierta de hormigón \| Cubierta de madera` |
| 61 | *(partial)* | `Dimensiones mínimas, anchura x profundidad (m) Vivienda \| En edificios…` |

**Captions are attached** via `TableItem.captions` — 15/23 in DccSUA — which is the fix #3 predicted.
The 9 header-less DOG_2025 tables are genuine two-column key/value blocks, not extraction failures.

HABITABILIDAD's 5 tables sit on pp. 47, 50, 98, 102, 103 — pp. 98/102/103 are in the natively-parsed
tail. The single header-less one is in the OCR region, consistent with
[#11](https://github.com/javier-abia/urbandocs/issues/11)'s "OCR-region tables lose their column keys".

---

## 3. OCR accuracy: digits are safe, thresholds are not

Splitting HABITABILIDAD at the profile seam — pp. 1–94 are `force_full_page_ocr`, pp. 95–106 are
natively spliced — separates the defects cleanly. Furniture excluded from both counts.

| | OCR region pp. 1–94 (22,202 words) | Native tail pp. 95–106 (9,124 words) |
|---|---|---|
| `≥` | **0** | 92 |
| `≤` | **0** | 40 |
| `<` / `>` | 18 / 3 | 21 / 13 |
| `m²` | **0** | 103 |
| `m2` | 5 | 3 |
| `m?` | **34** | 0 |
| ` 0 ` for conjunction *o* | 178 | 0 |
| ` Y ` for conjunction *y* | 133 | 0 |

Every defect class is confined to the OCR region, and within it the loss of `≥`, `≤` and `m²` is
**total, not partial**. This is the finding that matters most: the articulado of the habitability
norms — 94 pages of minimum dimensions — **cannot express a threshold**.

### Spot-check against the rendered pages

Comparing extracted text against `pdftoppm` renders of two OCR-region pages:

**p. 49 (PDF p. 45)** — of ~22 numeric tokens in the body, **all digits and decimals are
character-correct** (`4`, `2,60 m`, `0,15`, `2,20 m`, `10 %`, `A.2.2`). Every failure is an operator or
a unit:

| Ground truth | Extracted | Class |
|---|---|---|
| `superficie útil ≥ 12 m²` | `superficie útil 2 12 m?` | `≥` → digit `2`; `m²` → `m?` |
| `de superficie útil < 12 m² y aquellas que tengan ≥ 12 m²` | `de superficie útil 12 m? y aquellas que tengan 2 12 m?` | **`<` silently deleted** |
| `se incremente en 4 m² o más` | `4 m? 0 más` | `o` → `0` |
| `de 2,60 m, no computándose` | `de 2,60 m, n computándose` | `no` → `n` |
| `cuarto de baño/aseo` | `cuarto de bañolaseo` | `/` → `l` |

The `≥` → `2` substitution occurs 5 times corpus-wide in the pattern `2 <number> m?`
(`2 12 m?` ×3, `2 3,5 m?`, `2 5 m?`). The deleted `<` is the worse case: it leaves a **well-formed,
grammatical, and wrong** rule. "Estancias de superficie útil 12 m²" does not read as damaged text.

**p. 76 (PDF p. 72)** — 24 numeric tokens, again zero digit errors, but two silent drops:

- `Si se trata de vías con aparcamientos en línea o en ángulo **< 45º será de 3,30 m, y si se** trata
  de vías sin acceso a plazas…` — the emphasised span is missing, removing an entire dimensional
  threshold (`3,30 m` at `< 45º`) mid-sentence.
- `**Todos los edificios dispondrán** de las plazas de aparcamiento…` — leading words dropped, and
  `Ley` displaced to the end of the item.

Both confirm the silent-clause-drop class already ticketed as
[#17](https://github.com/javier-abia/urbandocs/issues/17); the new information is that the drops land
**on numeric provisions**, not just prose.

### Figure-interior text leaks into the body

p. 49's `GRÁFICO 16` diagram contributes `text` items to the body stream: `2,6`, `S.U.2 12 m?`,
`520,50m` (the render shows `S ≥ 0,50 m²`), `8`, `espacio no computable`. These are indistinguishable
from body text by label. They are separable by bbox containment against `pictures[]` — which
[the correction below](#correction-to-12-the-bboxes-are-fine) confirms is viable.

### List markers

57 of 419 `list_item`s carry a `TextItem.marker` (29 of 378 in the OCR region — **7.7%**). Observed
markers: `-`, `1.`–`5.`, `a.`–`d.`, `a)`, `b)`, `D.`. The tuned pipeline lifts the marker *out of* the
item text and then populates it for a small minority, so the tuned markdown reads
`- En vestíbulos, pasillos…` where the source reads `b) En vestíbulos, pasillos…`.

This corpus cross-references *by marker* (`el apartado c) del punto A.2.2` appears in the p. 49 text
above), so this is a live gap for the citation guarantee
([#8](https://github.com/javier-abia/urbandocs/issues/8)) and already ticketed as
[#18](https://github.com/javier-abia/urbandocs/issues/18). Measured here only to size it.

### Formulas

5 in DccSUA, decoded to LaTeX with subscripts intact — #3's "formulas dropped" is fixed. Two caveats:
the output is character-spaced (`1 0 ^ { 6 }` for 10⁶, `5 , 5` for 5,5), so it is as grep-hostile as
the body text; and one carries an OCR error (`\text{impactos/afão}` for *impactos/año*).
HABITABILIDAD has 0 formulas.

---

## 4. Grep-hostility: small deterministic damage, large whitespace damage

| | DccSUA | DOG_2025 | HABITABILIDAD |
|---|---|---|---|
| Private-use glyphs | **13** (4 distinct) | 0 | 0 |
| Split subscripts (`R d`) | 18 | 1 | 16 |
| Broken hyphenation (`pre- vistas`) | 19 | 2 | 4 |
| Multi-space runs inside text | **879** | 137 | **1466** |

**Private-use glyphs are down to 13 and are a fixed Symbol-font mapping** — a 4-entry repair table,
verified in context:

| Codepoint | Context | Correct |
|---|---|---|
| `U+F0B1` | `la contrahuella no variará más de ␣ 1 cm` | `±` |
| `U+F061` | `gire formando un ángulo ␣ con él` | `α` |
| `U+F044` | `␣ L  distancia en m función de` | `Δ` |
| `U+F06D` | (2 occurrences) | `μ` |

**Split subscripts survive in body text** even though formula enrichment fixed them inside formulas:
`R d` ×5, `C 1` ×3, `B o` ×3 in DccSUA. So `Rd ≤ 15` in the source is unfindable by exact match, and the
same document contains the *correct* `R _ { d }` form inside its LaTeX. Two spellings of one symbol.

**Whitespace is the dominant hostility.** 879 and 1,466 multi-space runs are justification artifacts
inside otherwise-clean strings (`Condiciones  y  características  de  la  información`). Any exact-match
lookup fails on these unless whitespace is collapsed.

### Normalization the lookup layer needs

Applied to both the index and the query, in this order:

1. **Whitespace collapse** — runs of spaces to one; strip. Highest yield, zero risk.
2. **Symbol-font glyph map** — the 4 entries above. Deterministic.
3. **Hyphenation rejoin** — `pre- vistas` → `previstas`, guarded against genuine compounds (`30-40 mm`).
4. **Subscript rejoin** — `R d` → `Rd` for the known symbol set; index both spellings rather than
   picking one.
5. **Unit folding** — `m²` ≡ `m2` ≡ `m?`. All three spellings occur in HABITABILIDAD (107 / 67 / 35
   corpus-wide including tables).
6. **OCR letter/digit folding, HABITABILIDAD only** — standalone `0` ≡ `o`, `Y` ≡ `y`. Query-side
   equivalence is safe; an *ingest-side* rewrite is not, because `0` is also a legitimate digit.

**Deliberately not on this list: repairing `≥`/`≤`.** They are absent, not corrupted — there is no
signal left to normalize. `2 12 m?` → `≥ 12 m²` is a *guess*, and a wrong guess inverts a legal
threshold. This has to be fixed at ingest by re-running OCR on the affected pages, or accepted and
disclosed. See [what this leaves open](#what-this-leaves-open).

---

## 5. Furniture: labels are accurate, filtering is safe

`furniture.children` is **empty in all three documents** — the header/footer items are labelled but
live in `body`. Filtering is therefore **label-based** (`label in {page_header, page_footer}`), not
container-based.

| Doc | page_header | page_footer | Body text eaten |
|---|---|---|---|
| DccSUA | 83 (1.05/pg) | 82 (1.04/pg) | **none** |
| DOG_2025 | 25 (1.00/pg) | 56 (2.24/pg) | **none** |
| HABITABILIDAD | 175 (1.65/pg) | 96 (0.91/pg) | **none** |

Checked item by item:

- **DccSUA** — all 83 headers are the running title `D ocumento B ásico SUA…` or a section name
  (`Anejo A. Terminología`, `con comentarios SUA 1…`, `MINISTERIO DE VIVIENDA Y AGENDA URBANA` on p. 1).
  78 of 82 footers are a bare page number. The other 4 are `Articulado:` / `14 junio 2022` /
  `Comentarios:` / `15 julio 2024` on p. 2 — the edition dates. Not body text, but **worth keeping as
  document metadata rather than discarding**, since they date the consolidated text.
- **DOG_2025** — 25 headers, all the CVE identifier; 56 footers, all the URL / ISSN / depósito legal.
- **HABITABILIDAD** — 1.65 headers/page because 85 pages emit the running title *and* the page number
  as two items. Footers are the `NOTAS:` form label (84×) and the COAG disclaimer. All 13 items
  exceeding 12 words are the disclaimer or the DECRETO 128/2023 legend, not articulado.

### DOG_2025's official `Pág.` markers survive

The 25 `Pág. 36525`…`Pág. 36549` markers are labelled **`text`**, not `page_footer`. They pass through
a furniture filter untouched. This matters because they are the *official* page numbers of the Diario
Oficial — a citation into DOG_2025 should quote `Pág. 36525`, not the PDF's sequential page 1 — and the
two differ by a constant 36,524 that the index can carry per document.

---

## Correction to [#12](https://github.com/javier-abia/urbandocs/issues/12): the bboxes are fine

#12 reported that HABITABILIDAD's tuned `prov.bbox` coordinates are in image-pixel space, citing
`bbox.r` reaching 1155 pt on a page declared 595.32 × 841.92. **That is wrong, and it is worth
correcting because it was recorded as blocking every bbox-derived design.**

The overflowing boxes are **entirely on pp. 97–104 and zero in the OCR region** (pp. 1–94). Those eight
pages are genuinely **A3**:

```
pdfinfo -f 94 -l 106 documentos/HABITABILIDAD.pdf
  Page  96 size:  595.32 x 841.92 pts (A4)
  Page  97 size: 1190.55 x 841.89 pts (A3)
  ...
  Page 104 size: 1190.55 x 841.89 pts (A3)
  Page 105 size:  595.32 x 841.92 pts (A4)
```

and the JSON declares them correctly (`pages["97"].size.width == 1190.55`). The original measurement
compared every box against page 1's size.

Validating each box against **its own page's** declared size:

| Doc | bboxes outside their own page box |
|---|---|
| DccSUA | 0 / 1491 |
| DOG_2025 | 0 / 424 |
| HABITABILIDAD | 0 / 3980 |

**0 of 5,895.** All three documents use `coord_origin: BOTTOMLEFT` consistently. Page anchoring and
bbox geometry are exact across the whole corpus, including across the OCR/native seam.

Two designs previously recorded as blocked on a scale factor are therefore **unblocked**: dropping
figure-interior text by containment in a `pictures[]` bbox, and bbox-sorting to repair local reading
order. (#12's other surviving finding — the `prov.bbox.l` indent discriminator — is unaffected, and its
subject is now out of scope anyway.)

---

## What this leaves open

Facts, not decisions — the decisions belong to
[#4](https://github.com/javier-abia/urbandocs/issues/4) and
[#5](https://github.com/javier-abia/urbandocs/issues/5).

1. **The missing `≥`/`≤` cannot be normalized away.** Three routes exist: re-run OCR on pp. 1–94 with a
   character allowlist that includes the mathematical operators; accept the loss and have the index mark
   HABITABILIDAD's articulado as *threshold-unreliable* so the agent never quotes a comparison from it
   as exact; or treat pp. 95–106 (which are clean) as the authoritative text where they overlap. This is
   the single largest open risk to the citation guarantee and is not covered by any existing ticket.
2. **Per-document fidelity is not one number.** HABITABILIDAD is trustworthy for digits and untrustworthy
   for operators and units — the same page is both. Whatever #4 records as fidelity metadata needs to be
   per-axis, not per-document.
3. **The DccSUA p. 68 table** is de-structured. Recoverable by hand if the substrate wants all
   accessibility-dimension tables as tables.
4. **Two spellings of one symbol** (`R d` in prose, `R _ { d }` in LaTeX) argue for indexing both
   normalized forms rather than choosing a canonical one.

---

## Reproducing

Measurement scripts were run ad hoc against the JSON; the load-bearing checks are small enough to
restate:

```python
import json
d = json.load(open('documentos/documentos-docling/docling-tuned/HABITABILIDAD.json'))

# §3 — the threshold finding
ocr = '\n'.join(t.get('text') or '' for t in d['texts']
                if t['prov'] and t['prov'][0]['page_no'] < 95
                and t['label'] not in ('page_header', 'page_footer'))
print(ocr.count('≥'), ocr.count('≤'), ocr.count('m²'))   # -> 0 0 0

# the #12 correction
pg = {int(k): v['size'] for k, v in d['pages'].items()}
bad = sum(1 for t in d['texts'] for p in (t.get('prov') or [])
          if p['bbox']['r'] > pg[p['page_no']]['width'] + 1)
print(bad)                                                # -> 0
```
