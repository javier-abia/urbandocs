# The navigable index: a two-level, derived, advisory index

Prototype and design for [#5](https://github.com/javier-abia/urbandocs/issues/5) — the
cheap artifact the agent reads before it opens any document.

Built by `scripts/build_navigable_index.py` against the tuned docling JSON in
`documentos/documentos-docling/docling-tuned/`. Reproduce with:

```
python3 scripts/build_navigable_index.py
python3 scripts/build_navigable_index.py --query "altura libre"
```

## The shape

Two levels, both derived from body text, never authored.

**L1 — `index/corpus.index`.** One line per document, always in the agent's
context. ~60 tokens per document; **~187 tokens for the present three**,
~3K at 50 documents.

```
DccSUA | 79pp 291sec | accesible edificio riesgo accesibles altura edificios anchura
                       puertas seguridad personas mínimo puerta escalera tabla rampa
HABITABILIDAD | 101pp 183sec | acceso ancho estancia altura mínima gráfico ventilación
                       iluminación planta pieza determinaciones estancias cocina
DOG_2025 | 25pp 19sec | ambiental revisión estratégica evaluación órgano galicia
                       sostenibilidad territorio ayuntamiento patrimonio rústico paisaje
```

**L2 — `index/<DOC>.index`.** One line per section, loaded only for the
documents L1 selected. DccSUA 9.6K, HABITABILIDAD 5.6K, DOG_2025 0.6K.

```
HABITABILIDAD:p34-41 | A.1.2 Iluminación, ventilación natural y relación con el ext…
                     | iluminación superficie gráfico pieza ventana ventilación mínima huecos
DccSUA:p31 | 1.1 Impacto con elementos fijos
           | altura impacto zonas libre circulación riesgo elementos escalera
```

Because the agent holds L1 always and pulls at most one or two L2s, **peak index
cost stays around 15K tokens regardless of how large the corpus grows** — the
scaling property a single flat index does not have.

## Why the terms are derived from the body, not the headings

The obvious index is the table of contents. It does not work, and the reason is
measurable rather than aesthetic: **query vocabulary lives in body text, not in
heading titles.**

Across all 504 deduplicated headings in the corpus, `altura libre` — the single
most common shape of question a permit review asks — appears **zero** times.
`cocina` appears twice. The provision that actually answers it sits in DccSUA
under `1.1 Impacto con elementos fijos`, a title no one would route a height
question to.

A body-derived digest fixes exactly that case, and it also correctly *repels*
false attractors:

| section | digest | routes `altura libre`? |
|---|---|---|
| `DccSUA 1.1 Impacto con elementos fijos` | altura impacto zonas **libre** circulación riesgo | yes — correctly |
| `HAB A.4.2 EQUIPAMIENTO DE LOS SERVICIOS` | patio vivienda revestimiento impermeable desagüe | no — correctly |

The digest is TF-IDF over the section's own body against every other section, so
it surfaces what makes a section *different*, not what makes it legal text. L1
additionally drops every term present in all three documents: those describe the
corpus, not the document, so they cannot discriminate between documents.

## Why a keyword index was rejected

A full inverted term index over the corpus is **5,194 terms, ~47K tokens** — and
it is strictly a slower `grep`. The whole corpus is 490K characters; an exact
search over it is deterministic, costs no tokens until it hits, and needs no
build step. Loading 47K tokens to approximate something free is a bad trade. The
index earns its place by carrying *structure and topicality*, which grep cannot
produce, not by carrying term locations, which grep produces for nothing.

## The routing is advisory, not binding

**Locked decision (owner, 2026-08-01): the index decides what to read first, never
what is allowed to be found.** A lookup is:

1. read L1 (always in context) → pick documents
2. load those documents' L2 → pick sections
3. read those sections — this is where the answer comes from
4. run one corpus-wide exact search on the query terms, and surface every hit
   that fell outside the routed set

### How well does routing actually work

Measuring this correctly turns on **what part of a query is the routing key**.
A permit question is not *"altura libre"* — it is *"altura libre **de los
trasteros**"*. The entity is what localizes; the attribute is corpus-wide by
construction, since every section of a dimensional norm talks about heights and
widths. **Routing on the attribute measures nothing**: an early version of this
prototype did exactly that, found `altura libre` reaching 3 of 30 hits, and
concluded routing barely worked. It was measuring the wrong half of the query.

Routed on the entity and verified on the attribute — eight realistic
entity+attribute pairs, ground truth being every body item containing both:

| query | sections routed | true provisions | found | recall |
|---|---|---|---|---|
| trastero + altura | 3 | 3 | 3 | 100% |
| rampa + pendiente | 8 | 8 | 8 | 100% |
| escalera + ancho | 15 | 19 | 17 | 89% |
| estancia + superficie | 7 | 24 | 19 | 79% |
| garaje + ancho | 8 | 4 | 3 | 75% |
| cocina + superficie | 4 | 7 | 5 | 71% |
| ascensor + dimensión | 15 | 6 | 3 | 50% |
| **total** | | **71** | **58** | **82%** |

**Routing works — 82% recall on an 8-term digest.** That is the number the design
rests on.

### Why the remaining 18% still needs a safety net

Reading all 13 misses by hand — a judgement call, not a measurement — they split
in two. About seven are **incidental mentions**: the entity appears but the
section does not govern it (`C.8 Patio interior` naming estancias inside a
definition). Nothing is lost by not routing there.

The other six are **genuine cross-entity provisions** — a binding rule about
entity A stated inside entity B's section, where A is absent from the digest:

```
[garaje] "Dimensiones de las rampas de circulación para vehículos"
    digest: rampas radio rampa circulación tramos gráfico diferenciada rectos
    → "El ancho libre mínimo de las rampas de circulación será de 3 m. Cuando
       el garaje albergue más de 100 vehículos deberán existir dos…"

[escalera] "B.2.1.2. Ámbito interior"
    digest: cuadrado ascensor puntuales hueco planta resulte gráfico elementos
    → "las áreas de acceso a ascensores y escaleras tendrán un ancho mínimo
       entre paramentos de 1,50 m"
```

These are binding dimensions that a competent routing pass will not find, because
the section is *about* something else. They are also precisely the shape that
cross-document contradiction detection
([#9](https://github.com/javier-abia/urbandocs/issues/9)) exists to catch: a rule
in an unexpectedly-named section is not noise, it is the finding.

Widening the digest is not the fix. Measured on attribute-routing, going from 8
to 30 terms doubles the index and still leaves misses:

| terms per section | L2 total |
|---|---|
| 8 | 15.7K |
| 16 | 23.3K |
| 30 | 32.9K |

Two things follow. First, **routing recall is a tunable function of digest width
that never reaches 1**, so a binding index would silently drop provisions at any
size. Second, because verification decouples recall from index width, the index
can stay at the cheap end — **8 terms per section** — and let the corpus-wide
pass catch the tail. Doubling the index to chase the last few percent buys less
than a single `grep` does for free.

Both figures are simulations of routing as literal matching against the digest,
so both understate a real agent, which reads the digest rather than matching it.
The 82% is therefore a floor. What the residual is made of — cross-entity
provisions, not random noise — is the durable finding, and it is what makes the
verification pass load-bearing rather than defensive.

This matters most for cross-document contradiction detection
([#9](https://github.com/javier-abia/urbandocs/issues/9)), where a rule in an
unexpectedly-named section is not noise but *the finding*.

## Constraints honoured

- **`SectionHeaderItem.level` is discarded** ([#14](https://github.com/javier-abia/urbandocs/issues/14):
  the emitted tree is inverted). Section boundaries come from the document order
  of heading items; the index is a flat sequence, and hierarchy is rebuilt
  downstream from heading text.
- **The `.md` files are never read** ([#18](https://github.com/javier-abia/urbandocs/issues/18):
  the serializer fabricates list markers and reorders `body`). Input is the JSON.
- **`content_layer == "furniture"` is the furniture filter**
  ([#14](https://github.com/javier-abia/urbandocs/issues/14): it eats no body
  text). Without it, DOG_2025's L1 digest fills with `https`, `lunes`, `junio`
  and a document-deposit code. One residue survives: DOG_2025's official `Pág.`
  markers are labelled `text`, not furniture, so `lunes` still ranks — cosmetic
  here, but a reminder that the filter is necessary and not sufficient.
- **HABITABILIDAD's contents pages are not used as a spine**
  ([#17](https://github.com/javier-abia/urbandocs/issues/17): 20 of 83 index
  entries lost their titles). The digest is built from body text, so this defect
  cannot reach the index. Headings with no body under them — contents-page echoes
  — are dropped outright, which is why the section counts here (291/183/19) are
  below the raw heading counts (369/223/21).

## Open, deliberately

- **Where the index is written** is left to the ingest pipeline
  ([#28](https://github.com/javier-abia/urbandocs/issues/28)); this prototype
  writes `index/` at the repo root, which is a prototype convenience, not a
  decision.
- **Query normalization** — whitespace collapse, the Symbol glyph map, unit
  folding, HABITABILIDAD's `0`≡`o` — applies to both the digest and the query
  side, and is still fog on the map pending
  [#6](https://github.com/javier-abia/urbandocs/issues/6).
- **Two-level is a ceiling, not a limit.** If the corpus outgrows a ~3K L1, the
  same construction nests again (theme → document → section). The map tracks
  this as *Partitioning / scale-out*.
