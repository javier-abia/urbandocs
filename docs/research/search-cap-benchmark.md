# Would capping `search`'s result count pay for itself?

Benchmark for [#90](https://github.com/javier-abia/urbandocs/issues/90),
which asks whether [#56](https://github.com/javier-abia/urbandocs/issues/56)'s
never-truncate stance on `search` is worth revisiting, and asks for numbers
before any implementation.

## Method

Ran the real agent + MCP loop (`evals/`, `EVAL_MODEL`/`EVAL_JUDGE_MODEL` as
configured) against both halves of the gold set (`docs/eval-questions.csv`),
in two separate passes — easy first, to bound cost before spending on the
heavier complex half. Each question's full message history
(`RunResult.all_messages()`) was captured locally — LangSmith's own trace for
this harness holds only per-question aggregates (token totals, tool-call
*count*), never the individual `search`/`get` payloads, so the aggregate
history alone can't answer what #90 asks.

For each question: every section `search` returned (ranked by score, as the
agent saw it), and the section ids the agent actually passed to `get`
afterwards — the "used" set. A `get`-ed id is credited to whichever rank (or
score) its owning section, or the section that lists it as a
`matched_child`, held in the search response.

Caveat, still standing even with both halves run: both runs are single-pass
conversations, each question answered once. #86's replay-compounding case (a
`search` result re-sent to the model on every subsequent round) needs a
multi-round transcript to observe directly — this data bounds the per-call
result size and the rank/score of what got used, not the compounding itself.
The complex run's own token totals (up to 655,373 input tokens for one
question) are consistent with heavy replay happening, but this benchmark
didn't isolate it.

## What one `search` call returns, today

| Q | sections returned | `get`-ed ids | full payload (~tok) |
|---|---|---|---|
| 1 | 1045 | 11 | 40,648 |
| 2 | 694 (2 calls) | 11 | 24,812 |
| 3 | 861 | 6 | 32,358 |
| 4 | 905 | 3 | 34,697 |
| 5 | 988 | 7 | 38,122 |
| 6 | 679 | 5 | 25,150 |
| 7 | 877 | 8 | 32,808 |
| 8 | 467 | 4 | 17,093 |
| 9 | 910 | 4 | 34,547 |
| 10 | 322 | 13 | 11,339 |

Every one of the ten **easy** questions swept 300–1000+ sections from a single
sweep — not the outlier #90 opens with (the 300-section Q8 case), the norm.
Token estimate is `len(json)/4` over the section list only (excludes the
shared ancestor-string table #99 interns, so this slightly overstates the
per-call cost — the real number is smaller, the shape of the result doesn't
change).

## Would a cap have hidden a section the agent actually used?

Rank of each `get`-ed section within its `search` call, capped at 20 / 50 /
100:

| Q | ranks of used sections | cut @20 | cut @50 | cut @100 |
|---|---|---|---|---|
| 1 | 13,13,13,13,32,41,93,93,99,125,304 | 7 | 5 | 2 |
| 2 | 1,2,3,8,9,10,13,211,212,213,214 | 8 | 4 | 4 |
| 3 | 2,2,2,2,5,28 | 1 | 0 | 0 |
| 4 | 2,3,65 | 1 | 1 | 0 |
| 5 | 9,10,18,18,18,212,213 | 2 | 2 | 2 |
| 6 | 1,1,1,1,1 | 0 | 0 | 0 |
| 7 | 3,7,98,99,100,101,101,102 | 6 | 6 | 3 |
| 8 | 2,11,40,41 | 2 | 0 | 0 |
| 9 | 173,174,175,366 | 4 | 4 | 4 |
| 10 | 1,1,2,2,2,2,2,2,3,3,3,3,3 | 0 | 0 | 0 |

At **every** candidate cap, at least one used section falls outside it in most
questions — 8/10 questions at cap 20, 6/10 at cap 50, **5/10 even at cap
100**. Q9's used sections cluster at ranks 173–366; nothing under a cap near
400 would have let that question's agent do what it actually did. The tail
isn't rare — it's most questions, once you count every section the agent
opened rather than just the first one.

## Token savings at those caps

| cap | tokens (10 Qs) | saved vs. no cap | used sections silently cut |
|---|---|---|---|
| none (today) | 291,575 | — | 0 |
| 100 | 49,679 | 83% | **15** |
| 50 | 26,731 | 91% | **22** |
| 20 | 11,796 | 96% | **31** |

The savings are real and large. So is the breakage: every cap tested cuts
sections the agent went on to `get` — which, per the harness's own system
prompt, means every claim grounded in one of those sections would either go
uncited or get answered from a section the agent never actually opened. This
run's correctness rate was 5/10 (`urbandocs-eval-search-cap-90-24f31af0`) —
not a baseline to compare against without a matched uncapped run, but it means
some of this set's questions were already failing before any cap made the
tail harder to reach.

## A different lever: capping by score, not by rank

Rank caps aren't the only shape a cap could take. `search`'s score is
*distinct slots matched* (`src/urbandocs/search.py`), and on the easy set the
distribution is heavily front-loaded: every question's `search` call
returned 270–528 score-1 sections (a single matched term) out of 300–1000+
total — most of the bulk, not the tail. A floor of `score >= 2` on the easy
set threw out 52% of the tokens and, in 9 of 10 questions, cut nothing the
agent went on to `get`. The one exception (Q2) cut 4 score-1 sections the
agent had fetched but never cited in its final answer.

Re-running the same score-floor check on the 10 complex questions
(`urbandocs-eval-search-cap-90-complex-fcf2cc13`) found one break: at
`score >= 2`, Q7 cut `PGO:p11:§5` — a section the model's final answer cites
by id for *"aplicación obligatoria del Plan General en el término
municipal"*, a load-bearing claim, not exploratory noise.

**Per Javier: Q7 isn't a realistic case.** The complex half of the gold set
is synthetic, built to stress multi-round behavior rather than sampled from
how a real question actually arrives, and Q7 doesn't read as one an
architect would actually ask. Setting it aside and re-running the same
`score >= 2` check over the other 19 questions (all 10 easy + 9 of 10
complex):

| | value |
|---|---|
| questions where `score >= 2` cut anything the agent `get`-ed | 3 of 19 (easy Q2, complex Q6, complex Q10) |
| sections cut, those 3 questions | 4, 1, 1 |
| any of those cut sections literally cited in the final answer | **0** |
| total token savings, all 19 questions combined | **49%** (706,330 -> 356,921 tok) |

With Q7 out, `score >= 2` is clean: across both halves of the gold set it
never cut a section the agent actually relied on, while still removing
roughly half the token cost of every `search` call — the single-term,
score-1 hits that make up the bulk of every sweep (270-528 of them per call
on the easy set alone) turn out to be mostly noise the agent never opens.

## Recommendation

**A `score >= 2` floor on `search` is worth pursuing; rank-based caps are
not.** Rank caps (20/50/100) cut something the agent actually used in most
questions at every value tried — never a value that was both small enough to
help and safe enough to trust. The score floor is different in kind, not
just degree: it isn't picking an arbitrary cutoff in a long tail, it's
dropping the single-matched-term hits that `search`'s own ranking already
treats as the weakest signal (`score` = distinct slots matched,
`src/urbandocs/search.py`) — and with the one non-representative complex
question set aside, dropping them cost nothing observed across 19 real
transcripts.

This still isn't a green light to implement without more evidence: n=19,
single-pass conversations, still not the sample #90 asks for (a
representative pull across the whole 20-question set run under realistic
multi-round conditions), and it still says nothing about #86's
replay-compounding — the same `search` result resent to the model every
round of a multi-round question, which no run here isolated. But it's a
different shape of finding than the rank caps: a candidate with a plausible
justification (score already ranks it as weak) and zero observed breakage,
where every rank cap tried had neither. If #56 gets revisited, this is the
concrete form the counter-argument should take, checked against a larger
sample before it ships.

## Reproducing

`evals/` has no built-in way to dump per-tool-call payloads — LangSmith's own
trace for this harness is aggregate-only (see Method). The run above added a
temporary, env-gated dump in `agent.answer_question` (`EVAL_DUMP_MESSAGES=<path>`,
appending each question's `ModelMessagesTypeAdapter.dump_python(...)` as one
JSON line) and reverted it afterwards — nothing in `evals/` carries this
instrumentation. To reproduce: reapply that one-line dump, start
`uv run -m urbandocs.server` locally, then
`uv run urbandocs-evals run --set easy` (or `--set complex`) from `evals/`
with `EVAL_DUMP_MESSAGES` set.
