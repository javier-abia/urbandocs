"""Locating the repo's data from inside the package.

Reads live at the repo root, not as package data: `docling-tuned/*.json` is a
shared input `tools/docling-convert/` also writes, and `corpus/` is
gitignored and rebuilt in under a second (#46).

Not `parents[N]` from `__file__` (`scripts/`'s approach): the depth is a
magic number, and it resolves into site-packages if installed non-editable.
Anchors on a marker file instead, so the search finds nothing rather than
something plausible when there is no repo above it.

Resolution order, most explicit first:

1. an explicit path, passed by the caller -- how tests point at a fixture root
2. `$URBANDOCS_ROOT`, for a deploy that puts the data somewhere unusual
3. an upward search for `pyproject.toml`, the repo's marker
"""

from __future__ import annotations

import os
from pathlib import Path

#: Marker for the repo root. Not `.git`: absent from a `git archive` checkout
#: or release tarball, and a marker that vanishes in production is worse than none.
ANCHOR = "pyproject.toml"

ENV_VAR = "URBANDOCS_ROOT"


class RootNotFoundError(RuntimeError):
    """No repo root above this module, and none given.

    Raised rather than falling back to the working directory: a wrong root fails
    later, further away, as a confusing "missing document" (#46).
    """


def repo_root(explicit: str | Path | None = None) -> Path:
    """Return the repo root. See module docstring for the resolution order."""
    if explicit is not None:
        return Path(explicit).resolve()

    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).resolve()

    here = Path(__file__).resolve()
    for directory in here.parents:
        if (directory / ANCHOR).is_file():
            return directory

    raise RootNotFoundError(
        f"no {ANCHOR} above {here}; pass an explicit root or set ${ENV_VAR}"
    )


def tuned_dir(root: str | Path | None = None) -> Path:
    """Stage 1's committed output, which Stage 2 reads. A permanent input (#4)."""
    return repo_root(root) / "documentos" / "documentos-docling" / "docling-tuned"


def corpus_tsv(root: str | Path | None = None) -> Path:
    """Stage 2's output: the retrieval substrate. Derived, gitignored."""
    return repo_root(root) / "corpus" / "corpus.tsv"
