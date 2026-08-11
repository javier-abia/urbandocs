"""Environment configuration for the eval harness, fail-loud (#85).

Every value the harness needs to reach the real engine, LiteLLM, and
LangSmith comes from the environment -- nothing here defaults a model name
or a key, because #85 explicitly defers "exact model to test and exact
judge model" to whatever production LiteLLM actually runs. A missing
required variable is a startup error, not a silent fallback.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """A required environment variable is missing or invalid."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required (set it in the environment or evals/.env)")
    return value


DEFAULT_MAX_REQUESTS = 50  # matches pydantic-ai's own UsageLimits default


@dataclass(frozen=True)
class Config:
    litellm_base_url: str
    litellm_api_key: str
    mcp_url: str
    eval_model: str
    judge_model: str
    langsmith_dataset: str
    max_requests: int

    @classmethod
    def from_env(cls) -> Config:
        litellm_base_url = _require("LITELLM_BASE_URL").rstrip("/")
        litellm_api_key = _require("LITELLM_EVAL_API_KEY")
        eval_model = _require("EVAL_MODEL")
        judge_model = _require("EVAL_JUDGE_MODEL")

        # #85's grading section: a judge that is the same model as the one
        # under test is self-preference bias, not a check. #85 also asks
        # for a *stronger* judge, which isn't a thing this can verify --
        # that half stays an operator responsibility, documented in
        # .env.example.
        if judge_model == eval_model:
            raise ConfigError(
                "EVAL_JUDGE_MODEL must differ from EVAL_MODEL -- a model judging "
                "its own answers is the self-preference bias #85 rules out"
            )

        # No default: LiteLLM's chat-completions base (needed for
        # `OpenAIProvider`, typically ending in `/v1`) and its MCP
        # passthrough route (`<litellm-url>/normativa/mcp`, deploy-runbook's
        # verification step 2, hung off the proxy *root*) are not the same
        # base URL, so this can't be derived from `LITELLM_BASE_URL` without
        # guessing which one it is.
        mcp_url = _require("URBANDOCS_MCP_URL")

        # LANGSMITH_API_KEY / LANGSMITH_TRACING / LANGSMITH_PROJECT are read
        # directly by the `langsmith` SDK; required here only so a missing
        # key fails before any model or MCP call runs, not partway through.
        _require("LANGSMITH_API_KEY")

        langsmith_dataset = os.environ.get(
            "LANGSMITH_DATASET", "urbandocs-gold-set"
        ).strip()

        # "Runs until it produces a final prose answer with citations, or
        # stops" (#85) -- the "or stops" half needs an enforced cap, since
        # nothing about the MCP loop otherwise bounds it.
        max_requests_raw = os.environ.get("EVAL_MAX_REQUESTS", "").strip()
        max_requests = int(max_requests_raw) if max_requests_raw else DEFAULT_MAX_REQUESTS

        return cls(
            litellm_base_url=litellm_base_url,
            litellm_api_key=litellm_api_key,
            mcp_url=mcp_url,
            eval_model=eval_model,
            judge_model=judge_model,
            langsmith_dataset=langsmith_dataset,
            max_requests=max_requests,
        )
