"""Enforce AGENTS.md's two commit-message conventions (#51, map #45).

Both existed only in prose -- Conventional Commits, and no AI attribution
trailers -- and neither had ever been checked by anything, which made this
the one convention in the repo with an actual enforcement gap (map #45's
notes). Unlike the *fixing* hooks in `.pre-commit-config.yaml`, this one only
rejects: a malformed subject line or a trailer naming an assistant can't be
safely rewritten, so `commit-msg` has nothing to do but say what's wrong and
let the author -- human or agent -- fix it and retry.

Merge and revert commits are exempt from the type-prefix check: git writes
both in its own fixed forms ("Merge branch 'x'...", 'Revert "y"') that the
author doesn't compose. The AI-trailer check still applies to every commit,
merges included -- there's no form of merge commit that legitimately carries
one.

Usage (wired as the `commit-msg` hook in `.pre-commit-config.yaml`; `$1` is
the path git passes every commit-msg hook):

    uv run -m urbandocs.check_commit_msg .git/COMMIT_EDITMSG
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# Conventional Commits' own type list. AGENTS.md names five by example
# ("feat:", "fix:", "docs:", "chore:", "refactor:", "etc.") -- the rest are
# the spec's, not an invention of this hook.
TYPES = [
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
]

# `type(scope)?!: description`. Scope is free-form and optional -- no commit
# in this repo has used one yet, so nothing here constrains its shape. `!`
# marks a breaking change per the spec.
SUBJECT_RE = re.compile(r"^(?P<type>" + "|".join(TYPES) + r")(\([^)]+\))?!?: .+")

# git writes both of these itself, in a form the author doesn't choose.
MERGE_RE = re.compile(r"^Merge (branch|pull request) ")
REVERT_RE = re.compile(r'^Revert "')

# Assistant names/tools seen in `Co-authored-by` trailers or "Generated
# with" lines, matched case-insensitively. Not just "claude": AGENTS.md's
# rule is no AI attribution, not no Anthropic attribution.
AI_NAMES = r"(claude|anthropic|copilot|chatgpt|gpt-|openai|codex|cursor|gemini)"

AI_TRAILER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(rf"^\s*co-authored-by:.*{AI_NAMES}", re.IGNORECASE | re.MULTILINE),
        "Co-authored-by trailer names an AI assistant",
    ),
    (
        re.compile(r"generated\s+with", re.IGNORECASE),
        '"Generated with" attribution line',
    ),
    (
        re.compile(r"🤖"),
        "🤖 attribution marker",
    ),
]


def subject_line(message: str) -> str:
    """The first non-blank, non-comment line -- git's own definition of the subject."""
    for line in message.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def check(message: str) -> list[str]:
    """Return the violations in `message`; empty means it's clean."""
    violations: list[str] = []

    subject = subject_line(message)
    if subject and not (
        SUBJECT_RE.match(subject) or MERGE_RE.match(subject) or REVERT_RE.match(subject)
    ):
        violations.append(
            f"subject line is not Conventional Commits: {subject!r}\n"
            f"    expected `<type>: <description>`, type one of "
            f"{', '.join(TYPES)} (see AGENTS.md)"
        )

    for pattern, name in AI_TRAILER_PATTERNS:
        if pattern.search(message):
            violations.append(
                f"{name} -- AGENTS.md forbids AI attribution in commits; remove it"
            )

    return violations


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="uv run -m urbandocs.check_commit_msg",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "message_file", type=Path, help="path git passes to commit-msg hooks"
    )
    args = ap.parse_args(argv)

    message = args.message_file.read_text()
    violations = check(message)
    if not violations:
        return 0

    print(f"commit-msg: {args.message_file} fails AGENTS.md's commit conventions:\n")
    for v in violations:
        print(f"  - {v}")
    print(
        "\nFix the message and retry -- this is a rejecting check (unlike the "
        "pre-commit hooks, a bad message can't be rewritten for you)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
