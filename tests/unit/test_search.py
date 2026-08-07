"""`search`: the sweep and the ranking, as plain functions over the substrate.

Every recall assertion here names the ids it expects and asserts they are
present -- never that "some results came back" (#58). The failure this suite
exists to catch is the silent one: a sweep that returns zero rows and exits
clean, or a scope mistake that costs a slice of the real hits with no error
anywhere (#33 measured both, on the corpus this fixture stands in for).
"""

from __future__ import annotations

import pytest

from urbandocs.search import search
from urbandocs.substrate import load_substrate


@pytest.fixture(scope="module")
def substrate(fixture_dir):
    return load_substrate(corpus_path=fixture_dir / "corpus.tsv")


def ids(ranked):
    return [r.section_id for r in ranked]


# --------------------------------------------------------------------------- #
# the stem, #9's whole claim
# --------------------------------------------------------------------------- #


def test_stem_reaches_both_documents_where_a_full_word_reaches_only_one(substrate):
    """`instal` is this fixture's version of #9's `anch`: D128 prints only
    `instalarse`, SUA prints only `instalacion`/`instalaciones`/`instalados` --
    no form is shared, so only the stem reaches both documents' vocabulary.
    """
    stem = ids(search(["instal"], substrate))
    assert "D128:p31:A.4.2.1" in stem  # matched via `instalarse`, D128-only
    assert "SUA:p32:§9" in stem  # matched via `instalacion`, SUA-only
    assert {r.doc for r in search(["instal"], substrate)} == {"D128", "SUA"}

    # Either full word alone reaches exactly one document -- reproducing the
    # failure #9 named: scoping to the full word costs the other document
    # outright, with no error anywhere.
    assert {r.doc for r in search(["instalacion"], substrate)} == {"SUA"}
    assert {r.doc for r in search(["instalarse"], substrate)} == {"D128"}


# --------------------------------------------------------------------------- #
# literal terms, never regex
# --------------------------------------------------------------------------- #


def test_a_leading_regex_metacharacter_is_matched_literally_not_as_a_quantifier(
    substrate,
):
    """`*altura` is #56's own example. Unescaped, `\\b*altura` fails to compile
    -- `*` has nothing to repeat -- so this must not raise, and it must not
    silently fall back to the unescaped `altura` search either.
    """
    starred = search(["*altura"], substrate)
    assert starred == []  # no record's norm literally contains "*altura"
    assert ids(search(["altura"], substrate)) != ids(starred)


def test_an_unbalanced_paren_in_a_term_does_not_raise(substrate):
    """`Ley 5/2010` is #56's other example: agent-generated text that must read
    as a literal search, never a syntax error. An unmatched `(` is the shape
    that would otherwise raise `re.error: missing ), unterminated subpattern`.
    """
    assert search(["(informe"], substrate) == []


def test_case_and_accent_folding_matches_query_side_to_norm(substrate):
    """A term is normalized through the same function that produced `norm`
    (`normalize`'s own docstring makes this the contract), so a caller need not
    already have folded the case or the accents by hand."""
    assert ids(search(["ALTURA"], substrate)) == ids(search(["altura"], substrate))
    accented, plain = search(["condición"], substrate), search(["condicion"], substrate)
    assert ids(accented) == ids(plain)


# --------------------------------------------------------------------------- #
# norm, never text -- #33's measured 16% loss
# --------------------------------------------------------------------------- #


def test_the_sweep_matches_norm_where_text_would_miss(substrate):
    """`norm` folds every spelling of the unit to `m2` (`m²`, `m 2`, `m2`);
    `text` keeps what the page prints. A sweep scoped to `text` would find zero
    of these -- the exact defect #33 measured as a silent 16% loss on `altura`.
    """
    hits = search(["m2"], substrate)
    assert {r.section_id for r in hits} == {"D128:p21:A.2.2", "D128:p24:A.3.2.1"}
    child = substrate.by_id["D128:p25:A.3.2.1.d"]
    assert "m2" not in child["text"]  # the page prints "m²" -- not this literal
    assert "m2" in child["norm"]  # `norm` is what actually matched
    assert (
        child["id"]
        in next(r for r in hits if r.section_id == "D128:p24:A.3.2.1").matched_children
    )


# --------------------------------------------------------------------------- #
# ranking: distinct slots, never raw hit count
# --------------------------------------------------------------------------- #


def test_sections_rank_by_distinct_terms_matched_not_by_hit_count(substrate):
    """Three terms, two sections that match all three and two that match one --
    the two triple-matches must outrank the single-matches, and ids/scores/order
    are named rather than counted."""
    ranked = search(["ancho", "libre", "paso"], substrate)
    assert [(r.section_id, r.score) for r in ranked] == [
        ("D128:p21:A.2.2", 2),
        ("D128:p24:A.3.2.1", 2),
        ("SUA:p31:1.2", 1),
        ("SUA:p32:§13", 1),
    ]


def test_the_ranked_list_is_complete_and_untruncated(substrate):
    """No top-N: every section that matched anything comes back, named in full
    rather than sampled."""
    ranked = search(["condicion"], substrate)
    assert {r.section_id for r in ranked} == {
        "SUA:p31:1.2",
        "SUA:p32:§9",
        "SUA:p32:§13",
        "SUA:p32:§16",
        "SUA:p76:B.1.1.1.3",
        "D128:p21:A.2",
        "D128:p23:A.3",
        "D128:p31:A.4",
        "D128:p32:A.4.2.1~3.d",
        "D128:p32:B.1",
    }


def test_a_term_with_no_hits_returns_an_empty_list_not_an_error(substrate):
    assert search(["zzzznohitzzzz"], substrate) == []


# --------------------------------------------------------------------------- #
# the ranked entry's shape
# --------------------------------------------------------------------------- #


def test_each_entry_carries_score_doc_page_ancestors_id_and_matched_children(
    substrate,
):
    """The full shape #56 requires on every line: enough to judge relevance and
    to know exactly which children to `get`, without a round trip."""
    (entry,) = [
        r for r in search(["ancho"], substrate) if r.section_id == "D128:p21:A.2.2"
    ]
    assert entry.score == 1
    assert entry.doc == "D128"
    assert entry.page == 21
    assert entry.ancestors == ["A.2. Condiciones funcionales."]
    assert entry.section_id == "D128:p21:A.2.2"
    assert entry.matched_children == [
        "D128:p22:§4",
        "D128:p22:§8",
        "D128:p22:A.2.2.e",
    ]


def test_a_section_matching_through_its_own_text_carries_no_matched_children(
    substrate,
):
    """A top-level heading with no parent_id is its own section when it matches
    directly -- nothing is subordinate to it in this sweep, so its matched
    children are empty rather than inherited from anywhere."""
    (entry,) = [
        r for r in search(["condicion"], substrate) if r.section_id == "D128:p21:A.2"
    ]
    assert entry.matched_children == []
    assert entry.ancestors == []  # A.2 has no parent_id of its own
