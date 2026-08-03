# The citation guarantee: what a finding promises

Resolves [#8](https://github.com/javier-abia/urbandocs/issues/8). Fixes the
shape of every citation the engine emits, what it guarantees, what it merely
renders, and the one operation ([#6](https://github.com/javier-abia/urbandocs/issues/6)
deferred here) that reads a cited location back.

The guarantee is deliberately narrow: **a citation promises a location, not a
string.** Everything else on this page follows from that one line, and from the
fact that 94 of HABITABILIDAD's 104 pages reach the substrate through OCR.

## The citation

```
HABITABILIDAD.pdf, p.20 (impreso 16)
  Artículo 14. Obras de remodelación de viviendas › 1 › a)
  id: HAB:p20:art14.1.a

DccSUA.pdf, p.13 (impreso 13)
  SUA 1 › 2 Pozos y depósitos › 2.1 Dotación
  id: SUA:p13:2.1

HABITABILIDAD.pdf, p.102
  FICHA 06
  id: HAB:p102:§4
```

| field          | source                                    | guaranteed |
| -------------- | ----------------------------------------- | ---------- |
| `doc`          | the PDF filename, as held in `documentos/` | yes        |
| `pdf_page`     | `prov.page_no`                             | yes        |
| `printed_page` | parsed from that page's own header/footer  | no — null where the page prints none |
| section chain  | `parent_id` walk, root → match             | yes        |
| `id`           | ingest ([#4](https://github.com/javier-abia/urbandocs/issues/4)) | yes |
| `text`         | substrate `text` column                    | **no — a rendering** |

## Why the promise stops at the location

HABITABILIDAD p.20 in the tuned JSON, verbatim:

```
section_header  Artículo 14". Obras de remodelación de viviendas.
list_item       … las determinaciones de las NHV-2010 0 con las del anexo …
list_item       Que la vivienda cuente con uno cuarto de baño cerrado …
```

Three defects on one page: a stray `"` in a heading, `0` for the conjunction
`o` (191× corpus-wide, [#11](https://github.com/javier-abia/urbandocs/issues/11)),
and `uno` for `un`. Add [#21](https://github.com/javier-abia/urbandocs/issues/21)'s
recovered `≥`/`≤` (absent from EasyOCR's charset entirely), `m2` where the page
prints `m²`, and [#17](https://github.com/javier-abia/urbandocs/issues/17)'s 65
lines that never reached the substrate at all.

An architect who takes a returned string and searches the PDF for it therefore
fails on a **correct** citation. So the engine must not invite that. What it
guarantees instead is the thing that is actually measured and solid:

- page anchoring is exact — **0 of 5,895 bboxes** fall outside their own page
  across all three documents ([#14](https://github.com/javier-abia/urbandocs/issues/14)),
  including across HABITABILIDAD's OCR/text-layer seam
- the section chain is derived from `parent_id`, which
  [#32](https://github.com/javier-abia/urbandocs/issues/32) fixed to cite-prefix
  nesting rather than header adjacency
- `id` is page-scoped and unique by construction ([#4](https://github.com/javier-abia/urbandocs/issues/4))

The text ships with [#27](https://github.com/javier-abia/urbandocs/issues/27)'s
per-axis flags (`source: ocr | native`, operator trust, line-coverage) riding on
the record. Flags are **disclosure, never a filter** — same rule as #6.

This is what makes the boundary on the map hold. Commentary is not separated
because *the architect verifies at the source*; that only works if the citation
lands them on the right page and section, which is exactly and only what is
promised here.

### One thing get_page does not do

An earlier framing claimed `get_page` surfaces #17's silent drops. It does not.
A dropped line never entered the substrate, so reading the page back out of
`corpus.tsv` shows nothing missing. The drop signal is #27's flags. `get_page`
earns its place on lateral context (below), not on drop detection.

## The section field: the full ancestor chain

Not the matched unit's printed cite alone. Two reasons, both measured:

1. **A printed cite does not uniquely identify.** HABITABILIDAD p.85 prints its
   Anexo II index as `1, 2, 2, 3` — the source itself repeats
   ([#18](https://github.com/javier-abia/urbandocs/issues/18)). `Artículo 14.1.a)`
   is an address that can resolve to more than one place; page + chain resolves.
2. **The qualifier lives in the parent.** `art14.1.a`'s kitchen-space
   requirement applies only under `art14.1`'s no-new-rooms condition. A citation
   that names only the leaf states a rule the source does not state.

The chain costs nothing — `get` already walks `parent_id` for the read contract.
Rendering rule: root → match, each link its printed `cite`; where `cite` is null
(the ~4% carrying positional `§n`), fall back to the ancestor's heading text.

## The page field: PDF page primary, printed page literal

The printed-page offset is constant per document, and it self-checks. Parsing
every `page_header`/`page_footer` that is a bare number (plus DOG_2025's
`Pág. NNNNN`, which docling labels `text`, not furniture):

| doc            | pages | labelled | offset agreement | unlabelled |
| -------------- | ----- | -------- | ---------------- | ---------- |
| DccSUA         | 79    | 78       | `+0`, 78/78      | 1 (cover)  |
| DOG_2025       | 25    | 25       | `+36524`, 25/25  | 0          |
| HABITABILIDAD  | 94    | 80       | `−4`, 80/80      | 14         |

**183 labelled pages, zero disagreement.** The arithmetic to fill the 14 gaps is
therefore available and safe.

**It is not used.** Owner steer (2026-08-03): *architects hold the original PDF,
so a citation naming p.38 sends them to p.38 of the PDF — there is nothing to
correct.* `printed_page` is parsed where the page prints it and is null
otherwise; no offset is fitted, extrapolated, or interpolated. It is a courtesy
field for reading aloud and cross-checking paper, never a navigation target and
never derived.

The table above stays here as the record that the derivation was available and
declined — and as the check to rerun if a document ever arrives whose labels
disagree with themselves.

## `get_page` — off-loop, page as a real boundary

#6 cut `get_page` to this ticket. It exists, with a constraint.

```
loop        sweep → rank → get → expand          (unchanged, #32)
off-loop    get_page(doc, pdf_page)
            → [ {id, cite, label, text, flags}, … ]  bbox reading order
```

**Not a phase.** Called on judgment, when expansion's context reads incomplete.
Making it a phase pulls the agent back toward page-reading, which is the failure
#32 spent a whole ticket escaping.

**Why it exists at all.** Expansion walks up (ancestors) and down (children).
Nothing walks sideways, so a page lead-in that governs the match while being
neither its parent nor its child is structurally unreachable. #32 already killed
the naive fix: a `±N` line window holds the governing header only **58.5%** of
the time and 42.6% of it is a different section. A page is not a window — it is
a real boundary with a real column, the same shape as the `parent_id` fix.

**Cost, measured over the tuned JSON:**

| doc            | items/page avg | max | chars/page avg | max    |
| -------------- | -------------- | --- | -------------- | ------ |
| DccSUA         | 18.1           | 36  | 2,982          | 6,171  |
| DOG_2025       | 13.2           | 22  | 2,338          | 3,485  |
| HABITABILIDAD  | 41.4           | 615 | 2,090          | 12,623 |

≈900 tokens typical, ≈3.5K worst (one figure-label-dense HABITABILIDAD page),
against a sweep that already returns 637 hits on the trace query.

**Sort by bbox, never by array order.** #18 recorded body reordering as a
markdown-serializer defect. It is not only that — the JSON `texts` array is
misordered too. HABITABILIDAD p.20:

```
texts[] order   A.1.1  A.2.1  A.1.2  A.3.1  A.4     ← wrong
bbox t desc     A.1.1  A.1.2  A.2.1  A.3.1  A.4     ← the printed page
```

`get_page` sorts by `prov.bbox` (top desc, then left), and so must ingest when it
assigns positional `§n` ids.

## What this constrains

- **[#28](https://github.com/javier-abia/urbandocs/issues/28) (ingest)** — emit
  `printed_page` by literal parse only, null where absent; never fit an offset.
  Order records by bbox, not by `texts[]` position. Assert, on every run, that
  each document's parsed labels agree with one offset — not to use it, but
  because disagreement means the page furniture parse is broken.
- **[#27](https://github.com/javier-abia/urbandocs/issues/27) (fidelity flags)**
  — the flags are load-bearing here: they are what makes "the text is a
  rendering" an honest statement rather than a disclaimer. `source` (ocr/native)
  is the minimum this ticket needs.
- **[#7](https://github.com/javier-abia/urbandocs/issues/7) (form factor)** —
  four operations to wrap, not three: `search`, `get`, `get_by_cite`, `get_page`.
- **[#33](https://github.com/javier-abia/urbandocs/issues/33) (executor)** —
  `get_page` is one more column-scoped scan (`$3 == page`), which does not move
  the contest.

## Open, deliberately

- **Whether a citation renders the chain or the caller does.** The operations
  return records with `parent_id` resolved; the string above is a presentation
  of that. Where the rendering lives is #7's, since a skill and an MCP server
  differ on exactly this.
- **`printed_page` for the FICHA tail** (pp. 97–104) stays null. Those pages
  print `FICHA 06`, an identifier in a different scheme. If it turns out
  architects cite the ADENDA that way, it is a `cite`, not a page.
