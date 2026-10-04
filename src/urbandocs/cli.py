"""Run one engine operation from the shell, printing what the MCP tool returns
(#65).

    uv run -m urbandocs.cli search anch puert
    uv run -m urbandocs.cli get 'D128:p21:A.2.2'
    uv run -m urbandocs.cli get-by-cite --doc D128 B.1
    uv run -m urbandocs.cli get-page SUA 76

The audit log's `invocation` column is a line of exactly this shape. Output is
`audit.render`'s compact JSON, so piping it to `sha256sum` checks a logged
`result_sha256`; pipe to `jq` to read it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from urbandocs.audit import render
from urbandocs.read import UnknownPageError, get, get_page
from urbandocs.resolve import get_by_cite
from urbandocs.server import wire_search
from urbandocs.substrate import load_substrate

if TYPE_CHECKING:
    from collections.abc import Sequence

    from urbandocs.substrate import Substrate


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="urbandocs.cli", description=__doc__)
    ap.add_argument("--corpus", type=Path, help="corpus.tsv to read (default: repo's)")
    sub = ap.add_subparsers(dest="op", required=True)
    sub.add_parser("search").add_argument("terms", nargs="*")
    sub.add_parser("get").add_argument("ids", nargs="*")
    cite = sub.add_parser("get-by-cite")
    cite.add_argument("--doc")
    cite.add_argument("cite")
    page = sub.add_parser("get-page")
    page.add_argument("doc")
    page.add_argument("page", type=int)
    return ap


def run(args: argparse.Namespace, substrate: Substrate) -> object:
    """Dispatch to the same function the matching MCP tool calls."""
    match args.op:
        case "search":
            return wire_search(args.terms, substrate)
        case "get":
            return get(args.ids, substrate)
        case "get-by-cite":
            return get_by_cite(args.cite, substrate, args.doc)
        case "get-page":
            return get_page(args.doc, args.page, substrate)
        case _:
            raise AssertionError(args.op)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    substrate = load_substrate(corpus_path=args.corpus)
    try:
        result = run(args, substrate)
    except UnknownPageError as exc:
        print(f"UnknownPageError: {exc}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
