# opencode's replay mechanism, and the lever that already exists

Resolves [#91](https://github.com/javier-abia/urbandocs/issues/91) (spike,
understanding-only, under [#86](https://github.com/javier-abia/urbandocs/issues/86)).
The question was how opencode/LiteLLM assemble each round's request and
whether anything can stop a `search`/`get` result from being paid for again
on every subsequent round. It can — opencode ships a config flag for exactly
this — but it defaults to doing nothing, silently, which is the actual finding.

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

## Subagent splitting: real lever, real cost

Splitting a multi-step question across separate subagent calls keeps each
subagent's own context free of the others' tool history, so it sidesteps
replay compounding structurally rather than pruning after the fact. The
cost is re-establishing shared context per subagent — a second subagent
that needs the first's `search` results has to either re-run the sweep or
have them handed over explicitly — and coordination: something has to
synthesize the subagents' separate findings into one answer with one
citation set, which is exactly the job the current single-loop
`search → get → expand → answer` order does implicitly. Not measured here;
flagged as the one lever in this list that would need a prototype to cost,
not just a config change.

## Recommendation

**Prototype `compaction.prune` first.** It is the one lever that already
exists, is close to on by default (a documented bug away from it), needs no
urbandocs code change, and targets the exact payload #86 measured as
expensive — `search`'s ranked list and `get`'s verbatim text are ordinary
tool outputs to it, no exemption needed. The open questions a prototype
would answer: whether 40K/20K are the right thresholds for a corpus where
one `search` call already runs 1.2–2.4K tokens (default thresholds were
clearly tuned for code-editing tool output, not this shape), and whether
losing a pruned `search` line's addresses mid-session ever costs a
citation opencode's own protected-last-2-turns window would have caught.

`compaction.auto`'s whole-session summarization is a second, coarser lever
worth knowing about but not worth prototyping first — it discards structure
`compaction.prune` keeps, and #86's actual round-3 cost (51.4K) is nowhere
near typical context limits, so it wouldn't trigger on the traces that
motivated this.

Subagent splitting stays a candidate for a *following* question, not this
one — it changes the loop's shape, where `compaction.prune` changes nothing
this repo owns or has to test against its own tool contracts.

## What's confirmed against this deployment, not just source

`~/.config/opencode/opencode.json` — the config behind #86's actual Q8 trace
— carries no `compaction` key at all. Under the default-off behavior
diagnosed above, that means pruning was off for the run that motivated this
whole spike, not merely off by some worst-case assumption. Turning on
`compaction.prune` (and tuning its thresholds for this corpus) is therefore
a config edit to that one file, not a code change anywhere.

The one thing still unconfirmed is whether `1.18.18` (the version actually
installed) matches the `dev`-branch source read here — worth a `--version`
diff against the tagged release before trusting the exact line numbers, not
before trusting the mechanism.
