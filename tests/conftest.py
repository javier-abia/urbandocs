"""Shared access to the committed fixture corpus.

The engine's unit tests read the fixture through these, never by building a path
of their own -- one place to change if the fixture moves, and no test that only
passes from the repo root.

Located relative to this file rather than through `urbandocs.paths` on purpose.
`paths` anchors on `pyproject.toml` because it is finding *repo* data that a
deployed checkout still has to locate (#46); the fixture is test data that always
sits beside the test importing it, so the shorter, cwd-independent path is the
honest one.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "corpus"


def read_tsv(path: Path) -> list[dict[str, str]]:
    """Read a corpus TSV the way the engine will: plain, unquoted, tab-delimited.

    `csv.QUOTE_NONE` is not incidental -- `ingest.write_tsv` writes no quoting and
    no escaping so that `cut` and `awk -F'\\t'` work on the substrate (#33). A
    reader that honoured quotes would silently disagree with the writer on any
    record whose text opens with `"`.
    """
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def corpus_rows() -> list[dict[str, str]]:
    """The 121-record excerpt. See `tests/fixtures/corpus/README.md` for its shape."""
    return read_tsv(FIXTURE_DIR / "corpus.tsv")


@pytest.fixture(scope="session")
def provenance_rows() -> list[dict[str, str]]:
    """The fidelity sidecar #27's disclosure derives from."""
    return read_tsv(FIXTURE_DIR / "corpus.provenance.tsv")


@pytest.fixture(scope="session")
def mixed_provenance_rows() -> list[dict[str, str]]:
    """A provenance sidecar that still has an `ocr` range. See its README."""
    return read_tsv(
        Path(__file__).resolve().parent
        / "fixtures"
        / "provenance-mixed"
        / "corpus.provenance.tsv"
    )
