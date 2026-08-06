"""AGENTS.md's two commit conventions, actually enforced (#51)."""

import pytest

from urbandocs import check_commit_msg as ccm


@pytest.mark.parametrize(
    "subject",
    [
        "feat: land pre-commit with the fast hooks and the secret scan (#50) (#70)",
        "fix: document the invocation that works, and make the tools say it "
        "(#66) (#67)",
        "chore: flag docling output versioning as a follow-up in ingest",
        "docs: settle cross-document coverage as a retrieval guarantee (#9) (#35)",
        "refactor(paths): anchor on pyproject.toml instead of parents[N]",
        "feat!: drop the OCR pipeline",
    ],
)
def test_real_and_scoped_subjects_pass(subject):
    assert ccm.check(subject) == []


@pytest.mark.parametrize(
    "subject",
    [
        "Add GNU General Public License v3",
        "Simplify CLAUDE.md to just reference AGENTS.md",
        "Update ingest.py",
        "FEAT: wrong case",
        "feat : space before colon",
        "feature: not a real type",
    ],
)
def test_non_conventional_subjects_are_rejected(subject):
    violations = ccm.check(subject)
    assert len(violations) == 1
    assert "not Conventional Commits" in violations[0]


def test_merge_commit_is_exempt_from_the_type_prefix():
    assert ccm.check("Merge branch 'feature/x' into main") == []
    assert ccm.check("Merge pull request #12 from owner/branch") == []


def test_revert_commit_is_exempt_from_the_type_prefix():
    message = 'Revert "feat: land the thing (#12)"\n\nThis reverts commit abc123.\n'
    assert ccm.check(message) == []


def test_comment_and_blank_lines_are_skipped_to_find_the_subject():
    message = (
        "\n# blank/comment lines git leaves in COMMIT_EDITMSG\nfeat: a real subject\n"
    )
    assert ccm.check(message) == []


def test_empty_message_has_no_subject_violation():
    # git's own hooks reject an empty message before this one ever sees it;
    # this check should not pile on with a confusing second failure.
    assert ccm.check("\n# only comments\n") == []


@pytest.mark.parametrize(
    "trailer",
    [
        "Co-Authored-By: Claude <noreply@anthropic.com>",
        "co-authored-by: claude sonnet 5 <noreply@anthropic.com>",
        "Co-authored-by: GitHub Copilot <copilot@github.com>",
    ],
)
def test_ai_co_author_trailer_is_rejected(trailer):
    message = f"feat: add a thing\n\n{trailer}\n"
    violations = ccm.check(message)
    assert any("Co-authored-by" in v for v in violations)


def test_generated_with_line_is_rejected():
    message = (
        "feat: add a thing\n\n🤖 Generated with [Claude Code](https://claude.com)\n"
    )
    violations = ccm.check(message)
    assert any("Generated with" in v for v in violations)
    assert any("attribution marker" in v for v in violations)


def test_ai_trailer_is_rejected_even_on_an_otherwise_exempt_merge_commit():
    message = "Merge branch 'x'\n\nCo-authored-by: Claude <noreply@anthropic.com>\n"
    violations = ccm.check(message)
    assert violations
    assert all("not Conventional Commits" not in v for v in violations)


def test_human_co_author_is_not_flagged():
    message = "feat: pair on the thing\n\nCo-authored-by: Jane Doe <jane@example.com>\n"
    assert ccm.check(message) == []
