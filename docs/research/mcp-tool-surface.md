# The four MCP tools: where `rank` runs and what each result carries

Resolves [#42](https://github.com/javier-abia/urbandocs/issues/42). Fixes the
signature, return shape and token cost of every operation the engine exposes,
under [#7](https://github.com/javier-abia/urbandocs/issues/7)'s remote MCP
server where the caller is someone else's agent.

The decision is one line: **`search` absorbs sweep and rank server-side, and raw
hits never cross the wire.** Everything below follows from that, from the
measurement that made it unarguable, and from a second corpus that broke the
first answer to what a result carries.

## Why `rank` moved to the server

[#32](https://github.com/javier-abia/urbandocs/issues/32) put `rank` in the
caller, which was sound while the caller was a component we wrote. Under a
client-neutral MCP it is Codex, Claude Code or opencode, and MCP cannot compel
a call sequence — so either the mandatory sweep and the term floor become
*instructions in a tool description*, or they become structural.

The expectation going in was a trade: pay tokens to buy the guarantee. The
measurement says there is no trade. Four realistic queries under
[#6](https://github.com/javier-abia/urbandocs/issues/6)'s term floor, against
the post-[#41](https://github.com/javier-abia/urbandocs/issues/41) corpus
(2,455 records, 496 sections):

| query                                  | raw hits | sections | bare-cite hits | **ranked list** |
| -------------------------------------- | -------- | -------- | -------------- | --------------- |
| `dimension` `rampa` `circulacion` `pendient` | 269 | 130 | ~2.4K | **~1.5K** |
| `altura` `libre` `trastero`            | 227      | 105      | ~2.0K          | **~1.2K**       |
| `anch` `libre` `paso` `puert`          | 353      | 121      | ~3.2K          | **~1.4K**       |
| `superficie` `util` `minim` `dormitorio` | 479    | 195      | ~4.3K          | **~2.4K**       |

**Rank is a compression, not a cost.** 227–479 hits collapse to 105–195
sections, so the ranked list is *cheaper than the raw hits it replaces* — by
1.7–1.8×, and that is against the cheapest conceivable raw line, a bare cite
with nothing attached. Shipping raw hits would pay more tokens, need a second
round-trip before anything is judgeable, and leave the guarantee as a sentence
a caller is free to ignore. One shape loses on both axes.

Ranked lines run **12 tok/section**, under
[#9](https://github.com/javier-abia/urbandocs/issues/9)'s 2.8–4.3K projection
because the corpus shrank with the DOG swap.

**This closes the *"what a raw `search` hit line carries"* fog as moot** rather
than answering it. Bare cite, cite plus matched line, cite plus a window — the
question only had force while raw hits crossed the wire, and they no longer do.
For the record, the middle option was measured at 14–30K tokens and was never
viable.

**No client re-scoring** (owner, 2026-08-05). "Distinct terms matched, grouped
by `parent_id`" is the only scoring the surface offers; there is no mode flag
and no fifth literal-occurrence tool.

## The four tools

### 1. `search(terms: list[str])`

The loop's mandatory first phase. Each term is one slot, matched as a regex
against `norm`; sections score by distinct slots matched.

Returns the **whole ranked section list, untruncated** — one line per section:

```
score  doc  page  <full heading ancestor chain>  section_id  [matched child ids]
```

- **Whole list, never truncated** — [#9](https://github.com/javier-abia/urbandocs/issues/9)'s
  guarantee, and the cutoff stays a judgment over heading chains.
- **No matched terms on the line** (owner, 2026-08-05). The score is the sort
  key, the chain is the judgment surface, nothing else. Adding which terms
  matched was costed at +6–8 tok/section and declined.
- **No legal text.** `search` returns addresses; the architect never verifies
  against a search line.

The **term floor stays instructed**, not structural. Stemming and synonyms are
the agent's by [#9](https://github.com/javier-abia/urbandocs/issues/9) — search
`anch`, not `ancho`/`anchura` (6/101 and 75/0 across the pair) — so a
server-side splitter handed *"anchura libre de paso"* would sweep `anchura` and
miss DccSUA's 101 `ancho`. A caller passing one lazy term gets a valid, cheaper,
worse answer the server cannot distinguish from a correct one. Accepted.

**A `question` argument was considered and rejected.** The idea was to carry the
natural-language question beside the terms so
[#30](https://github.com/javier-abia/urbandocs/issues/30)'s gold set could read
the pair out of Langsmith. It is redundant: under
[#7](https://github.com/javier-abia/urbandocs/issues/7)'s topology the MCP
server is connected to the architect's *agent*, LiteLLM sits between that agent
and the model, and a tool call travels inside the LLM request/response — so the
architect's question, the tool call and its result are already one trace, joined
by the conversation. Worth one look at a real trace once the gateway is up; if
MCP arguments turn out not to be legible there, the argument returns.

### 2. `get(ids: list[str])`

Batched, by decision. Per id it returns verbatim `text`, the full ancestor
chain, and direct children, labelled context-vs-match
([#4](https://github.com/javier-abia/urbandocs/issues/4)).

**Ancestors arrive as their own record text only.** Traced on
`SUA:p74:B.1.1.1`, the chain is three heading lines — `B.1.1 Diseño de la
instalación…`, `B.1 Sistema externo`, `Anejo B Características…`, ~30 tokens —
and `B.1.1`'s other child `B.1.1.2` does **not** arrive. Walking to the root
does not drag the tree with it. Siblings enter only one level down, as direct
children of the ranked section.

Batched rather than one-per-call because ten records is otherwise ten MCP
round-trips, each a full LLM turn re-sending the growing context and re-reading
the ranked list. The adaptivity that buys is already granted:
[#6](https://github.com/javier-abia/urbandocs/issues/6) fixed **N=1 refine
round** and measured one round as sufficient.

**Always returns, never refuses** (owner, 2026-08-05). An oversized batch is
disclosed, not truncated and not rejected — consistent with the map's standing
line that nothing may silently return less than it was asked for.

### 3. `get_by_cite(cite: str, doc: str | None)`

**A resolver, never a getter.** Returns addresses only — `id`, `doc`, `page`,
heading chain — and the agent calls `get` with what it picked.

The corpus forces this. Measured over 2,455 records:

| scoping             | keys | ambiguous | worst          |
| ------------------- | ---- | --------- | -------------- |
| cite alone          | 161  | **55%**   | `1` → 93 recs  |
| doc + cite          | 190  | **55%**   | `1` → 92 recs  |
| doc + page + cite   | 614  | 14%       | 6              |

**Adding `doc` buys nothing** — 55% to 55% — because the collisions are *inside*
one document. It is not confined to bare markers either: cites with two or more
dots are still **58% ambiguous** (`A.4.2.1` → 5 records), and **70% of records
carry no cite at all**. This is [#18](https://github.com/javier-abia/urbandocs/issues/18)
biting as predicted — *a provision id locates but does not uniquely identify* —
and [#4](https://github.com/javier-abia/urbandocs/issues/4) already accepted it:
the ambiguity is the source's.

Returning records would cost **~19K tokens** on `get_by_cite("1")` and the bad
cites are the *common* ones, since "el apartado 1" is what pointers produce.
As addresses the same call costs **~1.1K**. Beyond cost, a tool named
`get_by_cite` that returns *a record* promises a uniqueness the corpus does not
have.

`doc` survives as an optional **filter**, not a disambiguator — useful because
[#9](https://github.com/javier-abia/urbandocs/issues/9) established that
`expand` follows deferences across documents (DccSUA *is* DB SUA), so scoping is
sometimes right and sometimes exactly wrong.

### 4. `get_page(doc: str, page: int)`

Off-loop ([#8](https://github.com/javier-abia/urbandocs/issues/8)), single page,
every record on it in `prov.bbox` order, with `id`s so anything spotted is
gettable.

**No range parameter.** 32% of PGOM's articles span more than one page and
`Art. 37` spans **pp. 43–79** — a range call there returns **~70K tokens**, a
cost invisible at the call site and unbounded in the corpus that is coming. A
long article is walked one page at a time, ~1.9K a step, with the option to stop.

## What PGOM broke

The ranked line was first specified to address **sections only** — the agent
`get`s a section and reads it whole. On the current corpus that is cheap and
defensible. The owner asked for it to be checked against
`documentos/PGOM.pdf` (Vigo's plan, 350 pp., native text, 2.6M chars ≈ 5× the
whole current corpus) because it is a document the engine will have to carry.

It does not survive:

| `get(section)` | current corpus | **PGOM** |
| -------------- | -------------- | -------- |
| median         | 204 tok        | **84**   |
| p90            | 514            | **1,294** |
| p99            | 2,885          | **7,482** |
| max            | 3,643          | **24,611** |
| 10-section batch, p90 | ~5.1K   | **~12.9K** |

PGOM's median section is *cheaper* than the current corpus and its tail is **7×
worse**. `Art. 37 Planes Especiales de Protección` is **24,611 tokens with 298
direct children** — a flat catalogue of protected sites, so nesting cannot
exploit it (measured both ways: 24,793 flat, 24,611 nested). One such `get`
costs more than ten median sections and the entire ranked list combined, and
"protection plans" is an ordinary query, not a pathological one.

**Therefore the ranked line carries the section plus the ids of the children
that matched.** The agent can pull `Art. 37`'s three matching points instead of
all 298. Cost: roughly +4–6 tok/section, taking the worst current query from
2.4K to ~3.1K.

Two caveats on the figures. PGOM has no docling conversion yet, so it was
sectioned from `pdftotext -layout` by `Art. N.` with `1.`/`a)`/`A.` nested
beneath; real ingest will differ at the margins. And its per-page watermark was
stripped by shape for the measurement — if it is not stripped at ingest, every
figure above grows.

## Where the fidelity disclosure renders

[#27](https://github.com/javier-abia/urbandocs/issues/27) said "where the
citation renders". This surface splits that: **addresses** render in three
places (`search` lines, `get_by_cite`, `get_page`) while **verbatim text**
renders in only two (`get`, `get_page`).

Disclosure follows the **text**, not the address:

- **Per-record**, on `get` / `get_page`, where a record falls in an OCR'd range —
  derived at render time from `doc` + `page` + `label` against
  `corpus.provenance.tsv`, never stored.
- **Per-response blanket caveat**, once, when any returned record falls in such
  a range — with **no page list**, per #27: enumerating measured pages would
  imply the rest are clean.

Not on `search` lines. They are addresses the agent sorts, paid 105–195 times,
read at the moment it has no legal text to be wrong about. The record that
carries the citation is the one an architect verifies against the PDF, and that
is where the trust vector belongs.

**Known seam**: an agent that reads only the ranked list and never calls `get`
sees no disclosure. Judged correct rather than a gap — it also holds no text to
cite — and disclosed here rather than designed against.

**Today it renders on zero records.** After
[#41](https://github.com/javier-abia/urbandocs/issues/41),
`corpus.provenance.tsv` is all-`native` across all three documents, and PGOM is
native too. That the warning has a home before it has a subject is the point of
deriving rather than storing.

## Two defects this measurement surfaced

Neither belongs to the tool layer; both are recorded so they are not
rediscovered.

- **The `doc` field disagrees with itself.** `corpus.tsv`'s `doc` column holds
  the source filename `dog-habitabilidad`, while `DOC_CODES` in
  `scripts/ingest.py` gives ids the prefix `D128`. A citation therefore reads
  *"dog-habitabilidad p.43, `D128:p43:§6`"*, against
  [#41](https://github.com/javier-abia/urbandocs/issues/41)'s stated doc key of
  `D128`. Cosmetic, but it lands in every citation an architect reads.
- **PGOM carries a per-page watermark** — *"Versión traducida al castellano"*,
  *"del PXOM AD 26/05/2025"*, *"Data sinatura… CSV… Verificable en www.vigo.org/csv"*
  — bleeding into the text layer on every page. Same shape as
  [#41](https://github.com/javier-abia/urbandocs/issues/41)'s DOG_2025 masthead,
  and it must be stripped by shape at ingest.

## What is unchanged

The substrate (`corpus.tsv`), the loop order `sweep → rank → get → expand`, N=1,
evidence-only output with no synthesis and no completeness verdict, the citation
guarantee, `text`/`norm` symmetry, and the executor
([#33](https://github.com/javier-abia/urbandocs/issues/33), Python stdlib
in-process). This ticket specified the wire, not the engine behind it.
