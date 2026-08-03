# Cross-document coverage: a retrieval guarantee, not a contradiction verdict

Resolution of [#9](https://github.com/javier-abia/urbandocs/issues/9), which was
charted as *cross-document contradiction detection*. The title is a misnomer and
the ticket's own premise is the first thing that changed: the engine does not
detect contradictions, because detecting one is a ruling and the engine hands
back evidence ([#6](https://github.com/javier-abia/urbandocs/issues/6),
[#8](https://github.com/javier-abia/urbandocs/issues/8)).

What it owes instead is **coverage**: when a parameter is governed in more than
one document, every document's rule reaches the architect, each with its own
citation, side by side and unreconciled. The architect applies the hierarchy.

Figures come from `scripts/prototype_sweep_rank.py`, run against the tuned
docling JSON. `corpus.tsv` does not exist yet
([#28](https://github.com/javier-abia/urbandocs/issues/28)), so a section is
approximated as *nearest preceding `section_header` in bbox order* rather than
by cite-prefix nesting — the substitution #32 flagged as a defect. Token
magnitudes and rank orderings hold; individual rank numbers will shift.

## The corpus only has one cross-document pair

DOG_2025 is not a norm. It is the Ayuntamiento de Vigo's PGOM approval
announcement (art. 82.2 LSG) — **0** threshold lines (`X,XX m`, `≥ N`, `m²`),
**0** hits for `escalera`, `puerta`, `rampa`, `patio`, `ventilación`. The whole
cross-document surface in today's sample is DccSUA ↔ HABITABILIDAD.

They overlap heavily by entity — `puerta` 168/31, `escalera` 142/64, `ascensor`
69/46, `rampa` 79/13, `garaje` 21/32 (DccSUA/HABITABILIDAD) — and the overlaps
are not contradictions:

- **Door clear width.** DccSUA: `anchura libre de paso ≥ 0,78 m` (accessible
  itinerary, leaf at maximum opening). HABITABILIDAD: `puerta de acceso …
  ancho libre mínimo de 0,90 m` (dwelling entrance). Different scope, both bind.
- **Stair landings.** HABITABILIDAD does not restate DccSUA, it defers to it:
  `La meseta debe tener el mismo ancho que la escalera (DB SUA)`.

A national CTE DB, an autonomous habitability decree and a municipal PGOM layer
by design — minimum, additional, local. Divergent numbers are the normal case.
Equal-rank same-scope incompatibility, the thing "contradiction" names, is rare
here; the common case is *the same parameter regulated in several places at
once*, which is a retrieval problem.

## Vocabulary divergence is real, and stemming closes it

The two documents name the same parameter with different words, near-disjointly
(line counts, DccSUA / HABITABILIDAD):

| word | DccSUA | HABITABILIDAD |
|---|---:|---:|
| `anchura` | 75 | **0** |
| `ancho` | **6** | 101 |
| `pieza` | 1 | 138 |
| `estancia` | 3 | 149 |
| `recinto` | 18 | 2 |
| `aparcamiento` | 50 | 17 |
| `garaje` | 18 | 31 |

Two failure classes with different fixes. **Morphology** — `ancho`/`anchura`,
one root inflected differently — dies to stem matching on `norm`: `anch` reaches
80/101 and both documents become visible. **Synonymy** — `pieza`/`estancia`/
`recinto` — does not: `estanc` is still 3/149.

Stemming is what the owner means by *semantic search* (2026-08-03): search
`anch`, not `ancho` or `anchura`. No vectors, no model, nothing added to the
substrate — the no-embeddings constraint from
[#32](https://github.com/javier-abia/urbandocs/issues/32) is untouched. The
semantics live in the agent: it picks the query terms, reads the heading chains,
and judges which sections are on topic.

### The synonym map is deferred, and it was never load-bearing

A curated cross-document term map (`pieza ≈ estancia ≈ recinto`) was designed
and then declined for v1 by the owner (2026-08-03): architects share the
vocabulary, documents largely do too, and the map should only be reconsidered
if the gold set ([#30](https://github.com/javier-abia/urbandocs/issues/30))
shows real cross-document misses.

The measurement supports deferring it. Expanding `pieza → pieza|estancia|
recinto` on *superficie mínima de la pieza* moved DccSUA's best section from
rank **33 to rank 36** — the expansion ranked the other document *down*. DccSUA
genuinely does not regulate room floor area (that is habitability's domain; DB
SUA covers safety of use), and its rank-33 section is `5 Limpieza de los
acristalamientos exteriores`, noise.

Deferring the map also retires **slot collapsing**, which existed only to stop a
synonym set scoring as several distinct terms and inflating a section's rank.

### Silence is a valid answer

`ventil` appears 98 times in HABITABILIDAD and **0** times in DccSUA — correct,
since ventilation is DB HS, not DB SUA. Any rule of the form *every document
must return something* manufactures false parallels: it presents an unrelated
national section as the counterpart to a habitability rule. A false parallel is
worse than an omission, because it costs the architect their trust in the tool
rather than a glance. This is why a reserved-slot-per-document cutoff is
rejected outright rather than kept as a fallback.

## The guarantee is that two phases may not truncate

No new phase. #32's loop stands: `sweep → rank → get → expand`. Coverage is a
property of what those phases are forbidden to cut.

The cost asymmetry decides where cutting is allowed. Three probes:

| query | sections | hits | ranked list | hit lines (12 tok each) |
|---|---:|---:|---:|---:|
| ancho libre de paso, puertas | 137 | 455 | **2.8K** | 5.5K |
| superficie mínima de la pieza | 199 | 755 | **4.1K** | 9.1K |
| plaza de aparcamiento, dimensiones | 202 | 592 | **4.3K** | 7.1K |

A `get` record with ancestors and children runs ~300–600 tokens. So the
**complete** ranked section list — every section with a hit, every document,
nothing dropped — costs about what 7–10 records cost. Truncating it saves
nothing worth having and is the only way a second document disappears without a
trace.

Hence:

1. `sweep` is corpus-wide and ungated (already settled in #32).
2. `rank` emits its **whole** section list, ~3–4K tokens.
3. The cutoff is the agent's judgment over that list — **not** a top-N.
4. `get` is where cost is actually spent, so that is what judgment restricts.

A fixed N drops a rank-33 section unconditionally. Judgment drops it when the
heading chain reads `5 Limpieza de los acristalamientos exteriores` and keeps it
when the chain reads `Anchura de paso libre en puertas de itinerarios
accesibles` at rank 2. No numeric rule separates a correctly-deep rank from a
miss; the heading chain does.

On the `puertas` probe both documents' governing sections land at ranks **1 and
2**; on `plaza de aparcamiento`, at **1 and 3**. Cross-document coverage is not
scarce once the list is not cut.

## Heading chains, not headings

Ranking lines carry the section's **full ancestor chain**, not its leaf:

```
HABITABILIDAD p70   B.2. CONDICIONES DE LOS ESPACIOS COMUNES DEL EDIFICIO > B.2.5. Trasteros
DccSUA        p31   1 Resbaladicidad de los suelos > 1.1 Impacto con elementos fijos
HABITABILIDAD p65   B.2. … > B.2.1. Portal. > B.2.1.1. Acceso.
```

Cost: **+212 tokens** over the whole 137-section list (2,811 → 3,023), about 1.5
tokens per section.

This supersedes an earlier proposal to attach a matched line to sections whose
heading is thin. That proposal came from measuring the wrong unit: of 137
sections, 113 headings looked informative and 24 did not — but `B.2.5.
Trasteros`, `4.3.3 Mesetas`, `B.2.1.1. Acceso.` are only thin as leaves. Under
their parents they are unambiguous. Owner's steer (2026-08-03): the chain is the
unit the agent judges on. It is also **cheaper** than the patch it replaces
(+212 against ~+500 tokens) and it serves all 137 sections rather than 24.

One residue: `A.3. > A.3.2.` on HABITABILIDAD p.99 — ranked **7th** — where both
levels lost their titles to
[#17](https://github.com/javier-abia/urbandocs/issues/17)'s dropped-title
defect. The same cite carries its title elsewhere in the same document
(`A.3.2. Dimensiones superficiales y lineales`, p.57), so ingest can backfill a
bare heading from another occurrence of the same cite. Deterministic, no OCR
pass, closes the last of the 137. Note for #28.

## Deference is a second path, and #6 mislabelled it

HABITABILIDAD cites `DB SUA` / `SUA n` on **11** lines and the CTE on **42**;
DccSUA points back at Galicia **once**. The linkage is real, explicit, and
one-way.

#6 classified pointers by the shape of the cite string: `Ley 39/2015` and
`DB SI` name norms the corpus does not hold, so they were *external* — meaning
"cannot follow". `DB SUA` fell in the same bucket. But **DccSUA is DB SUA**; the
check that was missing is corpus membership, not string shape. The owner
confirms filenames will move toward printed names (`DB SUA`, `PGOM`/`PXOM`), so
the check is a lookup against document names and aliases.

With it, `expand` — which already follows in-corpus cites one hop — follows a
deference too: landing on `La meseta debe tener el mismo ancho que la escalera
(DB SUA)`, it opens DccSUA and returns the stair rule beside the line deferring
to it.

This path owes nothing to wording, which is what makes it worth having
alongside the lexical one. Two limits: it is **asymmetric** (42 lines one way,
1 the other), so it serves habitability questions far more than national ones;
and these cites address a document or a chapter (`SUA 1`, `SUA 4`), not an
article, so following one lands on a section to search rather than on a finished
answer. #6's N=1 refine bound is unaffected.

## What the architect receives

Provisions and citations. No ranking, no scores, no hit counts, no
"found in 2 documents" banner — rank is internal machinery, a work queue.

When two documents govern, both provisions arrive **side by side, each with its
own complete citation** (file, PDF page, full ancestor chain, `id` — #8), and
**unreconciled**: no "0,90 m overrides 0,78 m", no "these conflict", no "the
stricter applies". Placing them side by side is the entire deliverable. Which
one governs is a legal judgment, and it belongs to the architect or to the
downstream expediente agent, which this map rules out of scope.

## Constrains

- **[#7](https://github.com/javier-abia/urbandocs/issues/7)** — the form factor
  must hand the agent a 3–4K-token ranked list per query and let it choose what
  to open. A wrapper that imposes a fixed page size on results breaks the
  guarantee.
- **[#28](https://github.com/javier-abia/urbandocs/issues/28)** — stem matching
  in `search`; heading ancestor chains available on ranking lines; document-level
  cites resolved against corpus membership (names + aliases), not string shape;
  bare headings backfilled from another occurrence of the same cite.
- **[#30](https://github.com/javier-abia/urbandocs/issues/30)** — needs
  cross-document questions specifically, whose complete answer spans both
  documents. Under all-or-nothing scoring, returning only the habitability rule
  when DB SUA also governs is wrong, not partial. This is the only instrument
  that separates a correct deep rank from a miss.
- **[#33](https://github.com/javier-abia/urbandocs/issues/33)** — the executor
  must express stem alternations in the sweep pattern and grouping by section.

## Open, deliberately

- **Whether a synonym map is ever needed** — deferred to after the gold set
  measures the system without one.
- **What a raw `search` hit line carries** — the *ranked* line is settled here
  (doc, page, heading chain; ~22 tokens/section). The hit line beneath it is
  still #7's to size.
- **Section geometry** — every figure above uses nearest-preceding-header
  attachment. Reproduce once `corpus.tsv` ships with real `parent_id`.
