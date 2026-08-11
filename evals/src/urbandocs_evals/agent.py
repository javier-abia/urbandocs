"""The stand-in caller: a `pydantic-ai` agent as a real MCP client (#85).

`urbandocs.server` has only ever assumed an external caller (Codex, Claude
Code, opencode); this repo has never implemented one itself. This module is
that caller for eval purposes -- no mocking: it connects to the engine's
real `search`/`get`/`get_by_cite`/`get_page` tools over MCP, and calls the
model under test through LiteLLM's OpenAI-compatible endpoint on a
dedicated eval key.

The tool descriptions (`src/urbandocs/server.py`) already carry the loop
order, the term floor, and the evidence contract (#59, #64) -- MCP cannot
compel a call sequence, so those instructions are the only thing that makes
the agent sweep before it gets, and get before it answers. This module adds
nothing to that contract; it only tells the model it is answering as a
technical architect and must ground every claim in a citation.
"""

from __future__ import annotations

from pydantic_ai import Agent, UsageLimitExceeded
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from urbandocs_evals.config import Config

SYSTEM_PROMPT = (
    "You are a technical architect's assistant, answering questions about "
    "local construction-permit normativa using only the `search`, `get`, "
    "`get_by_cite` and `get_page` tools available to you -- never from "
    "outside knowledge. Follow the loop each tool's own description "
    "specifies: sweep with `search` first, `get` the sections that matter, "
    "expand by at most one in-corpus pointer if it opens a new question, "
    "then answer. Every claim in your final answer must be grounded in a "
    "record you actually opened with `get` or `get_page` -- never in a "
    "`search` line alone, since those carry no legal text. End your answer "
    "with the citations for every provision it relies on -- document and "
    "page, plus the record id or cite where you have one. An answer whose "
    "claim is right but whose citation is missing or wrong is a failure, "
    "not a partial success."
)


def build_litellm_model(cfg: Config, model_name: str) -> OpenAIChatModel:
    """An OpenAI-compatible model routed through LiteLLM on the eval key.

    Shared by the agent under test and the judge (#85: same LiteLLM route,
    different model names) so the provider wiring exists in one place.
    """
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(base_url=cfg.litellm_base_url, api_key=cfg.litellm_api_key),
    )


def build_agent(cfg: Config) -> Agent[None, str]:
    """Wire the agent under test: LiteLLM model, real MCP toolset."""
    toolset = MCPToolset(
        cfg.mcp_url,
        headers={"Authorization": f"Bearer {cfg.litellm_api_key}"},
    )
    return Agent(
        build_litellm_model(cfg, cfg.eval_model),
        toolsets=[toolset],
        system_prompt=SYSTEM_PROMPT,
    )


async def answer_question(agent: Agent[None, str], question: str, *, max_requests: int) -> str:
    """Run the agent to completion and return its final prose answer.

    "Runs until it produces a final prose answer with citations, or stops"
    (#85) -- `max_requests` is the enforced cap for that second case. A run
    that hits it produces no answer to grade, so it's reported as a stalled
    run rather than raised, and the judge fails it on content alone.
    """
    try:
        result = await agent.run(question, usage_limits=UsageLimits(request_limit=max_requests))
    except UsageLimitExceeded:
        return (
            f"[stopped: exceeded {max_requests} model requests without producing "
            "a final answer]"
        )
    return result.output
