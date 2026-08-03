# Fidelity disclosure: what a record carries, and what it doesn't

Resolves [#27](https://github.com/javier-abia/urbandocs/issues/27).

**Answer: no fidelity metadata on any record.** The trust vector is a function of
three columns the agent already holds — `doc`, `page`, `label` — plus one small
provenance sidecar that ingest emits. Nothing is stored per record, because
nothing needs to be.

The one axis that turned out to matter is not the one the ticket was written
about.

## Why nothing is stored

[#4](https://github.com/javier-abia/urbandocs/issues/4) ruled that fidelity flags
must live *on the record*, on the grounds that the agent only ever sees a slice,
so a warning outside the slice never reaches it. That reasoning does not survive
[#32](https://github.com/javier-abia/urbandocs/issues/32)'s substrate.

`corpus.tsv` is `id doc page cite parent_id label text norm`. Every OCR axis is
keyed on exactly `doc`, `page` and `label` — all three of which are *in the
slice*, on every returned record. A standing rule of the form

> in HABITABILIDAD, pp.1–94, figures inside `table` records are not glyph-exact

is fully evaluable against columns the agent is already holding. It does not need
to be materialised alongside them.

[#14](https://github.com/javier-abia/urbandocs/issues/14)'s finding survives
intact: trust is a vector, not a number — the same page is trustworthy for prose
and untrustworthy for tables. But a vector that is a *function* of three stored
columns does not itself need storing, and storing it would introduce the one
failure a derived value cannot have: disagreeing with what ingest actually did.

Axis by axis:

| Axis | Ticket's framing | Disposition |
|---|---|---|
| Operators ([#21](https://github.com/javier-abia/urbandocs/issues/21)) | untrusted in OCR'd tables and figures | **empty — see below** |
| Units | `m²` folds to `m2` | follows from `source == ocr`; not repaired, by owner steer |
| Addressability ([#18](https://github.com/javier-abia/urbandocs/issues/18)) | `addressed: false` on 4% | **not a fidelity axis** — stays where #4 put it |
| Text completeness ([#17](https://github.com/javier-abia/urbandocs/issues/17)) | 65 lines on 34 pages | blanket caveat, no page list |

**Addressability is not extraction damage.** A provision the page prints without
a marker is *faithfully* extracted; it simply has no printed address, so it
terminates at its nearest addressable ancestor plus page. That is a fact about
the source, not about the pipeline, and it belongs in the same column #4 gave it
— not in a trust vector.

## The operator axis is empty

The untrusted-operator surface in HABITABILIDAD pp.1–94 is `table` + `picture`
records: 58 of the 1,538 items in that range.

```
HABITABILIDAD, items by label (whole doc / pp.1–94)

  text                 2961 /  698
  list_item             419 /  378
  section_header        223 /  154
  page_header           175 /  163
  page_footer            96 /   74
  picture                76 /   56
  footnote                9 /    9
  table                   5 /    2
  caption                 2 /    2
  checkbox_unselected     2 /    2
```

**All 56 pictures carry zero text.** Docling emits them as empty placeholders,
and figure *content* is out of scope by the owner's steer on
[#3](https://github.com/javier-abia/urbandocs/issues/3). So #21's headline
hazard — the legacy engine *manufacturing* operators on line art, 105 `≤`
against a truth of 40 — never enters `corpus.tsv` at all. It was a hazard of the
recovery pass's raw output, not of the substrate built from it.

That leaves **two table records**, p.47 and p.50. Every cell of both was checked:

```
p.47 — 32 cells, 0 carrying ≥ ≤ < >
p.50 — 43 cells, 0 carrying ≥ ≤ < >
```

There is no operator to disclose. This also closes the measurement gap the map
recorded as deliberately open — *"operator fidelity in the OCR'd tables of
pp.1–94 was never checked"*. It is now checked, and the answer is that there are
no operators there to be wrong about.

## What is actually damaged: digits

The same two tables are damaged in a way no prior ticket measured.

```
p.47  Superficie E1 (estancia mayor):
        25m2 · 16m2 · 18m2 18m2 · 2Om2 2Om2 · 22m2 · 25m2

p.50  Cocina:
         5m2 ·  7m2 ·  7m?  ·  9m2 ·  9m2 · 1Om2
```

- `2Om2`, `1Om2` — letter `O` for zero. A **20 m²** and a **10 m²** minimum floor
  area, rendered as strings that are not numbers.
- `7m?` — the `²` lost to a literal `?`, distinct from the `m2` fold.
- `3 3`, `4 4`, `18m2 18m2`, `12m2 12m2` — cells duplicated across the split.
- `N'` for `Nº`; `Superficie E5_` for `E5`.

This corrects the scope of
[#14](https://github.com/javier-abia/urbandocs/issues/14)'s *"0 errors in ~46
sampled numeric tokens"*: that was measured on prose. The OCR'd tables are not
clean, and the defect is character-level substitution inside the figure itself —
strictly worse than a missing comparison operator, because `2Om2` reads as
damaged while a wrong operator reads as fine.

The owner's steer still holds and is what keeps this non-blocking: **the prose
restates every binding threshold**, so the citable statement of these limits is
elsewhere and undamaged. This is a disclosure, not a coverage gap.

## The disclosure

When a returned record is a `table` whose `doc` + `page` fall in an OCR'd range,
the response carries a line naming the figures as unverified and pointing at the
source page. It is **derived at render time** from `doc`, `page` and `label` —
nothing is stored on the record.

It fires on **2 records of ~5,900**, so it is never noise, and it never filters:
consistent with [#8](https://github.com/javier-abia/urbandocs/issues/8)'s rule
that fidelity rides along as disclosure and never as a gate, and with
[#6](https://github.com/javier-abia/urbandocs/issues/6)'s evidence-only output —
it tells the architect to verify, which is the thing the whole engine is built
to make possible.

For **#17's dropped lines**, the disclosure is a blanket caveat with **no page
list**. A dropped line never entered the substrate, so there is no record to key
a rule on. Enumerating the measured 34 pages would imply the other 60 are
verified-complete, which the coverage geometry cannot support — a mid-block drop
is invisible to it, so 65 is a floor of unknown tightness. The honest statement
is that any page in the OCR'd range may be incomplete.

## The provenance sidecar

The render-time rule needs the doc → page-range → source mapping, and nothing
holds it today. `*.pipeline.json` records `profile: "ocr"` at *document* level
only, which is too coarse: HABITABILIDAD's 5 tables are 2 in the OCR'd range and
3 in the natively-parsed tail (pp.97–101 — which were
[#21](https://github.com/javier-abia/urbandocs/issues/21)'s **ground truth**). A
document-level rule would disclaim exactly the tables proved clean.

So ingest emits the ranges it actually applied:

```
corpus.provenance.tsv

doc             from   to   source
HABITABILIDAD      1   94   ocr+equ
HABITABILIDAD     95  106   native
DccSUA             1  ...   native
DOG_2025           1  ...   native
```

Ingest *knows* these — #21's and #18's tesseract splices are bbox-region
operations it performs, so the file records what ran rather than what someone
believed. It is not per-record storage, and it scales past the three documents
prose could have covered.

## What this constrains

- **[#28](https://github.com/javier-abia/urbandocs/issues/28) (ingest)** — emit
  `corpus.provenance.tsv` alongside `corpus.tsv`, from the ranges the conversion
  passes actually covered, not from the pipeline profile. Add no fidelity column
  to `corpus.tsv`; it stays at the eight columns #32 fixed. Consider whether p.47
  joins p.50 in the set of tables skipped for cell-level search — #4 already
  skips p.50 for unresolved headers, and p.47's cells are duplicated across the
  split.
- **[#7](https://github.com/javier-abia/urbandocs/issues/7) (form factor)** — the
  disclosure renders where the citation renders. #8 left *"whether a citation
  renders the chain or the caller does"* open for this ticket; the two answers
  are the same answer, because both are presentations of a returned record and a
  skill and an MCP server differ on exactly this.
- **[#30](https://github.com/javier-abia/urbandocs/issues/30) (gold set)** — if a
  gold question's answer depends on a p.47 or p.50 figure, the graded answer is
  the prose restatement, not the table cell.

## Open, deliberately

- **Whether the two damaged tables should be repaired.** `2Om2 → 20m2` is
  unambiguous to a reader and would be a two-character fix, but #21 established
  the standing rule that a repair asserting what the page *meant* is unsound
  (`>` → `≥` was rejected on exactly this ground). Disclosure was chosen over
  repair for consistency with that rule, not because the repair is hard.
