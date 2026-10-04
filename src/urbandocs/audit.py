"""Server-side audit log: every operation's re-runnable invocation beside a
digest of its result (#65).

Each call appends one JSON line to `paths.audit_log()`:

    {"ts": ..., "substrate_sha256": ..., "invocation": "uv run -m urbandocs.cli
     search anch puert", "result_sha256": ...}

Re-running `invocation` against a substrate with the same digest prints the
exact bytes `result_sha256` was taken over, so `... | sha256sum` checks it. A
call that raised logs `error` in place of `result_sha256`.

Nothing here crosses the wire: the tool's return value is passed through
untouched (#7).
"""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

#: How the owner re-runs a logged call; `urbandocs.cli` parses what follows.
PROG = ["uv", "run", "-m", "urbandocs.cli"]


def _positionals(values: Sequence[str]) -> list[str]:
    """Positionals, behind `--` when one would otherwise parse as an option."""
    if any(v.startswith("-") for v in values):
        return ["--", *values]
    return list(values)


def search_argv(terms: Sequence[str]) -> list[str]:
    return ["search", *_positionals(terms)]


def get_argv(ids: Sequence[str]) -> list[str]:
    return ["get", *_positionals(ids)]


def get_by_cite_argv(cite: str, doc: str | None) -> list[str]:
    options = [] if doc is None else ["--doc", doc]
    return ["get-by-cite", *options, *_positionals([cite])]


def get_page_argv(doc: str, page: int) -> list[str]:
    return ["get-page", *_positionals([doc, str(page)])]


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def render(result: object) -> bytes:
    """The bytes the CLI prints for `result`, and the ones the log digests."""
    text = json.dumps(_jsonable(result), ensure_ascii=False, separators=(",", ":"))
    return (text + "\n").encode()


def substrate_sha256(corpus_path: Path) -> str:
    """Digest of `corpus.tsv` and its provenance sidecar: what a call ran over."""
    h = hashlib.sha256()
    for path in (corpus_path, corpus_path.with_name("corpus.provenance.tsv")):
        h.update(path.read_bytes())
    return h.hexdigest()


@dataclass(frozen=True)
class AuditLog:
    path: Path
    substrate_sha256: str

    def record[T](self, argv: list[str], call: Callable[[], T]) -> T:
        """Run `call`, log it under `argv`, and return its result unchanged."""
        try:
            result = call()
        except Exception as exc:
            self._write(argv, error=f"{type(exc).__name__}: {exc}")
            raise
        self._write(argv, result_sha256=hashlib.sha256(render(result)).hexdigest())
        return result

    def _write(self, argv: list[str], **outcome: str) -> None:
        line = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "substrate_sha256": self.substrate_sha256,
            "invocation": shlex.join([*PROG, *argv]),
            **outcome,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
