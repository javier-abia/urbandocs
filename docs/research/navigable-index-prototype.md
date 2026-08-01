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

Step 4 is the safety net, and it is not theoretical. Simulating routing as
literal matching against the digest, `altura libre` routes to 3 sections but the
corpus holds 30 hits — **21 outside the routed set**, including
`B.2.3 Espacios de comunicación`'s *"la altura libre mínima de estos espacios
será de 2,40 m"*, a binding dimension for the exact question asked.

Widening the digest reduces the gap but never closes it:

| terms per section | hits missed by routing (of 30) | L2 total |
|---|---|---|
| 8 | 21 | 15.7K |
| 16 | 10 | 23.3K |
| 30 | 4 | 32.9K |

Two things follow. First, **routing recall is a tunable function of digest width
that never reaches 1**, so a binding index would silently drop provisions at any
size. Second, because verification decouples recall from index width, the index
can stay at the cheap end — **8 terms per section** — and let the corpus-wide
pass catch the tail. Paying 33K tokens to still miss 4 hits is worse than paying
15.7K and missing none.

The 21/30 figure is an upper bound on the real miss rate: an agent reading
`A.3.1.1. Piezas situadas en plantas piso | altura libre pavimento techo` would
route there, where literal matching does not. The curve's shape is what matters,
not its exact height — and the shape says the safety net is load-bearing.

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
