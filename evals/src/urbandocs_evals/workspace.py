"""The workspace variant: an outer agent with one `research` tool, backed by a worker.

The outer agent stands in for Codex. It sees only `research(question)` and the
records that call returns. The worker runs the real `search`/`get` loop over MCP,
but its own context holds instructions, a one-line log per finished step, and
only the latest tool result. Every fetched record lives in `Workspace`, in code,
and the reply is built from the stored originals, so the worker never retypes
legal text.
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent, RunContext, UsageLimitExceeded
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart
from pydantic_ai.usage import RunUsage, UsageLimits

from urbandocs_evals.agent import AnswerResult, _peak_context_tokens, build_litellm_model

if TYPE_CHECKING:
    from urbandocs_evals.config import Config

Record = dict[str, Any]

SHOW = 15  # sections a worker sees per search page; the rest wait behind `more`
WORKER_MAX_REQUESTS = 25

WORKER_PROMPT = (
    "You gather evidence from local construction-permit normativa for one "
    "question. You never write the answer. Split the question into its parts "
    "(one per regulation or topic it names). For each part: `search` with one "
    "stem per content word, `get` the ids that look relevant, then `keep` only "
    "the records whose text the answer will rely on, including the record "
    "that carries a qualifier or exception. Old tool results shrink to one "
    "line after you have seen them, but every record stays retrievable: call "
    "`get` again on an id to reread it. Use `more` only if the shown sections "
    "clearly miss the topic. Stop when every part has kept evidence or you "
    "are sure the corpus does not cover it. Then reply with one sentence "
    "naming any part you found no evidence for, or 'complete'."
)

OUTER_PROMPT = (
    "You are a technical architect's assistant, answering questions about "
    "local construction-permit normativa using only the `research` tool -- "
    "never from outside knowledge. Call `research` with the question, or with "
    "a narrower follow-up if the evidence leaves a part open. It returns "
    "verbatim records with their document, page and id. Every claim in your "
    "final answer must be grounded in a returned record. End your answer with "
    "the citations for every provision it relies on -- document and page, "
    "plus the record id or cite where you have one. An answer whose claim is "
    "right but whose citation is missing or wrong is a failure, not a partial "
    "success."
)


@dataclass
class Workspace:
    """Everything a worker run has fetched, outside the model's context."""

    mcp: MCPToolset
    searches: list[dict[str, Any]] = field(default_factory=list)
    records: dict[str, Record] = field(default_factory=dict)
    kept: list[str] = field(default_factory=list)
    stubs: dict[str, str] = field(default_factory=dict)  # tool_call_id -> log line


@dataclass
class WorkerStats:
    """Worker cost across every `research` call in one outer run."""

    usage: RunUsage = field(default_factory=RunUsage)
    peak_context_tokens: int = 0
    calls: int = 0


def page_of(response: dict[str, Any], offset: int) -> dict[str, Any]:
    """One `SHOW`-sized page of a `search` response, its ancestor pool re-indexed."""
    sections = response["sections"][offset : offset + SHOW]
    pool: dict[str, int] = {}
    out = []
    for s in sections:
        ids = [pool.setdefault(response["ancestors"][i], len(pool)) for i in s["ancestor_ids"]]
        out.append({**s, "ancestor_ids": ids})
    return {"ancestors": list(pool), "sections": out}


def collapse_old_results(
    ctx: RunContext[Workspace], messages: list[ModelMessage]
) -> list[ModelMessage]:
    """Replace every tool result except the latest round's with its log line."""
    stubs = ctx.deps.stubs
    last_request = max(
        (i for i, m in enumerate(messages) if isinstance(m, ModelRequest)), default=-1
    )
    out: list[ModelMessage] = []
    for i, m in enumerate(messages):
        if i != last_request and isinstance(m, ModelRequest):
            parts = [
                dataclasses.replace(p, content=stubs[p.tool_call_id])
                if isinstance(p, ToolReturnPart) and p.tool_call_id in stubs
                else p
                for p in m.parts
            ]
            m = dataclasses.replace(m, parts=parts)
        out.append(m)
    return out


def render(records: list[Record]) -> str:
    """The reply to the outer agent: stored originals, with their citations."""
    blocks = []
    for r in records:
        lines = [f"[{r['doc']} p.{r['page']} · {r['id']}]", " > ".join(r["ancestors"]), r["text"]]
        lines += [f"  {c['id']}: {c['text']}" for c in r.get("children", [])]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_worker(cfg: Config, model_name: str) -> Agent[Workspace, str]:
    worker = Agent(
        build_litellm_model(cfg, model_name),
        name="urbandocs-worker",
        deps_type=Workspace,
        system_prompt=WORKER_PROMPT,
        capabilities=[ProcessHistory(collapse_old_results)],
    )

    @worker.tool
    async def search(ctx: RunContext[Workspace], terms: list[str]) -> dict[str, Any]:
        """Sweep the corpus. Submit one stem (3+ characters) per content word,
        at least two terms, no bare numbers. Returns the top sections as
        addresses only (no legal text) and the total count; `get` the ids
        that matter."""
        ws = ctx.deps
        response = await ws.mcp.direct_call_tool("search", {"terms": terms})
        ws.searches.append(response)
        n, total = len(ws.searches), len(response["sections"])
        ws.stubs[ctx.tool_call_id or ""] = (
            f"search #{n} ({', '.join(terms)}) -> {total} sections, top {min(SHOW, total)} shown"
        )
        return {"search": n, "total": total, **page_of(response, 0)}

    @worker.tool
    async def more(ctx: RunContext[Workspace], search: int, offset: int) -> dict[str, Any]:
        """The next page of an earlier search's sections, starting at `offset`."""
        response = ctx.deps.searches[search - 1]
        ctx.deps.stubs[ctx.tool_call_id or ""] = f"more(search #{search}, from {offset})"
        return {"search": search, "offset": offset, **page_of(response, offset)}

    @worker.tool
    async def get(ctx: RunContext[Workspace], ids: list[str]) -> dict[str, Any]:
        """Verbatim text of section or record ids (compact `DOC:pN:a,b` entries
        accepted), each with its ancestor chain and direct children."""
        ws = ctx.deps
        response = await ws.mcp.direct_call_tool("get", {"ids": ids})
        for r in response["records"]:
            ws.records[r["id"]] = r
            for c in r["children"]:
                ws.records.setdefault(
                    c["id"],
                    {
                        **c,
                        "doc": r["doc"],
                        "page": r["page"],
                        "ancestors": [*r["ancestors"], r["text"]],
                    },
                )
        got = [r["id"] for r in response["records"]]
        ws.stubs[ctx.tool_call_id or ""] = f"get -> {len(got)} records: {', '.join(got)}"
        return response

    @worker.tool
    async def keep(ctx: RunContext[Workspace], ids: list[str]) -> str:
        """Mark records as evidence for the answer. Only kept records are
        returned; everything else is discarded when you finish."""
        ws = ctx.deps
        unknown = [i for i in ids if i not in ws.records]
        added = [i for i in ids if i in ws.records and i not in ws.kept]
        ws.kept += added
        note = f"; not fetched yet, `get` them first: {', '.join(unknown)}" if unknown else ""
        return f"kept {len(added)}, {len(ws.kept)} in total{note}"

    return worker


def build_outer(cfg: Config, worker: Agent[Workspace, str]) -> Agent[WorkerStats, str]:
    outer = Agent(
        build_litellm_model(cfg, cfg.eval_model),
        name="answer-normativa-question-workspace",
        deps_type=WorkerStats,
        system_prompt=OUTER_PROMPT,
    )

    @outer.tool
    async def research(ctx: RunContext[WorkerStats], question: str) -> str:
        """Gather verbatim normativa evidence for a question. Returns the
        governing records with document, page, id and ancestor chain."""
        ws = Workspace(mcp=MCPToolset(cfg.mcp_url, headers=_auth(cfg)))
        stats = ctx.deps
        stats.calls += 1
        async with ws.mcp:
            try:
                run = await worker.run(
                    question,
                    deps=ws,
                    usage=stats.usage,
                    usage_limits=UsageLimits(
                        request_limit=stats.usage.requests + WORKER_MAX_REQUESTS
                    ),
                )
                note = run.output
                stats.peak_context_tokens = max(
                    stats.peak_context_tokens, _peak_context_tokens(run.all_messages())
                )
            except UsageLimitExceeded:
                note = f"stopped after {WORKER_MAX_REQUESTS} steps; evidence may be incomplete"
        kept = [ws.records[i] for i in ws.kept]
        if not kept:
            return f"No evidence kept. Worker note: {note}"
        return f"Worker note: {note}\n\n{render(kept)}"

    return outer


def _auth(cfg: Config) -> dict[str, str]:
    return {"Authorization": f"Bearer {cfg.litellm_api_key}"}


async def answer_question_workspace(
    cfg: Config, question: str, *, worker_model: str, max_requests: int
) -> AnswerResult:
    """Run the outer agent to an answer; worker cost is reported separately."""
    outer = build_outer(cfg, build_worker(cfg, worker_model))
    stats = WorkerStats()
    start = time.monotonic()
    try:
        result = await outer.run(
            question, deps=stats, usage_limits=UsageLimits(request_limit=max_requests)
        )
    except UsageLimitExceeded:
        return AnswerResult(
            answer=f"[stopped: exceeded {max_requests} model requests without a final answer]",
            usage=RunUsage(),
            elapsed_seconds=time.monotonic() - start,
            worker=stats,
        )
    return AnswerResult(
        answer=result.output,
        usage=result.usage,
        elapsed_seconds=time.monotonic() - start,
        peak_context_tokens=_peak_context_tokens(result.all_messages()),
        worker=stats,
    )
