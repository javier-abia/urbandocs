# What structure docling can reliably extract from the normativa PDFs

Research asset for [#3](https://github.com/javier-abia/urbandocs/issues/3), child of the map
[Map: Agentic normativa-search engine (no-RAG spec)](https://github.com/javier-abia/urbandocs/issues/1).

**Corpus measured:** the three real PDFs in `documentos/` — `DccSUA.pdf` (79 pp, 1.7M),
`DOG_2025.pdf` (25 pp, 508K), `HABITABILIDAD.pdf` (106 pp, 15M) — against the existing conversions in
`documentos/documentos-docling/` (DccSUA, DOG_2025 only) and `documentos/documentos-pdftotext/` (all three).

All numbers below are measured from those files, not estimated.

---

## Summary

Docling is a **good but lossy** substrate. It reliably gives page anchoring, table structure, and
paragraph text. It does **not** give a section hierarchy, does not preserve the visual distinction
between normative text and commentary, drops formulas and figures entirely, and cannot handle
HABITABILIDAD at all without OCR.

**Scoping note from the owner (comment on [#3](https://github.com/javier-abia/urbandocs/issues/3)):**
*"Images are complementary but not needed to extract information from them. They come together to help
technical architects but the real laws are in text."* Dropped figures are therefore an **accepted
loss**, not a gap to close — see [Figures](#4-figures-are-placeholders-with-no-caption-or-alt-text).
That steer also forced a re-measurement of HABITABILIDAD, and **the original conclusion there was
wrong**: its content is not drawings, it is ordinary normative prose rendered as 600-dpi bitmaps. See
[HABITABILIDAD](#habitabilidad-the-law-is-in-the-text-the-text-is-a-600-dpi-bitmap).

| Feature | Docling | pdftotext |
|---|---|---|
| Page anchors | Reliable (`<!-- page-break -->`, separator semantics) | Reliable (one marker **per page**, leading) |
| Headings | Emitted, but **all flat `##`** — no levels | None at all |
| Tables | Well-formed pipe tables, high fidelity | None — flattened into prose |
| Table captions | Emitted as the preceding paragraph, not attached | Same problem, worse |
| Figures/images | `<!-- image -->` placeholder, content lost | Silently dropped |
| Formulas | `<!-- formula-not-decoded -->`, content lost | Garbled/dropped |
| Normative vs commentary | **Not distinguished** | Not distinguished |
| Running headers/footers | Inlined as body paragraphs | Inlined as body paragraphs |
| Greek/symbol chars | Corrupted to private-use glyphs | Corrupted |
| Bitmap-text doc (HABITABILIDAD) | Needs OCR (not run) | Yields nothing usable |

---

## What it gets right

### 1. Page anchoring is exact — but the two pipelines use different conventions

Docling emits `<!-- page-break -->` as a **separator**: 78 markers for 79 pages (DccSUA), 24 for 25
(DOG_2025). So **page N = (markers before the position) + 1**.

pdftotext emits one marker **per page, leading**: 79 / 25 / 106 markers for 79 / 25 / 106 pages. So
**page N = the Nth marker**.

Both are exact and verified against `pdfinfo`. They are off by one relative to each other — an index
built over a mix of the two pipelines must record which convention a file uses, or every citation
from one half of the corpus is wrong by a page.

> Correction to a note on the map: the pdftotext markdown *does* carry page markers. It lacks form-feed
> characters, but it has the same `<!-- page-break -->` HTML comments.

### 2. Tables are genuinely high fidelity

37 tables across the two converted docs (24 in DccSUA, 13 in DOG_2025). **Zero ragged tables** —
every table has a consistent column count across all its rows, and none has an empty header row.
Numeric normativa tables survive intact:

```
| Resistencia al deslizamiento R d   |   Clase |
|------------------------------------|---------|
| R d ≤ 15                           |       0 |
| 15 < R d ≤35                       |       1 |
```

Row-grouping (a group label row followed by indented sub-rows, e.g. `Zonas interiores secas` then
`- superficies con pendiente menor que el 6%`) is preserved **positionally** — legible to a reader or
an agent, but not machine-structured as a hierarchy.

### 3. Paragraph text and list structure survive

Numbered normative paragraphs come out as `- 3 Entre dos plantas consecutivas…`, keeping the
article-paragraph number attached to its text. That is enough to cite at paragraph granularity.

---

## Where it loses fidelity

### 1. No section hierarchy — every heading is `##`

326 headings in DccSUA, 21 in DOG_2025, **all at level 2**. Docling detects "this is a heading" but
never assigns a level. The document's real tree (Sección → article → 1.2 → 1.2.1) exists only inside
the heading *text*:

```
## Sección SUA 6 Seguridad frente al riesgo de ahogamiento
## 1 Piscinas
## 1.2 Características del vaso de la piscina
## 1.2.1 Profundidad
```

Hierarchy is therefore **recoverable by parsing the heading string**, not by reading markdown levels.
Any index build must do that reconstruction itself.

### 2. Ministry commentary is indistinguishable from the norm — the correctness risk

`DccSUA.pdf` is the *"con comentarios del Ministerio"* edition: the binding normative text and the
Ministry's non-binding interpretive commentary are interleaved. In the PDF they are visually
distinct (shaded blocks). **In the docling markdown they are identical** — both are `##` heading plus
plain paragraphs, with no marker, class, or wrapper separating them.

This is the highest-stakes finding. A search engine that quotes a commentary paragraph as though it
were the norm gives a technical architect a citation that does not hold up.

**A usable heuristic exists.** Of the 326 headings, **107 are numbered/structural** (`1.2.1 …`,
`Sección SUA n`, `Anejo X`, roman numerals, `Índice`) and **219 are unnumbered prose titles** —
and the unnumbered ones are overwhelmingly commentary:

```
## Aplicación del DB SUA a escaleras mecánicas, ascensores accesibles, plataformas elevadoras verticales, etc.
## Diferencias entre DB SUA y reglamentación sobre lugares de trabajo
## Ejemplos en los que se puede considerar no viable adecuar las condiciones existentes…
```

The heuristic is **numbered heading ⇒ normative; unnumbered heading ⇒ commentary**. It is not proven
exhaustively (front-matter titles like `Documento Básico consolidado` are also unnumbered and are
neither), so it needs validation before being trusted — but it is a real signal available for free in
the existing output, and it does not require re-running docling.

### 3. Formulas are dropped

5 `<!-- formula-not-decoded -->` markers in DccSUA — and they sit on **computational norms**, the
worst place to lose content:

- `La frecuencia esperada de impactos, Ne, puede determinarse mediante la expresión:` → formula gone
- `El riesgo admisible, Na, puede determinarse mediante la expresión:` → formula gone
- `La eficacia E requerida para una instalación de protección contra el rayo…` → formula gone

Any query about lightning-protection calculation retrieves the sentence introducing the formula and
then nothing. At minimum the index must flag these positions so the agent knows to open the PDF page.

### 4. Figures are placeholders with no caption or alt text

106 `<!-- image -->` markers across the two docs (75 of them in DOG_2025, a 25-page document). The
placeholder carries no caption, no number, no description — so a figure cannot even be *named*, let
alone read. In DOG_2025 the density is high enough that pages reduce to a run of consecutive
`<!-- image -->` markers with almost no text between them.

**This is an accepted loss, not a gap.** Per the owner: the figures are complementary aids for
technical architects; the binding rule is always stated in the surrounding text. Page 55 of
HABITABILIDAD is the clean illustration — a floor-plan diagram captioned `GRÁFICO 23` sits above a
full page of articulado (`Tendedero.` a/b/c) that states every dimension the diagram depicts
(`1,20 m`, `1,50 m²`, `0,20 m²`). Reading the diagram adds nothing citable.

Two consequences for the design, both cheap:

- Extracting figure *content* (OCR of diagrams, alt-text generation, figure retrieval) is **out of
  scope**. Do not build it.
- The placeholders should still be **positionally recorded** in the index, so the agent can tell a
  user "there is a figure here, open page N to see it" rather than silently omitting it. Position is
  free; content is not needed.

### 5. Running headers and footers are inlined as body text

DOG_2025 emits `Lunes, 30 de junio de 2025`, `Pág. 36540`, `DOG Núm. 123` as ordinary paragraphs, in
the middle of the content flow. Two consequences:

- They pollute grep results and break paragraph continuity across page boundaries.
- **But `Pág. 36540` is the official citation page** — the number an architect actually cites, and it
  is *not* the PDF page index (that content is on PDF page ~12). The official page number is
  available only because the footer was inlined. Stripping headers blindly would destroy it.

### 6. Symbol-font characters corrupt to private-use glyphs

7 × `U+F044` (Δ), 3 × `U+F061` (α), 2 × `U+F06D` (µ), 1 × `U+F0B1` (±) in DccSUA — Symbol-font
characters that never got mapped to Unicode. They appear in exactly the places that matter:
`Tabla B.1 Ángulo de protección <U+F061>`, and a step-height paragraph using Δ. These strings are
unsearchable and will render as tofu in any citation.

Comparison/relational operators fare fine: `≤` (33) and `≥` (29) are correct Unicode.

### 7. Sub/superscripts are split, which breaks exact-match grep

Subscripts become a space-separated token: **`Rd` is emitted as `R d`**, `Ne` appears as `Ne` in prose
but the table variant splits. A literal `grep "Rd"` misses the table that defines it. Additionally,
82 lines in DccSUA and 15 in DOG_2025 contain **multi-space runs inside sentences** (PDF
justification artifacts): `las condiciones  de  seguridad  de  utilización`. Any exact-phrase search
over this text must normalize whitespace first.

---

## HABITABILIDAD: the law *is* in the text — the text is a 600-dpi bitmap

This document is the outlier and it changes the ingestion decision. The earlier version of this
section concluded "the normative content lives in the drawings". **That was wrong**, and the owner's
comment on #3 is what prompted re-measuring it. Corrected below.

The extraction symptoms stand:

- 106 pages, 15M, **12,578 embedded raster images**.
- Its pdftotext output is 13,397 words, but **97 of 106 pages have fewer than 20 words**; the median
  page has **2 words**.
- `pdftotext -layout` on page 30 yields **one** non-empty line, page 55 yields two (`GRÁFICO 23`),
  page 80 yields four.
- The table of contents extracts as bare section numbers (`B.2.1.2.`, `B.2.6.3.`) with **the titles
  missing** — the heading text is not in the text layer.
- Fonts are `ArialMT` / `TimesNewRomanPSMT`, **not embedded, not subset, no Unicode map**.

But rendering the pages shows what the text layer is hiding. **Page 20 renders as dense articulado**
— `Artículo 13. Obras de remodelación de edificios.` with numbered clauses 1–4 and an italic
commentary line — and extracts **0 words**. Page 12 renders four lines of legal preamble citing
`artículo 129 de la Ley 39/2015` and also extracts **0 words**. This is prose, laid out as prose,
completely unextractable.

The mechanism, from `pdfimages -list`: every "image" is a **`smask` stencil at 600 ppi** driven by a
2×2 indexed-colour source (`906 0 0.846 12 10B`, `906 0 600 600 2310B`). The 12,578 images are not
photographs or drawings — they are the **glyph runs themselves**, rendered to 1-bit bitmaps at
600 dpi. The non-embedded WinAnsi fonts are a red herring; there is no text to map because the text
was rasterised at export.

Distribution of those stencils across the document (`pdfimages -list` grouped by page):

| Pages | smasks/page | What is actually there |
|---|---|---|
| 5–32 | 5–142 | Preamble + articulado, pure bitmap prose, 0 extractable words |
| 33–82 | 6–191 | `GRÁFICO 1`–`GRÁFICO 40` — **one diagram plus a full page of bitmap articulado** |
| 85–94 | 5–207 | Annex tables and conditions, bitmap |
| 95–106 | **0** | **Real text layer** — page 100 alone extracts **1,884 words** |

Two findings follow that the "content is in the drawings" framing had buried:

1. **The `GRÁFICO` pages are text pages.** Page 55 is a single floor-plan diagram above a full page
   of `Tendedero.` articulado with all its dimensions written out. There is no page in this document
   whose normative content is only a drawing.
2. **HABITABILIDAD has the same normative/commentary split as DccSUA** — pages 20 and 55 both show
   indented *italic* explanatory blocks between the numbered clauses. Whatever classifier
   [#12](https://github.com/javier-abia/urbandocs/issues/12) lands on has to work here too, and here
   the only signal available will be whatever OCR preserves of the italic + indent.

So: **no text-extraction pipeline — docling included — will produce a searchable document from it
without OCR**, exactly as before. What changes is the prognosis. OCR against crisp, born-digital,
1-bit text at 600 dpi is the easy end of the problem, not the hard end — nothing like a scanned or
skewed page — so recovery of ~94 pages of pure normative prose is likely at high fidelity. That makes
OCR the highest-value coverage work on the map, not a marginal salvage attempt.

**Docling is not installed in this environment** (`which docling` → not found, `import docling` →
`ModuleNotFoundError`). Re-running or extending conversions requires installing it first — the
existing markdown was produced elsewhere.

---

## Implications for the open tickets

**Ingestion substrate ([#4](https://github.com/javier-abia/urbandocs/issues/4)):**
Docling is the strongest available text substrate and its page anchors are trustworthy, but it is not
sufficient alone. The decision has to cover three tiers, because this corpus contains all three:
text-layer docs (DccSUA, DOG_2025), a bitmap-text doc needing OCR (HABITABILIDAD — one third of the
sample, and ~94 pages of recoverable prose, not a lost cause), and the commentary/normative
separation that docling does not encode. Whether that separation is recovered by heuristic
post-processing or by a different extraction pass is the open call. Figure *content* extraction is
explicitly not a tier — it is out of scope.

**Navigable index ([#5](https://github.com/javier-abia/urbandocs/issues/5)):**
The index cannot be lifted from markdown heading levels — there are none. It must be built by parsing
heading *strings* for their numbering. That is tractable and deterministic on the numbered 107, and
it doubles as the normative/commentary classifier. The index should also record per-file: the
page-marker convention in use, positions of dropped formulas and figures, and whether an official
page number (`Pág. NNNNN`) differs from the PDF page index.

**Citation guarantee ([#8](https://github.com/javier-abia/urbandocs/issues/8)):**
Two constraints fall straight out of this research. First, a citation must state whether the quoted
text is normative or commentary — quoting Ministry commentary as the norm is a correctness failure,
not a formatting one. Second, "page" is ambiguous: DOG_2025 has an official page number in its footer
that differs from its PDF page index, and the two conversion pipelines number pages differently. The
guarantee must pin down which page it means.

**Whole-corpus coverage:** any design that assumes "all normativa is searchable text" is already
false for one of three documents in the sample. Coverage gaps need to be visible to the agent rather
than silently returning no results. The gap is a *pipeline* gap, though, not a content gap — the law
is in the text in all three documents; in one of them the text is currently unreadable.
