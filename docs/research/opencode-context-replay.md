# Replay compounding across clients, and the Codex subagent lever

Resolves [#91](https://github.com/javier-abia/urbandocs/issues/91) (spike,
understanding-only, under [#86](https://github.com/javier-abia/urbandocs/issues/86)).
The question was how opencode/LiteLLM assemble each round's request and
whether anything can stop a `search`/`get` result from being paid for again
on every subsequent round. opencode has a config-level answer, but opencode
is the owner's current interactive client, not the deployment one — the
owner expects deployment to run through the **Codex desktop app** instead
(owner, 2026-08-16). Codex was researched directly rather than treating
opencode's answer as representative: it turns out to have the same replay
problem but a materially different, and stronger, lever for it.

## The mechanism is what everyone assumes, confirmed against source

opencode resends the full stored message history — including every prior
tool result — on every round. `MessageV2.toModelMessagesEffect`
(`packages/opencode/src/session/message-v2.ts`) converts the whole session's
messages to model format on each call; there is no per-round trimming step
by default. This is not opencode-specific: it is how any loop built on the
stateless Chat Completions API behaves, `urbandocs_evals`'s own
`pydantic_ai.Agent` + `MCPToolset` loop included
(`evals/src/urbandocs_evals/agent.py`). Nothing here is a bug to report
upstream; it explains the *shape* of #86's Q8 numbers (26.6k → 45.0k → 51.4k
across 3 rounds) without needing anything opencode-specific — round *N*
pays for every byte round *N-1* got back, on any such loop.

## Two compaction mechanisms exist; only one is close to on by default

opencode's `session/compaction.ts` and `session/overflow.ts` implement two
distinct things, both gated by config under `compaction`:

**`compaction.auto`** — whole-session summarization when
`isOverflow()` trips: total tokens (`tokens.total`, or input + output +
cache read/write) exceed the model's context limit minus a
`COMPACTION_BUFFER` (20,000 tokens by default, or a configured reserve).
Old messages get replaced with a structured Markdown summary (goal,
constraints, progress, decisions, next steps). Defaults **on** — the
overflow check only disables it when `compaction.auto === false`.

**`compaction.prune`** — this is the lever your `get`-time idea describes.
A backward scan over messages, marking old *tool outputs* as cleared
(`part.state.time.compacted = Date.now()`) while keeping the tool-call
record itself, so structure survives but payload doesn't get resent. Gated
by two thresholds: only fires once accumulated tool-output tokens exceed
`PRUNE_PROTECT` (40,000), and only commits if it can free at least
`PRUNE_MINIMUM` (20,000) tokens. The last two conversation turns are always
protected, and `PRUNE_PROTECTED_TOOLS = ["skill"]` is permanently excluded
— nothing exempts `search`/`get` specifically, so ranked-section lists and
verbatim records are ordinary prune targets once old enough.

**It defaults to off, contradicting its own docs.** `prune()` opens with
`if (!cfg.compaction?.prune) return` — an *omitted* config key disables it,
not enables it — which a filed opencode bug
([anomalyco/opencode#24108](https://github.com/anomalyco/opencode/issues/24108))
already diagnosed at this exact line: documented as default-enabled,
actually default-disabled. `Flag.OPENCODE_DISABLE_PRUNE` exists to force it
off explicitly, which only makes sense if the intended default is on.

This is a materially different shape than "aging out" as originally
imagined: it is not semantic (opencode has no notion that `get` supersedes
the `search` line it followed) and not per-tool — it is a global,
budget-triggered sweep over the oldest tool output once *total* tool-output
tokens cross 40K. On a corpus where a single `search` call already runs
1.2–2.4K tokens (`docs/research/mcp-tool-surface.md`), that threshold is
reachable within a handful of rounds, not a rare tail case.

## Codex: the actual likely deployment client

Checked directly rather than assumed from opencode's behavior, since the two
are separate codebases with no reason to match.

**Same replay problem.** The Responses API supports server-side conversation
state via `previous_response_id` — a caller can pass just the new turn and
let OpenAI's servers hold the rest, avoiding resend entirely. Codex doesn't
use it for multi-turn state despite the API supporting it
([openai/codex#4047](https://github.com/openai/codex/issues/4047)), so full
history — every prior tool result included — gets resent each round, the
same shape as opencode's and as `urbandocs_evals`'s own pydantic-ai loop.

**Codex's own compaction is opaque, not tunable.** Server-side, opt-in via
`context_management.compact_threshold` on the Responses API call — and the
resulting compacted item is explicitly documented as "opaque and not
intended to be human-interpretable," an encrypted blob only OpenAI's
servers can decrypt. No equivalent to opencode's `compaction.prune`
(selective, inspectable, tool-output-specific, threshold I could reason
about against this corpus's payload sizes). Nothing here for urbandocs to
target even if the desktop app turns it on.

**Codex has native subagents, in the desktop app, triggerable by
instruction.** This is the lever that matters. Each subagent runs in its
own context window and sandbox; its tool-call history is explicitly isolated
from the orchestrator's thread — the docs frame this as preventing "context
pollution." Delegation can be triggered three ways: an explicit user ask,
autonomously (Ultra tier only), or **by `AGENTS.md`/skill instructions** —
meaning it can be made standing behavior for this MCP server specifically,
not something the architect has to remember to invoke. Subagent activity
"appears in the ChatGPT desktop app, Codex CLI, and the IDE extension," so
this isn't a CLI-only feature the desktop app lacks.

**The risk that has to survive prototyping: subagents return summaries by
default, not raw output.** Codex's own docs frame this as the point — "return
summaries instead of raw intermediate output" to keep the orchestrator's
thread clean. That collides directly with this repo's citation guarantee:
"evidence-only output with no synthesis," every claim grounded in a record
actually opened with `get`, never a paraphrase
(`mcp-tool-surface.md`; `evals/src/urbandocs_evals/agent.py`'s
`SYSTEM_PROMPT`). A subagent that summarizes a `get` result instead of
returning it verbatim can silently drop or reword the citation an architect
would otherwise verify against the source PDF. Whether an explicit
instruction — "return the `get` record verbatim: text, ancestor chain,
citation id — never summarize or paraphrase" — reliably overrides Codex's
default summarizing behavior is unconfirmed; it is the first thing a
prototype needs to test, before token savings are even worth measuring.

## No protocol-level lever either

MCP itself has nothing that would make aging-out portable across clients.
Tool metadata as of the 2026-07-28 spec carries `readOnlyHint`,
`destructiveHint`, `idempotentHint`, `openWorldHint`, and (new in that
release) cache hints for the *tool catalog* — there is no annotation a
server can attach to a *tool result* meaning "drop this once superseded" or
any per-call TTL. Aging out a result is purely a client-loop decision, the
same way opencode's is; nothing in the protocol lets urbandocs express it
once and have every compliant client honor it.

## What LiteLLM offers: caching, not trimming

Nothing at the gateway layer prunes or windows a request in flight. LiteLLM
proxy's relevant features are `context_window_fallbacks` (switch to a
larger-context model on a context-length error — a fallback, not a
reduction) and response caching (Redis/semantic/exact-match) — the latter
is what `cached_tokens` already reflects in the Q8 trace (11,495 → 26,613 →
44,995), offsetting dollar cost while leaving the replayed prompt, and the
context-window pressure it represents, unchanged. There is no config surface
that rewrites or trims an outbound request's message array. This closes the
"gateway lever" line from #91: there isn't one, on the public docs/source.
(Not checked against the deployed gateway's actual config — out of scope
per the owner, since urbandocs doesn't control that box.)

## Subagent splitting: two different shapes, one much cheaper than the other

**By loop phase** (owner's idea, 2026-08-16): one subagent runs the whole
`search → rank → get(→ expand)` sequence for a question and returns only
what `get` produced. This is the shape Codex's subagent primitive fits —
the ranked list, `search`'s expensive payload
(105–195 sections, ~12 tok/section per `mcp-tool-surface.md`, and exactly
the thing an architect never cites from anyway) exists only inside the
subagent's own context window and is discarded with it, never entering the
orchestrator's history to be replayed on every later round. Coordination
cost is close to zero — one subagent, one question, one boundary — and it's
*semantic* pruning: the ranked list is dropped because it's structurally
superseded by `get`, not because a token budget happened to trip.

**By sub-topic**: splitting a multi-step question into independent
subagents per sub-question (e.g. one for `anch`/width provisions, one for
`trastero`/storage-height provisions). Real coordination cost this repo
would have to own: a second subagent that needs the first's `search`
results has to either re-run the sweep or have them handed over explicitly,
and something has to synthesize the subagents' separate findings into one
answer with one citation set — the job the current single-loop order does
implicitly today. Not measured here; a real lever, but a costlier one, and
not what the owner's idea was describing.

## Recommendation

**Prototype delegating `search → get(→ expand)` to a Codex subagent,
instructed to return the `get` record verbatim.** This is the strongest
lever found, because it's now checked against the client actually expected
at deployment rather than the one that happened to produce #86's trace:

- The primitive exists natively in Codex, including the desktop app, and
  can be made standing behavior via `AGENTS.md`/skill instructions rather
  than relying on the architect to ask for delegation each time.
- It sidesteps replay compounding structurally — the ranked list never
  enters the orchestrator's history at all — rather than depending on any
  compaction feature being turned on, tunable, or even inspectable (Codex's
  own compaction is an opaque server-side blob; opencode's `compaction.prune`
  is a client config flag the deployment client has no obligation to carry).
- Coordination cost is near zero for the loop-phase shape (one subagent,
  one question), unlike splitting by sub-topic.

**The first thing to test is not token savings — it's whether the subagent
actually returns verbatim evidence instead of a summary.** Codex's docs
describe summarizing as the *intended* default behavior for subagents; an
instruction to preserve `get`'s exact text and citation id has to be
checked against real output, not assumed to reliably override that default.
If it doesn't hold, this lever fails the citation guarantee before it ever
gets to save a token, and the idea reverts to needing the sub-topic
shape's heavier coordination, or no subagent delegation at all.

**Payload-size reduction** (#87–90, five of six sub-issues already landed
per #86) stays worth continuing regardless of how the subagent prototype
goes — it helps inside a subagent's own context too, and doesn't depend on
Codex's delegation behavior holding up under test.

## What's confirmed, and what still needs a real run

Two different depths of confirmation went into this doc. opencode's
mechanism is confirmed against both source and this deployment's actual
config: `~/.config/opencode/opencode.json` (the config behind #86's real Q8
trace) carries no `compaction` key at all, so pruning was off for the run
that motivated this whole spike, not off by assumption. Codex's mechanism
is confirmed against public docs and a filed source-level bug report, but
**not yet against a real Codex desktop session** — the subagent primitive,
the `AGENTS.md`-triggering, and above all whether verbatim-return
instructions actually hold are all things this spike read about rather than
watched happen. That run is the next step, not this one, since #91 was
scoped as understanding-only.
