import pytest

from urbandocs_evals.config import Config, ConfigError, dataset_name_from_env

REQUIRED_ENV = {
    "LITELLM_BASE_URL": "https://litellm.example/v1",
    "LITELLM_EVAL_API_KEY": "sk-eval-key",  # pragma: allowlist secret
    "URBANDOCS_MCP_URL": "https://litellm.example/normativa/mcp",
    "EVAL_MODEL": "gpt-4.1",
    "EVAL_JUDGE_MODEL": "claude-opus",
    "LANGSMITH_API_KEY": "ls-key",  # pragma: allowlist secret
}


def _set_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    env = {**REQUIRED_ENV, **overrides}
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_from_env_reads_required_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    monkeypatch.delenv("LANGSMITH_DATASET", raising=False)
    monkeypatch.delenv("EVAL_MAX_REQUESTS", raising=False)
    cfg = Config.from_env()
    assert cfg.eval_model == "gpt-4.1"
    assert cfg.judge_model == "claude-opus"
    assert cfg.mcp_url == "https://litellm.example/normativa/mcp"
    assert cfg.langsmith_dataset == "urbandocs-gold-set"
    assert cfg.max_requests == 50


def test_from_env_missing_var_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    monkeypatch.delenv("EVAL_MODEL", raising=False)
    with pytest.raises(ConfigError, match="EVAL_MODEL"):
        Config.from_env()


def test_from_env_requires_mcp_url_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    # No default: the chat-completions base and the MCP passthrough route
    # aren't the same URL, so this can't be derived (#85 spec review).
    _set_env(monkeypatch)
    monkeypatch.delenv("URBANDOCS_MCP_URL", raising=False)
    with pytest.raises(ConfigError, match="URBANDOCS_MCP_URL"):
        Config.from_env()


def test_from_env_rejects_judge_same_as_eval_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, EVAL_JUDGE_MODEL="gpt-4.1")
    with pytest.raises(ConfigError, match="self-preference"):
        Config.from_env()


def test_from_env_max_requests_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, EVAL_MAX_REQUESTS="10")
    cfg = Config.from_env()
    assert cfg.max_requests == 10


def test_dataset_name_from_env_matches_config_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # `run` (via `Config.from_env`) and `upload-dataset` (via this function
    # directly) must agree on which dataset they mean when only
    # LANGSMITH_DATASET is set -- a prior bug had `upload-dataset` carry its
    # own hardcoded argparse default that ignored this env var entirely.
    monkeypatch.delenv("LANGSMITH_DATASET", raising=False)
    assert dataset_name_from_env() == "urbandocs-gold-set"

    monkeypatch.setenv("LANGSMITH_DATASET", "my-custom-set")
    assert dataset_name_from_env() == "my-custom-set"
    _set_env(monkeypatch, LANGSMITH_DATASET="my-custom-set")
    assert Config.from_env().langsmith_dataset == dataset_name_from_env()
