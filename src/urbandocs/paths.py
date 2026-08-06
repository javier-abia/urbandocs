"""Locating the repo's data from inside the package.

The engine and Stage 2 read files that live at the repo root -- the committed
`docling-tuned/*.json` that Stage 1 emits, and the `corpus/` Stage 2 derives from
them (#46). Neither is package data: `docling-tuned/` is a shared *input* that
`tools/docling-convert/` also writes, and `corpus/` is gitignored and rebuilt in
under a second. So the package has to find them at runtime.

`parents[N]` from `__file__` is what `scripts/` used, and it is wrong here for two
reasons: the depth is a magic number that breaks the moment a module moves into a
subpackage, and it resolves to site-packages if the project is ever installed
non-editable. Anchoring on a marker file fixes both -- the search finds the repo
wherever the module sits, and finds *nothing* rather than something plausible if
there is no repo above it.

Resolution order, most explicit first:

1. an explicit path, passed by the caller -- how tests point at a fixture root
2. `$URBANDOCS_ROOT`, for a deploy that puts the data somewhere unusual
3. an upward search for `pyproject.toml`, the repo's marker
"""

from __future__ import annotations

import os
from pathlib import Path

#: Marker that identifies the repo root. `.git` is deliberately not used as well:
#: it is absent from a deployed checkout made by `git archive` or a release
#: tarball, and a marker that disappears in production is worse than no marker.
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
