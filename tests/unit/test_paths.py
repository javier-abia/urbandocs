"""Root resolution — the thing that replaced `parents[N]` (#46).

These matter more than they look. Every one of them is a failure mode that, with
the old fixed-depth walk, produced a *plausible* wrong directory rather than an
error -- and a wrong root surfaces much later as a missing document.
"""

import pytest

from urbandocs import paths


def test_explicit_root_wins_over_everything(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path / "from-env"))
    assert paths.repo_root(tmp_path) == tmp_path.resolve()


def test_env_var_wins_over_the_anchor_search(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    assert paths.repo_root() == tmp_path.resolve()


def test_anchor_search_finds_this_repo(monkeypatch):
    # No explicit root, no env var: walk up from the module and find the repo
    # this test is running inside.
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    root = paths.repo_root()
    assert (root / paths.ANCHOR).is_file()
    assert (root / "src" / "urbandocs" / "paths.py").is_file()


def test_missing_root_raises_rather_than_guessing(monkeypatch):
    # The old behaviour resolved to *something* no matter what. Refusing is the
    # point: a bad root must fail here, not three call frames later.
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.setattr(paths, "ANCHOR", "definitely-not-a-real-marker")
    with pytest.raises(paths.RootNotFoundError):
        paths.repo_root()


def test_two_roots_do_not_leak_into_each_other(tmp_path):
    # This is the property `global TUNED` could not offer, and the reason #49's
    # fixture tests can be written at all.
    a, b = tmp_path / "a", tmp_path / "b"
    assert paths.tuned_dir(a) != paths.tuned_dir(b)
    assert paths.tuned_dir(a).is_relative_to(a)


def test_data_paths_hang_off_the_root(tmp_path):
    assert paths.corpus_tsv(tmp_path) == tmp_path / "corpus" / "corpus.tsv"
    assert paths.tuned_dir(tmp_path) == (
        tmp_path / "documentos" / "documentos-docling" / "docling-tuned"
    )
