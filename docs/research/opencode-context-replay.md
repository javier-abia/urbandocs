# opencode's replay mechanism, and why the fix isn't a client-side lever

Resolves [#91](https://github.com/javier-abia/urbandocs/issues/91) (spike,
understanding-only, under [#86](https://github.com/javier-abia/urbandocs/issues/86)).
The question was how opencode/LiteLLM assemble each round's request and
whether anything can stop a `search`/`get` result from being paid for again
on every subsequent round. It can, in opencode specifically — but opencode is
the owner's current interactive client, not a commitment for deployment
(owner, 2026-08-16: "in deployment I will probably not use opencode"), so a
config flag that lives in one client's `~/.config` is evidence about the
mechanism, not a fix urbandocs can rely on. The durable levers are the ones
that don't assume which client shows up.

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

**Don't build on `compaction.prune`.** It proves the mechanism (pruning old
tool output measurably works, opencode already does it once turned on) but
it lives in one client's config file, and the owner doesn't expect that
client at deployment. Turning it on is a fine stopgap for today's own
interactive use of opencode — one line in
`~/.config/opencode/opencode.json` — but it is not something #86's tracking
issue should count as solved, since whatever client actually ends up
calling this MCP server is under no obligation to have anything like it.

**The durable levers are the ones already in flight or genuinely
client-agnostic**, both because #91 found no protocol- or gateway-level
lever exists:

- **Payload-size reduction** (#87–90, five of six sub-issues already
  landed per #86) is the one category that helps under *any* client,
  including a full-replay one with no pruning at all — it shrinks what
  gets paid for every round rather than trying to stop the resend. This is
  where further effort belongs.
- **Subagent splitting** stays worth a prototype once the deployment client
  is actually chosen — it's a design pattern most modern agent harnesses
  support in some form (not a config flag), so it doesn't gamble on one
  client's feature set the way `compaction.prune` does. Its cost
  (re-establishing shared context, synthesis across subagents) still needs
  measuring before recommending it, which #91 didn't attempt.

If the eventual production client turns out to be one urbandocs builds
itself (in `pydantic_ai`'s style, per `evals/src/urbandocs_evals/agent.py`),
loop-level pruning becomes a lever urbandocs actually owns rather than
borrows from a client's config — worth revisiting then, not now.

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
