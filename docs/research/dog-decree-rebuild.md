# Rebuilding the corpus on the DOG decree

What changed when `documentos/HABITABILIDAD.pdf` — the scanned, consolidated
IGVS edition — was replaced by `documentos/dog-habitabilidad.pdf`, the DOG decree
it consolidates, and what that cost and bought. Resolves
[#41](https://github.com/javier-abia/urbandocs/issues/41); the decision it
executes is [#39](https://github.com/javier-abia/urbandocs/issues/39)'s.

Everything below is measured against the artifacts in this commit:
`documentos/documentos-docling/docling-tuned/dog-habitabilidad.json` (Stage 1)
and `corpus/corpus.tsv` (Stage 2).

## The document

**DOG núm. 176, Decreto 128/2023**, 51 pages, natively typeset. The text-density
probe in `tools/docling-convert/main.py` chose the `text-layer` profile on its
own — median **2,336 chars/page, 0% sparse pages**, against HABITABILIDAD's 6
chars/page and 92% sparse. No `--ocr` override, no profile argument.

Conversion took ~6 minutes on CPU, against ~20 for the scanned edition.

## The OCR programme is retired, not disabled

`scripts/repair_ocr.py` was never called and needs no flag to stay out of the
way: it exits on the profile check, because the document did not convert under
`ocr`. Its three passes have no input here —

- no marker splice ([#18](https://github.com/javier-abia/urbandocs/issues/18)):
  the decree **prints** its markers,
- no line-coverage recovery ([#17](https://github.com/javier-abia/urbandocs/issues/17)):
  nothing was dropped, because nothing was read from a bitmap,
- no operator recovery ([#21](https://github.com/javier-abia/urbandocs/issues/21)):
  the comparison glyphs are in the text layer.

The script stays in the repo for the next scanned PDF. What leaves is its
*subject*, and with it the HABITABILIDAD findings of #11, #17, #18, #21 and #27,
which are now historical.

`corpus.provenance.tsv` is consequently **all-`native`** across all three
documents:

```
doc                 page_from  page_to  source
DOG_2025            1          25       native
DccSUA              1          79       native
dog-habitabilidad   1          51       native
```

Under [#27](https://github.com/javier-abia/urbandocs/issues/27) fidelity is
*derived* from `doc` + `page` + `label` rather than stored, so this is the whole
of the change: the derivation now returns a clean vector for every record in the
corpus, and the disclosure renderer has nothing to emit. There is no stale
caveat to retract because there was never a stored flag to go stale — which is
the property #27 chose the derivation for.

## The doc key is `D128`, and `HAB` is left dead

Ids read as `D128:p22:A.2.2`. Two things ride on the choice:

- The `DOC_CODES` fallback derives a code from the first three alphanumerics, so
  `dog-habitabilidad` would have become `DOG` and collided with DOG_2025. Ids
  would have stopped being unique across the corpus.
- `HAB` is deliberately **not** reused. The decree renumbers every page, so a
  stale `HAB:p20:art14.1.a` must fail to resolve rather than quietly land on
  whatever provision now occupies that address. A dead prefix fails loudly.

The `doc` column stays `dog-habitabilidad`, matching the filename on disk:
[#8](https://github.com/javier-abia/urbandocs/issues/8) promises a *location*, so
the document a citation names has to be the file an architect can open.

## Acceptance

The bands [#39](https://github.com/javier-abia/urbandocs/issues/39) measured on
the raw decree, re-asserted on the ingested `corpus.tsv`. The current corpus had
**zero of every symbol in the first band** across HABITABILIDAD pp.1–95.

Stage 2 is fast and rerun on every change, so the bands live in
`src/urbandocs/check_corpus.py` rather than in a transcript:

```bash
python -m urbandocs.ingest && python -m urbandocs.check_corpus
```

| band | measured | required |
| --- | --- | --- |
| `²` | 65 | ≥ 65 |
| `≥` | 3 | ≥ 3 |
| `º`/`°` | 10 | ≥ 10 |
| `±` | 1 | ≥ 1 |

All 65 `²` survive ingest: **11 in body text, 54 in tables**, which is why the
band is asserted after `serialize_table` rather than on the Stage 1 JSON.

**The 7 angle thresholds are present**, and exist nowhere in the old corpus:
`15º`×2 (one of them `≥ 15º`, one `± 15º`), `45º` (as `< 45º`), `60º`×2, `90º`×2.

**The 4 phantom values are gone**: `1,5 m`, `120 m`, `30 cm`, `7 m` — each
present in the OCR'd corpus and absent from the decree. One caution for anyone
re-running this check: the decree writes `7 m 2` (docling splits the
superscript), which is an **area** and not the phantom `7 m` *length*, so the
assertion needs a `(?!\s*[²2])` guard or it reports a false failure.

### The hand-verified one

`A.2.2`'s `60º` — the condition deciding whether two paramentos count as
*enfrentados*, and therefore whether the width rule applies at all. In the OCR'd
corpus `HAB:p43:§6` read:

> si el ángulo que forman entre sí es menor de 60 Si el ángulo … es mayor 0 igual
> a no se co

Both the symbol and the value were gone, in **prose** — which is what
[#39](https://github.com/javier-abia/urbandocs/issues/39) found and why #27's
"the prose restates every threshold" did not generalise. It now reads, across
two records under the correct heading:

```
D128:p22:§10   A.2.2 < A.2   ...si el ángulo que forman entre sí es menor de 60º. Si el ángulo que forman los
D128:p22:§11   A.2.2 < A.2   dos paramentos es mayor o igual a 60º no se considerarán paramentos enfrentados, por lo
```

## What the rebuild forced on ingest

Three defects the new document exposed. None is habitability-specific in cause;
two were live and unmeasured on DOG_2025 before this document surfaced them.

### 1. The masthead lands inside provision text

docling files `CVE-DOG:`, `ISSN`, `Depósito legal` and the URL under
`page_header`/`page_footer`, so the label filter
([#14](https://github.com/javier-abia/urbandocs/issues/14)) eats them. It does
**not** catch the running `DOG Núm. NNN` masthead, which arrives labelled `text`
in the `body` layer — 49 pages of the decree, 21 of DOG_2025.

On a further **6 pages it is not a standalone item at all**: docling appends it
to the body paragraph that runs to the foot of the page, so it lands *inside* a
provision (`…se simplifica la estructu ra del índice y DOG Núm. 176`). Measured
corpus-wide it is always trailing, at the exact end of the field, so it is
stripped rather than matched whole. **4 of those 6 are DOG_2025**, where the
splice was live before the decree exposed it.

Matched on the masthead's own shape and not on `Núm.`, because the same band at
the top of the page prints `Pág. 52775` — the official citation page, kept
deliberately (#8, #14). A geometric filter would have taken both. 47 `Pág.`
records survive.

### 2. Line-break hyphens, and the dash they are not

The Diario Oficial sets two justified columns and breaks words across lines.
docling rejoins the lines but keeps the hyphen and the gutter, in either order:

```
super -ficie      70 sites in the decree, 127 in DOG_2025
simi- lares        2 sites in DccSUA
```

Left alone these defeat [#32](https://github.com/javier-abia/urbandocs/issues/32)'s
sweep on exactly the terms that carry the rules — `superficie`, `fachadas`,
`ventilación`, `paramento`, `parámetros`, `comunicación` are all split.

The hazard is that the same documents use a bare hyphen as a **parenthetical
dash**: `espacios libres -públicos o privados- que no cumplan`. Joining that
fuses two real words (`privadosque`), which is worse than the split it fixes —
and **the rule that was already in `normalize()` did exactly that**. Audited
across the corpus it fired on 16 sites, of which only **2 were genuine**
(DccSUA's `simi- lares`, `perso- nas`); the other 14 were parenthetical closers
it corrupted. It was net-harmful and had never been measured.

The discriminator is **pairing**, and it is exact on all 219 sites: a
parenthetical dash opens (`word -lower`) and closes (`lower- `); a line-break
hyphen never closes. Measured — 9 of the decree's 70 openers find a closer, at
17–55 characters; DOG_2025 has 127 openers and **zero** closers; DccSUA has 2
pairs. The window is set at 200, well beyond the observed maximum.

Verified against `norm`, since `search` matches `norm` and `get` returns `text`
(#6). `text` is left verbatim: a citation promises a location and never that the
string matches the page glyph for glyph (#8), so rewriting the verbatim text to
make it searchable would trade the guarantee the engine makes for one it does
not.

Result on the two documents that are *not* changing: `similares` 5→5 and
`personas` 79→79 (the genuine joins survive), `inscripcion` 2→3, `proteccion`
143→145, `senalada` 1→2, `administraciones` 8→9 (line-break hyphens now closed),
and the 2 corrupted fusions gone. Residual ` -x` in DccSUA + DOG_2025: **2
sites, both correct parentheticals**.

**Residue, disclosed**: a hyphen split across two *records* cannot be rejoined by
a per-field rule. `D128:p22:§9` ends `…dos paramentos que delimitan una pieza
están en-` and `§10` opens `frentados si el ángulo…`. The concept stays reachable
— `enfrentados` appears whole in `§11` and `§13` — but the token at the seam does
not.

### 3. Most headings are not labelled as headings

Of the 114 items in the decree that print a letter-dotted cite and a title, only
**37 got `section_header`**; the other 77 arrive as `list_item` or plain `text`.

The consequence is not cosmetic. Without them the spine held **no `A.2`, `A.2.1`
or `A.2.2` at all**, so every provision on pp.19–22 — the ticket's own
hand-verify target among them — inherited `A.1.2` from five pages back. That is a
**wrong ancestor chain**, which is the one thing a citation does promise (#8),
and it is the failure shape #32 named when it replaced header-adjacency with
cite-prefix nesting: the nesting rule was right, but the cites never reached it.

Ingest now promotes an item to the spine when it prints a letter-dotted cite and
a title. Keyed on the shape `parse_cite` already recognises, which is this
document's numbering scheme: **it promotes 0 items in DccSUA and 0 in DOG_2025**,
which number `Sección SUA n` / `n.n` / `Anejo A` and nothing respectively — so
the rule provably cannot regress them. Measured, not assumed.

The contents pages (pp.14–17) match the same shape, and that is harmless rather
than a concession. Nesting is by cite **prefix**, so the index builds a stack
that the body's first heading pops in full — `A.1` is not an extension of `B.3`.
The index entries were already records before this; only their label changed.
This is not a retraction of #5/#17's "do not source the spine from the contents
page": the spine is sourced from the body, and the index simply cannot parent it.

With the promotion, `A.2.2` is on the spine and the `60º` rule chains to
`A.2.2 < A.2`, as shown above.

## The substrate now

```
corpus records        2,455   (DccSUA 1,306 · dog-habitabilidad 832 · DOG_2025 317)
section_header          515
distinct parent_ids     495
```

Addressability, which is what #18's whole recovery programme existed to buy:

| | HABITABILIDAD (after the tesseract splice) | Decreto 128/2023 (no recovery pass) |
| --- | --- | --- |
| unaddressed list items | 315 | **46** |
| list items carrying a printed cite | — | 220 of 266 (**82%**) |

The decree prints its markers, so the marker splice, the closed-vocabulary
repairs and the ordinal-continuity self-check are all unnecessary here. #18's
finding stands for scanned documents; it simply has no subject in this corpus.

Ancestor-chain depth across the decree's 832 records: 49 at depth 0 (top-level
headings and preamble), 273 at 1, 306 at 2, 198 at 3, 6 at 4.

## Known and accepted loss

Per [#39](https://github.com/javier-abia/urbandocs/issues/39), and not
compensated for here. The decree prints only what it modifies, so these leave the
corpus: articles **1, 2, 5, 6, 10, 12, 17, 18, 20** of Decreto 29/2010 — the
*Definiciones* among them — the unmodified points of 3/7/8/9/11/13/15, **ANEXO
III**, and the **whole ADENDA** (2,308 records / 63,097 chars, already native).

Under [#9](https://github.com/javier-abia/urbandocs/issues/9) no rule forces a
hit per document, so queries landing in those ranges return empty with nothing to
announce it. Adding a compensating rule is deliberately *not* this work: whether
those ranges need sourcing, and from where, is the map's open fog — the DOG
original of 29/2010 publishes them natively and does not overlap the decree, but
the trigger is unmeasured until
[#30](https://github.com/javier-abia/urbandocs/issues/30)'s gold set exists.

## Two consequences for whoever picks up #30

- **Every `HAB:p*` id is void**, and `D128:p*` ids are not a renaming of them —
  the pagination is different and so is the text. Gold citations must be authored
  against this corpus.
- **DOG_2025's positional `§n` ids shifted** as a side effect of dropping its 21
  masthead records: removing a record renumbers the positional ids after it on
  that page. Its cite-bearing ids are unaffected. Nothing depended on the old
  numbering, since #30 has not been built yet.
