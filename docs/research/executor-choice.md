# The executor: what actually runs `search`, `get`, `get_by_cite`, `get_page`

Resolves [#33](https://github.com/javier-abia/urbandocs/issues/33).
[#32](https://github.com/javier-abia/urbandocs/issues/32) settled the substrate
as one flat `corpus.tsv` and wrote every operation as column-scoped `awk` — but
wrote it as the default, not as a choice. This measures the choice.

**Answer: Python, stdlib only, called in-process — not a shell tool the
operations shell out to.** `awk` loses on a property that has nothing to do with
speed: **there is no spelling of "word boundary" that works across awk
dialects**, and both wrong spellings fail by returning zero rows. `#28` already
named that the engine's worst failure mode.

The substrate is untouched. `corpus.tsv` stays a plain, unquoted, greppable TSV,
and `awk`/`grep`/`cut` stay the right tools for reading it *by hand*. What
changes is only what the four operations execute.

## Speed is not the discriminator

Confirming what [#32](https://github.com/javier-abia/urbandocs/issues/32)
expected. Measured on `corpus.tsv` (4,924 records, 1.3 MB, 3 documents) and on a
simulated 20-document corpus (32,800 records, 9.0 MB), 20 reps after warming the
page cache. Note the flattening: 20 documents is **9 MB of TSV against the
~46 MB of docling JSON** the ticket projected.

Sweep only, stem `rampa` over `norm`, corpus-wide:

| executor | 3 docs | 20 docs |
| --- | --- | --- |
| `grep -P` | 3.7 ms | 3.5 ms |
| `rg` | 9.2 ms | 17.5 ms |
| `python3` | 32.5 ms | 73.2 ms |
| `gawk` | 40.2 ms | 203.9 ms |

All four return **the same 73 rows** at 3 docs and the same 506 at 20. `gawk` is
the slowest of the four and the one #32 wrote.

But sweep alone is not an operation. **Sweep + rank end-to-end in one Python
process**, 4-term query (`anch libre paso puert`), including interpreter
startup:

| corpus | sections ranked | wall time |
| --- | --- | --- |
| 3 docs | 158 | **85 ms** |
| 20 docs | 1,083 | **420 ms** |

Against 10–30 s of model latency per query that is **0.4%–4%**. For comparison
the `gawk` 4-term alternation is 47 ms at 3 docs — and then still needs a
ranker. The whole contest is worth ~40 ms of a 20-second query, so every
argument below is about correctness, not cost.

## The word boundary has no portable spelling in awk

This is the decision.

`search` is stemming ([#9](https://github.com/javier-abia/urbandocs/issues/9):
search `anch`, not `ancho`/`anchura`), so every sweep is *word-boundary plus
literal prefix*. In awk that boundary cannot be written portably:

| dialect | pattern | rows | how it fails |
| --- | --- | --- | --- |
| gawk | `/\yrampa/` | **73** | correct |
| gawk | `/\brampa/` | **0** | `\b` is *backspace*; no warning, exit 0 |
| POSIX awk (`--posix`) | `/\yrampa/` | **0** | `\y` unknown; warning on stderr, **exit 0** |
| BWK awk (`--traditional`) | `/\yrampa/` | **0** | same |

`\b` silently returning zero is [#28](https://github.com/javier-abia/urbandocs/issues/28)'s
finding, reproduced. What is new is the other side: **`\y` is a GNU extension**,
so the correct-on-gawk spelling is the silently-empty spelling on POSIX awk, on
macOS's BWK awk, and on Debian/Ubuntu, where `/usr/bin/awk` is mawk rather than
gawk. Neither `--lint` nor `--posix` warns about `\b`; the `\y` warning goes to
stderr and leaves exit status 0, so a caller that shells out sees success and an
empty result set.

There is no third spelling. Choosing awk therefore means *requiring GNU awk
specifically* — which retires awk's main claim, that it is already on every
machine. Python's `re` needs `\b`, one spelling, no dialect flag, everywhere.

## Escaping: the term is agent-generated, and no shell tool escapes it for you

Because the term is a stem it is always a literal, and always has to be escaped
into the boundary regex. Probing terms an agent could plausibly emit:

| term | gawk `/\y…/` | rg | `re.escape` |
| --- | --- | --- | --- |
| `rampa` | 73 | 73 | 73 |
| `*altura` | **179** | **179** | 0 |
| `a\b` | **0** | **1076** | 0 |
| `Ley 5/2010` | **syntax error** | 0 | 0 |
| `anexo [II` | error | error | 0 |
| `apartado (a` | error | error | 0 |

Read the middle rows. `*altura` returns 179 hits under both shell tools — the
`*` quantifies the boundary and the term silently degrades to `altura`. `a\b`
returns **0 under gawk and 1,076 under rg**: three executors, three different
answers, none of them an error. Only the unbalanced-delimiter terms fail loudly.

`Ley 5/2010` deserves its own line. The `/` closes awk's `/…/` regex literal, so
the form #32 wrote is a **syntax error** on a whole class of real Spanish legal
cites — and this corpus is built on one (the CTE is Real Decreto 314/2006).
Passing the term via `-v t` and building a dynamic regex survives the slash but
fixes neither the metacharacter problem nor the boundary problem.

`re.escape` is correct on every row above, by construction rather than by
vigilance.

## Column scoping: `$8` is legible, `{7}` is a trap

`awk` addresses the column directly (`$8`). `rg` and `grep` cannot, so the
column becomes a counting prefix:

```
gawk -F'\t' '$8 ~ /\yrampa/'                    # norm
rg   -N  '^(?:[^\t]*\t){7}[^\t]*\brampa'        # norm
```

They also count differently — awk counts **fields** (8), rg counts **delimiters
crossed** (7) — so translating between them is a permanent off-by-one. And the
off-by-one is silent: `{6}` scopes column 7, `text` instead of `norm`, and
returns **70 rows instead of 73**. Plausible, wrong, no error.

That is not a rounding error. `norm` differs from `text` in **3,539 of 4,924
records**, and searching the wrong column costs recall on every stem:

| stem | `text` | `norm` | lost |
| --- | --- | --- | --- |
| `anch` | 148 | 175 | 15% |
| `altura` | 150 | 179 | 16% |
| `superfic` | 181 | 192 | 6% |
| `ventil` | 95 | 100 | 5% |

These are exactly the "misses in the concept" the owner's steer on
[#32](https://github.com/javier-abia/urbandocs/issues/32) rules out. `rg` is the
fastest correct shell option and the easiest one to get silently wrong.

## The substrate is tab-delimited, not CSV — and two candidates forgot

`scripts/ingest.py:528` states the contract: *"Plain TSV — no quoting, no
escaping, so `awk -F'\t'` and `cut` just work."* 39 records legitimately contain
a `"`. Any reader that guesses CSV quoting corrupts the file:

- `sqlite3 .import` in `.mode tabs`: **4,923 rows of 4,924**, with
  `corpus/corpus.tsv:4322: unescaped " character` on stderr. Loud, but a record
  is gone.
- Python `csv.reader` at the default dialect: **silently** merges two fields on
  that same row (7 columns instead of 8). `QUOTE_NONE` fixes it.
- `gawk`, `rg`, `grep`, and `str.split('\t')`: all 4,924 rows, 8 columns.

The right reader splits on the literal delimiter and does nothing else. Python
does that natively; the hazard is only in reaching for `csv`.

## The rejected candidates

**`jq` / `jaq` — out by construction.** The substrate is a TSV, so there is no
JSON to query. The premise holds anyway: `jq` over the 5.2 MB of tuned docling
JSON costs **145 ms per invocation just to parse**, ~1 s at 20 documents, and
yields the nested structure that ingest exists to flatten away — not the flat
addressable provisions [#4](https://github.com/javier-abia/urbandocs/issues/4)
and #32 designed. `jaq` would lower the constant and change nothing else. Not
installed here; not worth installing.

**SQLite — out, and already fog.** It needs an import step that drops a record
(above); its `REGEXP` operator is an extension, present in this 3.53 CLI but not
guaranteed by any build, and `LIKE` cannot express a word boundary (`LIKE
'%anch%'` returns 176 against the correct 175, so stemming degrades to
substring); and it buys ~10 ms against an 85 ms budget while reintroducing the
binary, ungreppable artifact
[#4](https://github.com/javier-abia/urbandocs/issues/4) rejected. #32 already
placed SQLite + FTS5 past ~200 documents **as a reranker over hits, never a
pre-filter** — that placement stands and this ticket does not disturb it.

**`mlr` — out.** Not installed, not present by default anywhere in this stack,
and it is a CSV/TSV query language, which is the thing
[#12](https://github.com/javier-abia/urbandocs/issues/12)'s steer weighs
against.

**`grep -P` — fastest, least expressive.** 3.5 ms and correct, but it inherits
`rg`'s counting-prefix column problem and offers nothing to build `rank` with.

## Legibility: the steer is satisfied better by Python than by awk

[#12](https://github.com/javier-abia/urbandocs/issues/12)'s steer, restated by
#32: an engine whose recall depends on a tool an architect can read and re-run
by hand is easier to defend than one that depends on a query language. Two
things follow, and they point the same way.

**Python is not a query language.** The steer's real target was opacity —
embeddings, a scoring function nobody can re-derive. A 120-line script that
reads a text file and prints matching lines is not that.

**The emitted command is more re-runnable, not less.** Compare what the engine
would hand an architect who wants to check a result:

```
gawk -F'\t' '$8 ~ /\yanch/ {print $1"\t"$2"\t"$3"\t"$5}' corpus/corpus.tsv
python3 scripts/search.py anch libre paso puert
```

The first needs the reader to know that `$8` is `norm`, that `\y` is a boundary,
that `\b` would silently return nothing, and that pasting it on a Mac returns
nothing. The second is the query. **The engine should print its own invocation
alongside its results** — that is the scored property, and it is cheaper to
honour with a named script than with a one-liner.

Crucially the *substrate's* legibility is untouched. `corpus.tsv` remains a
plain TSV, and an architect checking a citation by hand still runs
`grep rampa corpus/corpus.tsv`. The steer's force lands on the file, and the
file does not change.

## The clinching argument: `rank` was never a one-liner

[#32](https://github.com/javier-abia/urbandocs/issues/32)'s `rank` phase groups
hits by `parent_id` and scores each section by **distinct query terms matched** —
and it already exists, as `scripts/prototype_sweep_rank.py`, 120 lines of Python
that also does normalization, cite parsing and ancestor-chain assembly.
`scripts/ingest.py` is Python. `scripts/section_geometry.py` is Python.

Choosing awk for `sweep` therefore does not remove Python from the engine. It
adds a second language, a subprocess, and a serialization boundary in the middle
of a four-phase loop — to save ~40 ms of a 20-second query, at the cost of every
failure mode above.

## What this constrains

- **[#7](https://github.com/javier-abia/urbandocs/issues/7) (form factor)** —
  the operations **shell out to nothing**. "Shells out to `awk`" leaves #7's
  option space; the four operations are Python functions over `corpus.tsv`, and
  skill / MCP server / library all become thin wrappers over the same in-process
  calls. Whatever #7 picks must surface the equivalent re-runnable invocation in
  its output.
- **Stdlib only.** `re`, `unicodedata`, `collections`, `pathlib` — no
  dependency, matching Stage 2's existing "needs nothing but python" property
  ([#28](https://github.com/javier-abia/urbandocs/issues/28)).
- **Never `csv.reader` on `corpus.tsv`.** Split on `\t`. A default-dialect
  `csv.reader` silently loses a field on the one record carrying an unescaped
  quote.
- **Escape every query term** with `re.escape` before anchoring it with `\b`.
  The term is a literal stem; treating it as a pattern is how `*altura` returns
  179 rows.
- The substrate decision, the loop order, and SQLite's placement past ~200
  documents are all unchanged.

## Reproducing

Rebuild the substrate first (`corpus/` is gitignored and derived):

```
uv run scripts/ingest.py
```

The tables above come from `gawk`/`rg`/`grep -P`/`python3` invocations given
inline, run against `corpus/corpus.tsv`. The 20-document figures use a corpus
synthesized by replicating the 3-document one 7× with distinct `doc` and `id`
prefixes — it measures scan cost against file size, which is what is at issue,
not real 20-document content.

## Open, deliberately

- **Whether `search` should return the matched line or only the cite** is
  [#7](https://github.com/javier-abia/urbandocs/issues/7)'s, still fog on the
  map. Nothing here depends on it: it changes what the operation prints, not
  what runs it.
- **The reranker at 100–200 documents** stays fog. This decision does not
  prejudge it — a Python sweep can hand hits to anything, including SQLite.
