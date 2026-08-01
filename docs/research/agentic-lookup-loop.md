# The agentic lookup loop: four fixed phases, one refine round, five tools

Design for [#6](https://github.com/javier-abia/urbandocs/issues/6) — the contract
that turns a question into evidence, deterministically, opening only what it
needs. The form factor that wraps this contract is
[#7](https://github.com/javier-abia/urbandocs/issues/7); the loop's shape is the
same whether the operations are `jq` in a shell or typed tool calls.

Sizing figures reproduce with:

```
python3 scripts/count_pointers.py --pointers
python3 scripts/count_pointers.py --breadth
```

## What a lookup returns

**Evidence, never an answer.** A lookup hands back records — text, ancestor
chain, direct children, `id`/`cite`/`page`, fidelity flags — plus a factual
account of what it searched. It never composes prose and never rules on
compliance.

The destination calls this engine a retrieval substrate that a future
expediente-review app calls. Keeping synthesis out of it is not tidiness: the
whole trust model rests on the architect verifying against the source
([#12](https://github.com/javier-abia/urbandocs/issues/12)'s steer), and a
paraphrase sitting next to a real citation is exactly how a threshold gets lost
between the page and the architect. The engine's job is to put the right page in
front of a human, not to read it for them.

For the same reason the envelope reports *what was searched and what returned
nothing*, as fact, and offers no completeness verdict. A loop that says "I
believe this is complete" invites the caller to stop checking, which is the one
behaviour the trust model cannot afford.

## The loop

Four phases, always in this order, none skippable. The agent's judgment lives
*inside* the phases — which entity, which terms, which sections — never in
whether a phase runs.

```
  question
     │
  ┌──▼─────────────────────────────────────────────────────────┐
  │ 1  ROUTE    read L1 (always in context) → pick documents    │
  │             load those L2s → pick sections                  │
  ├────────────────────────────────────────────────────────────┤
  │ 2  READ     get() the routed sections' records              │
  ├────────────────────────────────────────────────────────────┤
  │ 3  SWEEP    corpus-wide exact search, every content word    │
  │             of the query on its own. Always runs.           │
  ├────────────────────────────────────────────────────────────┤
  │ 4  EXPAND   every kept hit → ancestor chain + direct        │
  │             children; resolve in-corpus pointers, one hop   │
  └──┬─────────────────────────────────────────────────────────┘
     │
  evidence
```

**Why the phases are fixed.** Phase 3 is the safety net under
[#5](https://github.com/javier-abia/urbandocs/issues/5)'s measured 18% residual,
and that residual is structural rather than lexical: a binding rule about entity
A stated inside entity B's section, with A absent from B's digest. The garage
ramp width lives under *Dimensiones de las rampas de circulación*, whose digest
contains no `garaje`. Routing cannot reach it at any digest width, so the
corpus-wide pass is what recovers it — and a pass that an agent may skip once the
routed sections look convincing is not a safety net.

Phase 4's expansion is the read contract from
[#4](https://github.com/javier-abia/urbandocs/issues/4), restated here because
the loop is where it is enforced: a match arrives with its ancestors, because the
qualifier often lives in the parent (`art14.1.a`'s encimera applies only under
`art14.1`'s no-new-rooms condition), and with its children, because the
obligation often lives below (`art14.1` ends in `deberá cumplir:`).

**Phase 1 stays advisory.** Per #5's locked decision, routing chooses what to
read *first*, never what may be found. Phase 3 therefore runs corpus-wide even
when L1 selects a single document — narrowing the sweep to the routed set would
convert an advisory index into a binding one by the back door.

## Pointers, and the one refine round

### What a pointer is

A **pointer** is a phrase inside a provision's text that names another
addressable unit by the `cite` the page prints: `en la tabla 1.2`, `conforme al
apartado SUA1 - 4.3.1`, `lo regulado en el anexo II`, `véase figura 3.1`.

Two things that look like pointers and are not:

- **Relative mentions** — `el apartado anterior`, `la sección correspondiente`.
  They name by relation, carry no address, and cannot be resolved by lookup.
- **Self-titles** — `Artículo 9. Condiciones generales aplicables a la
  rehabilitación` is the article's own heading, not a reference to anything.

And one that is a pointer but never resolves: an **external** pointer, naming a
norm the corpus does not hold — `el artículo 129 de la Ley 39/2015`, `el anejo A
del DB SI`.

### How many there are

Body text only; heading labels excluded, so self-titles are not counted.

| document | body items | pointers | in-corpus | external | figure | items carrying ≥1 |
|---|---|---|---|---|---|---|
| DccSUA | 893 | 279 | 188 | 50 | 41 | 203 (22.7%) |
| HABITABILIDAD | 3393 | 273 | 170 | 12 | 91 | 227 (6.7%) |
| DOG_2025 | 229 | 47 | 33 | 14 | 0 | 33 (14.4%) |
| **total** | | **599** | **391** | **76** | **132** | |

Figure pointers are counted apart because they resolve to a page and a position,
never to a rule — figure *content* is out of scope per
[#3](https://github.com/javier-abia/urbandocs/issues/3).

Pointers are not a rare edge case: nearly a quarter of DccSUA's body items carry
one.

### Why exactly one hop

A depth probe on HABITABILIDAD's articulado: of 60 `artículo N` pointers, 53
resolve inside the document, and **45 of those 53 (85%) land on an article that
itself carries a further pointer.** Branching does not decay — round 2 costs
about what round 1 did, and round 3 again after that. There is no natural
stopping point above one, so the loop takes one and stops.

> The 85% was measured at whole-article granularity — "the target article
> contains a pointer somewhere" rather than "the provision actually attached
> does". It is an upper bound on branching. It is decisive against unbounded
> recursion and it does not, on its own, separate one hop from two.

**The rule.** Phase 4 resolves in-corpus pointers found in the evidence, attaches
each target as labelled context, and stops. Pointers found *inside those targets*
are reported as unresolved pointers, not followed. External and figure pointers
are never resolved — they are listed with what they name, so the architect knows
a reference exists and where it goes.

Ambiguous resolution is preserved, not hidden: a `cite` lookup may return several
records, and per #4 that ambiguity belongs to the source
([#18](https://github.com/javier-abia/urbandocs/issues/18): a provision id
locates but does not uniquely identify). All candidates attach.

## The tool surface

Five operations. What each returns is part of the contract; how it is invoked is
[#7](https://github.com/javier-abia/urbandocs/issues/7)'s.

| operation | returns | used by |
|---|---|---|
| `read_index()` | L1 — one line per document | phase 1 |
| `read_doc_index(DOC)` | L2 — one line per section | phase 1 |
| `search(terms, scope?)` | hits: `id`, `page`, `cite`, snippet | phases 2, 3 |
| `get(ids)` | records + ancestor chain + direct children | phases 2, 4 |
| `get_by_cite(cite, doc?)` | records, possibly several | phase 4 |

**`search` returns snippets, not records.** The agent picks which hits matter,
then calls `get`. Two round trips, and the reason is phase 3: its hit count is
unbounded by construction, since it searches bare content words across the whole
corpus. Measured worst case among realistic attributes:

| term | hits | share of body items |
|---|---|---|
| `superficie` | 173 | 3.4% |
| `altura` | 170 | 3.3% |
| `escalera` | 153 | 3.0% |
| `estancia` | 145 | 2.8% |
| `trastero` | 29 | 0.6% |

At ~30 tokens a snippet that is ~5K tokens for the broadest term — affordable.
Returning each of those 173 hits as a full contextual record, with ancestors and
children, would not be, and the pass that must never be skipped is precisely the
wrong place to put an unbounded cost.

**`get_page` was considered and cut.** Reading a whole page belongs to the
citation guarantee ([#8](https://github.com/javier-abia/urbandocs/issues/8)) —
landing an architect on the right page to verify — not to finding an answer.
Offering it here invites read-the-whole-page habits that the index exists to
prevent.

**Fidelity flags ride on records; the loop never filters on them.** #27 decides
which axes exist. Whatever they are, the loop surfaces them and suppresses
nothing — an untrusted HABITABILIDAD table cell
([#21](https://github.com/javier-abia/urbandocs/issues/21): operator recovery is
gated to prose, so pp.1–94 table cells are the untrusted surface) is returned
with its warning attached, because evidence-only means the caller decides what a
flag is worth.

## Phase 3's terms: a mandated floor

The sweep is only as good as what is fed into it, and choosing terms is the one
place agent judgment could quietly gut a mandatory phase. So the floor is fixed
and the ceiling is not:

- **Must search**: every content word of the query, **each on its own** — entity
  and attribute separately, never only as a phrase — plus number variants.
- **May add**: synonyms, related entities, corpus vocabulary the agent recognises.
- **May never search fewer.**

Searching the attribute alone is not redundant with routing; it is the specific
move that recovers #5's cross-entity residual. The garage ramp width is found by
sweeping `ancho`, in a section that routing on `garaje` never reaches.

Synonyms earn the "may add" clause on measurement rather than principle: an
architect says `garaje` (49 hits) and the corpus also says `aparcamiento` (65
hits). Both are live vocabulary; a floor made of the query's own words alone
would see one and miss the other.

## Query normalization

[#14](https://github.com/javier-abia/urbandocs/issues/14) settled the pipeline —
whitespace collapse (the dominant hostility, 879 of 1466 multi-space runs) → the
4-entry Symbol-font glyph map → hyphenation rejoin → subscript rejoin → unit
folding `m²`≡`m2`≡`m?`. What #6 settles is where it lives, which had to be
answered here because it must be **symmetric**: a normalized query against an
unnormalized corpus matches nothing.

**Ingest writes both forms.** Each record carries `text` (verbatim, exactly what
the page printed) and `norm` (normalized); `<DOC>.cells.tsv` likewise. `search`
matches `norm`. **`get` always returns `text`.**

That split is load-bearing for #8: normalization serves matching, and an
architect must read what the page actually says or the citation guarantee is
hollow. It also keeps #5's promise that the corpus-wide pass is a free `grep` —
the normalized form is on disk, so a shell `grep` and the `search` operation use
the same bytes rather than two implementations of the same rules.

Accepted costs: the substrate roughly doubles over 490K characters of text, and
changing a normalization rule means re-running ingest (Stage 2, seconds — the
expensive Stage 1 artifacts stay committed per #4).

HABITABILIDAD's `0`≡`o` and `Y`≡`y` stay **query-side**, per #14 — they are OCR
damage specific to one document, so they expand into query variants rather than
rewriting the stored corpus. A stored `norm` that "fixed" them would be an ingest
rewrite of what the page says, which is the thing #14 ruled out.

## What this hands downstream

- **[#7](https://github.com/javier-abia/urbandocs/issues/7)** — five operations
  with fixed return shapes to wrap. The form factor question is now narrow: what
  invokes them, not what they are.
- **[#8](https://github.com/javier-abia/urbandocs/issues/8)** — `get` returns
  verbatim `text` with `id`/`cite`/`page`, so a citation reads straight off the
  record. `get_page` was deliberately left to #8 to specify.
- **[#9](https://github.com/javier-abia/urbandocs/issues/9)** — phase 3 already
  sweeps corpus-wide and phase 4 already resolves pointers across documents, so
  contradiction detection inherits a loop that sees more than one document per
  query rather than needing its own retrieval path.
- **[#27](https://github.com/javier-abia/urbandocs/issues/27)** — flags ride on
  records and are never filtered on; #27 decides which axes exist.
- **[#28](https://github.com/javier-abia/urbandocs/issues/28)** — ingest must
  emit `norm` alongside `text`, on records and on `cells.tsv`.
- **[#30](https://github.com/javier-abia/urbandocs/issues/30)** — the gold set is
  what can settle the two numbers this design left as bounds: whether N=1 is
  enough, and whether the mandated floor's synonym clause carries its weight.

## Open, deliberately

- **N=1 is a floor set against an upper-bound branching figure.** A
  provision-granularity re-probe would sharpen it. It will not change the verdict
  against unbounded recursion; it could change 1 to 2.
- **Snippet width** is unspecified — ~30 tokens is the sizing assumption, not a
  decision. It belongs with #7, where the transport is known.
- **How the agent picks entities from a natural-language question** is left to
  the agent. The floor guarantees the query's own words are swept regardless, so
  a bad entity choice costs routing quality, never coverage.
