# Sweep first, rank from the hits: the loop without an index

A revision of [#6](https://github.com/javier-abia/urbandocs/issues/6)'s lookup
loop. The four phases stay; their order changes and the L1/L2 index layer is
deleted. Routing stops being an artifact the ingest builds and becomes a sort
over the sweep's own hits.

The case rests on three measurements: L1 routing fails on a query that is a
section title verbatim; a `±N`-line context window recovers the governing
ancestor only 58.5% of the time; and at this corpus size an index buys back
about 120 tokens per query against a sweep that has to run regardless.

Figures below were produced against a prototype build of the flat schema
([#28](https://github.com/javier-abia/urbandocs/issues/28) has not shipped it
yet). Once `corpus.tsv` exists the sweep and rank figures reproduce with the
`awk` given inline; the section-geometry figures need a small script that does
not exist yet — see *Open, deliberately*.

## What changed

```
  #6 as designed                      this revision
  ─────────────────                   ─────────────
  1 ROUTE   read L1 → pick docs       1 SWEEP   awk over `norm`, corpus-wide
            load L2s → pick sections  2 RANK    group hits by parent_id
  2 READ    get() routed sections     3 GET     text + ancestors + children
  3 SWEEP   corpus-wide, always       4 EXPAND  in-corpus cites, one hop
  4 EXPAND  ancestors + children
```

Deleted: `read_index()`, `read_doc_index(DOC)`, `corpus.index`, `<DOC>.index`.
Three of five tool operations survive — `search`, `get`, `get_by_cite`.

Kept unchanged: the mandated term floor, the corpus-wide guarantee, the read
contract from [#4](https://github.com/javier-abia/urbandocs/issues/4), the one
refine hop, evidence-only output, `text`/`norm` symmetry from
[#14](https://github.com/javier-abia/urbandocs/issues/14).

## Why L1 goes

#6 called routing advisory and spent three paragraphs defending the rule that it
may never gate the sweep. The measurement that prompted this revision is that L1
was not merely advisory — it was actively wrong on an easy query.

Query: `dimensiones de las rampas de circulación`. HABITABILIDAD holds a section
whose heading is that string verbatim, at pp. 74–76. The L1 digests:

```
DccSUA        | 79pp 291sec | accesible edificio riesgo accesibles altura
                              edificios anchura puertas seguridad personas
                              mínimo puerta escalera ejemplo tabla usuarios
                              acceso escaleras itinerario rampa figura
                              circulación ascensor distancia entrada
HABITABILIDAD | 101pp 183sec | acceso ancho estancia altura mínima mínimo
                              gráfico ventilación iluminación planta pieza
                              piezas determinaciones estancias edificio
                              edificios obras paramentos interior cocina
                              cuadrado galicia excepción mínimas podrán
```

DccSUA's line carries `rampa` and `circulación`. HABITABILIDAD's carries none of
the three content words. Routing picks DccSUA and never consults HABITABILIDAD's
L2 — where line 86 is an exact title match.

The failure is at L1, not L2, and it is structural rather than fixable by
widening. Frequency rank of the query terms within each document:

| term | HABITABILIDAD | DccSUA |
|---|---:|---:|
| `dimensiones` | 75 | 208 |
| `circulacion` | 124 | 64 |
| `rampas` | **365** | 137 |
| `rampa` | **797** | 55 |
| `garajes` | 175 | 756 |

The digest is 25 terms. Surfacing `rampas` for HABITABILIDAD needs N≈365 — at
which point every document's line contains `altura`, `ancho`, `superficie`, and
the index has stopped discriminating. Token cost is survivable; the loss of
signal is not.

**The root cause is that a frequency digest assumes a topically homogeneous
document.** HABITABILIDAD covers viviendas, garajes, patios, instalaciones and
definiciones across 3,393 body items; one 25-term bag averages that
heterogeneity away. DccSUA is homogeneous (accessibility), which is why its
digest works and why the design validated cleanly against it.

TF-IDF makes it worse, not better: `rampa` is shared vocabulary (48 occurrences
in DccSUA, 4 in HABITABILIDAD), so inverse document frequency penalises exactly
the term needed. HABITABILIDAD's distinctive terms are `estancia`, `pieza`,
`vividera` — the vivienda mass already crowding the digest.

## Why ranking from hits works instead

Group the sweep's hits by `parent_id` and score each section by **how many
distinct query terms** landed in it. Against the trace query below, both target
sections rank 8th and 9th of 613 sections — top 1.5% — from the sweep alone.

Distinct-term count beats raw hit count as the key. Sorting on raw hits floats
`B.2.5. Trasteros` (10 hits, topically wrong) above both correct sections.

This is not a cheaper index. It is not an index: there is nothing to build, tune,
re-derive when a document is added, or keep in context. And it removes the
advisory-versus-binding problem structurally — routing derived *from* the sweep
cannot gate the sweep, so the rule no longer needs defending in prose.

## Why not a `±N` window

The tempting simplification is to drop structure entirely: sweep with `grep`,
return 30 lines above and below, let the agent read. Measured against the corpus,
it fails on both axes.

```
ancestor header inside ±30 window        58.5%   (2643 / 4515 body items)
mean share of window from other sections  42.6%
windows >50% foreign content              40.4%
distance to header  p50 18 | p75 87 | p90 208 | max 382
sections >30 items  4.1% of sections — but 58.1% of all body items
```

**It misses the governing qualifier four times in ten.** Long sections are rare
but hold most of the content; p90 distance to the header is 208 items. For those
hits the window returns 60 lines with no heading in them, and nothing in the
output distinguishes that case from a successful one. Silent, not detectable.

**Nearly half of what it returns is a different rule.** In a compliance corpus
that is the dangerous failure rather than mere waste. From p101, ten lines apart:

```
DIMENSIONES DE LAS RAMPAS DE CIRCULACIÓN PARA VEHÍCULOS.
  Ancho libre mínimo de las rampas de circulación:  3,00 m
  …
DIMENSIONES DE LAS VÍAS DE CIRCULACIÓN Y DISTRIBUCIÓN.
  Anchos mínimos: Con aparcamientos en batería ≥ 5,00 m
```

Both read "ancho libre mínimo". Different sections, different rules, **3 m versus
5 m**. A flat window returns them as one undifferentiated block.

**And it cannot be applied to a sweep at all.** 1,000 hits × 60 lines × ~30
tokens is 1.8M tokens. The cheap-hits-then-selective-read split is forced by the
hit count, not chosen for elegance — `±N` is a lossy implementation of `get`,
not an alternative to it.

The fix is one column. `parent_id` is exact at any section length, costs one
integer per row, and is derived from structure docling already emits.

## Why no index at any tier

The sweep is mandatory — that is what #5's residual buys. An index can only save
money by letting you skip something, and the sweep is the thing that cannot be
skipped. **Every index is therefore additive**, and has to earn its cost against
a baseline that runs anyway.

What it could earn is better ranking: fewer sections opened. But ranking is
already free from the hits. A perfect index moves the trace's targets from ranks
8 and 9 to ranks 1 and 2 — about 8 lines of ranked list, ~120 tokens, $0.0006.

| approach | build (20 docs) | per query | verdict |
|---|---|---|---|
| sweep + hit-derived rank | 0 | 7.6K tok, $0.055 | baseline |
| wider frequency digest | 0 | +10K tok resident | dead — N≈365 destroys discrimination |
| TF-IDF digest | 0 | +10K tok resident | dead — penalises shared vocabulary |
| title index | 0 | +39K tok resident | works, but is what sweep-first deletes |
| LLM section digests | ~$9.50 one-time, re-run per change | +tokens resident | strictly worse than titles — in the trace the title *was* the query |
| embeddings | ~$0.10 one-time | negligible | see below |

Embeddings are the only serious contender and would plausibly have fixed the L1
failure: `rampas de circulación para vehículos` and a query about `garaje` are
semantically close despite sharing no content word. They still lose here, on four
properties of this corpus:

- **Numbers.** The payload is thresholds. Embeddings match sections *about*
  widths without distinguishing 3 m from 3,30 m from 5 m.
- **OCR damage.** `0`≡`o`, `Y`≡`y`, the dropped clause on p76. Query-side variants
  against exact match are auditable; vector similarity over damaged text degrades
  silently.
- **The guarantee changes shape.** A sweep states a fact about the corpus —
  *swept `ancho` across 5,128 items, 106 hits, 12 opened*. Vector retrieval states
  a fact about a model — *top 20 by cosine*. The first has a bounded, re-derivable
  residual; that is how #5 measured 18% at all.
- **[#12](https://github.com/javier-abia/urbandocs/issues/12)'s steer.** An engine
  whose recall depends on `awk` is easier to defend to an architect than one whose
  recall depends on an embedding model's grasp of Galician building vocabulary.

**The reason indexes lose is that the corpus is small.** 5,128 records now, ~36K
at 20 documents, ~8 MB of TSV, ~50 ms for a full scan. Indexes exist to avoid
full scans; here the full scan is free.

## Where the answer flips

Sweep cost is the *return*, not the scan, and it scales linearly:

| corpus | worst-term hits | sweep return | $/query |
|---|---:|---:|---:|
| 3 docs | ~640 | 7.6K tok | $0.055 |
| 20 docs | ~4,500 | 54K tok | $0.20 |
| 200 docs | ~45,000 | 540K tok | **$2.70** |

Around 100–200 documents the ranked hit list stops being free. At that point an
index earns its place — as a **reranker over sweep hits**, never as a pre-filter
before them. Reranking preserves the corpus-wide guarantee and only reorders what
to open; a pre-filter reintroduces exactly the failure L1 just demonstrated.

Timing is not the constraint at any of these sizes. A 5-term sweep over a
simulated 20-document corpus (35,896 records) takes 527 ms in naive Python and
well under 20 ms indexed, against 10–30 s of model latency per query.

## The substrate

One flat table. No JSON, no `jq`, no database.

```
id  doc  page  cite  parent_id  label  text  norm
```

`text` is verbatim, exactly what the page printed. `norm` is
[#14](https://github.com/javier-abia/urbandocs/issues/14)'s pipeline. `search`
matches `norm`; `get` always returns `text`.

All operations are column-scoped `awk` in a single pass:

```bash
# phase 1 — sweep, cite-only return shape
awk -F'\t' '$8 ~ /\brampa/ {print $1"\t"$2"\t"$3"\t"$5}' corpus.tsv

# phase 3 — children
awk -F'\t' '$5=="hab:74:1212"' corpus.tsv

# phase 3 — get by id, verbatim
awk -F'\t' '$1=="hab:75:1236" {print $7}' corpus.tsv

# phase 4 — cite lookup, may return several (#18)
awk -F'\t' '$4=="tabla 1.2"' corpus.tsv
```

Ancestors are a `parent_id` walk upward.

`jq` was considered and rejected: the docling JSON is 6.6 MB across three
documents (~46 MB at twenty), it re-parses on every invocation, and its nesting —
`prov` arrays, `$ref` chains — is precisely what ingest exists to flatten away.
SQLite with FTS5 is the right answer somewhere past 200 documents and premature
now.

## A worked trace

> «¿Qué ancho mínimo debe tener la rampa de un garaje de 120 plazas?»

**Normalize.** #14's pipeline, then HABITABILIDAD's query-side OCR variants
(`0`≡`o`, `Y`≡`y`). Terms, each swept alone — never only as a phrase:

```
must:  ancho  minimo  rampa  garaje  plaza  120
may:   anchura  aparcamiento  vehiculo
```

**Sweep.** Corpus-wide; nothing gates it.

| term | hits | | term | hits |
|---|---:|---|---|---:|
| `minimo` | 155 | | `aparcamiento` | 65 |
| `ancho` | 106 | | `garaje` | 49 |
| `plaza` | 74 | | `vehiculo` | 49 |
| `rampa` | 72 | | `120` | 5 |
| `anchura` | 62 | | | |

637 hits, ~12 tokens each ≈ 7.6K tokens. `120` fires but misses — the corpus
states the rule as *más de 100 vehículos*. The variant costs almost nothing and
the floor requires it.

**Rank.** Group by `parent_id`, score by distinct terms matched.

```
terms  hits  section id       heading
    7    29  hab:100:3051     B.2.6. GARAJES COLECTIVOS
    6    17  hab:72:1160      B.2.6.1 Área de acceso y espera.
    6    14  dcc:46:809       2 Características constructivas
    6    10  dcc:65:1147      Plaza de aparcamiento accesible
    5    15  hab:76:1250      B.2.6.3. Áreas de aparcamiento
    5    11  dcc:27:504       4.3.2 Tramos
    5    10  hab:70:1116      B.2.5. Trasteros
    5     9  hab:101:3673     DIMENSIONES DE LAS RAMPAS DE CIRCULACIÓN…
    5     8  hab:74:1212      Dimensiones de las rampas de circulación…
    5     8  dcc:47:824       3 Protección de recorridos peatonales
```

`hab:74:1212` is the section L1 could not reach at any digest width.

**Get.** Ancestors by `parent_id` walk; children by matching on it.

| id | p | text |
|---|---:|---|
| `hab:74:1213` | 74 | pendiente máxima **18 %** tramos rectos, **14 %** curvos, medida sobre el eje |
| `hab:74:1214` | 74 | (GRÁFICO 39 Y 40) |
| `hab:75:1236` | 75 | ancho libre mínimo **3 m**; garaje >100 vehículos → dos rampas de 3 m, **o** una única de **6 m**; en todos los casos **+0,30 m** en la cara exterior de los giros |
| `hab:76:1240` | 76 | radio de giro mínimo **3,50 m**, borde interior |
| `hab:76:1241` | 76 | altura libre mínima **2,30 m**, crítica 2,10 m en elementos aislados |

`hab:75:1236` answers the question, and the ancestor chain is what makes it
usable: 120 > 100 selects the second sentence, and `B.2.6 GARAJES COLECTIVOS` is
what establishes it applies to collective garages at all.

From the ficha at `hab:101:3673`, one rule **absent from the articulado**:

```
hab:101:3683   Para > 100 vehículos y acceso único → 5,00 m.
```

Surfaced as a discrepancy. The engine reports both and rules on neither.

**Expand.** `(GRÁFICO 39 Y 40)` is a figure pointer — listed with what it names,
never resolved, per [#3](https://github.com/javier-abia/urbandocs/issues/3).
Fidelity flags ride along: p101 records sit on the untrusted table surface per
[#21](https://github.com/javier-abia/urbandocs/issues/21) and return with the
warning attached, filtered by nothing.

**Envelope.**

```
answer:      none — evidence only
searched:    9 terms, corpus-wide, 3 documents, 5128 body items
returned:    637 hits → 10 sections ranked → 2 opened → 19 records
unopened:    627 hits across 71 other sections
pointers:    1 figure (GRÁFICO 39 Y 40, p75) — not resolved
flags:       4 records on HABITABILIDAD pp.1–94 table surface (#21)
discrepancy: articulado p74–76 vs ficha p101 — ficha adds
             "acceso único → 5,00 m", absent from the articulado
```

The unopened tail is a number, not a verdict. No completeness claim anywhere.
~11K input tokens ≈ $0.055.

## What the trace exposed

Three defects, all in the prototype ingest rather than the design. Recording them
because they are what a trace is for.

1. **The parent walk climbs siblings, not ancestors.** `B.2.6.2. Vías de
   circulación` → `B.2.6.1 Área de acceso` is a sibling chain. The prototype
   assigns `parent_id` by *most recent header*, and docling's `section_header`
   label carries no nesting level. The fix is to derive level from the cite prefix
   — `B.2.6.2` is a child of `B.2.6` — which the numbering already encodes. **This
   is load-bearing**: the whole argument for `parent_id` over `±N` rests on the
   chain being real.
2. **Children include the next section's header** (`hab:76:1242`,
   `hab:101:3687`). Boundary marker, not content. Off-by-one.
3. **Children include figure OCR fragments.** `hab:75:1218`–`1235` — `máx`, `Q;`,
   `eje`, `5`, `8`, `<30 cm PLANTA` — sit physically between two headers and so
   inherit the parent. 18 of 24 children of `hab:74:1212` are figure noise. Needs a
   label filter at ingest, which is also how #3's figure boundary gets enforced in
   practice.

None touch the four-phase shape or the schema.

## What this hands downstream

- **[#7](https://github.com/javier-abia/urbandocs/issues/7)** — three operations
  to wrap rather than five. `read_index` and `read_doc_index` are gone.
- **[#8](https://github.com/javier-abia/urbandocs/issues/8)** — unchanged. `get`
  returns verbatim `text` with `id`/`cite`/`page`.
- **[#9](https://github.com/javier-abia/urbandocs/issues/9)** — strengthened. The
  trace surfaced a real articulado-versus-ficha discrepancy without being asked to
  look for one.
- **[#28](https://github.com/javier-abia/urbandocs/issues/28)** — emit
  `corpus.tsv` with the eight columns above. `parent_id` must come from cite-prefix
  nesting, not header adjacency. Filter figure-label items out of the body. Stop
  emitting `corpus.index` and `<DOC>.index`.
- **[#30](https://github.com/javier-abia/urbandocs/issues/30)** — the gold set now
  has one more question to settle: does distinct-term ranking put the governing
  section in the top *k*?

## Open, deliberately

- **The ranking result is an existence proof, not a recall figure.** Ranks 8 and 9
  of 613 on one query. #30 is what tells you whether that holds across thirty
  questions or whether this one was lucky in having a section title that matched.
  If it does not hold, the fix is a reranker over sweep hits — not an index in
  front of them. The structural argument survives either outcome.
- **No reproduction script yet.** The sweep and rank figures reproduce from the
  `awk` above once #28 emits `corpus.tsv`. The section-geometry figures — ancestor
  distance percentiles, `±30` window recall, cross-section bleed — came from an
  ad-hoc probe and need a committed script to be re-derivable.
- **N=1 is untouched** by this revision and still rests on #6's upper-bound
  branching figure.
- **Snippet and hit-line width** stay unspecified; ~12 tokens for a cite-only hit
  is the sizing assumption here, not a decision.
