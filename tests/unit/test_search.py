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

    Every call here pairs the term under test with a second term local to the
    same record ("cocina" for the D128 side, "puerta" for the SUA side) so the
    section under test clears the #102 score floor -- the pairing changes
    nothing about which document the first term alone would have reached.
    """
    stem = ids(search(["instal", "cocina", "puerta"], substrate))
    assert "D128:p31:A.4.2.1" in stem  # matched via `instalarse`, D128-only
    assert "SUA:p32:§9" in stem  # matched via `instalacion`, SUA-only
    assert {r.doc for r in search(["instal", "cocina", "puerta"], substrate)} == {
        "D128",
        "SUA",
    }

    # Either full word alone reaches exactly one document -- reproducing the
    # failure #9 named: scoping to the full word costs the other document
    # outright, with no error anywhere.
    assert {r.doc for r in search(["instalacion", "puerta"], substrate)} == {"SUA"}
    assert {r.doc for r in search(["instalarse", "cocina"], substrate)} == {"D128"}


# --------------------------------------------------------------------------- #
# literal terms, never regex
# --------------------------------------------------------------------------- #


def test_a_leading_regex_metacharacter_is_matched_literally_not_as_a_quantifier(
    substrate,
):
    """`*altura` is #56's own example. Unescaped, `\\b*altura` fails to compile
    -- `*` has nothing to repeat -- so this must not raise, and it must not
    silently fall back to the unescaped `altura` search either.

    Paired with "puerta" (co-occurring with "altura" in the same record) so
    the real term's hit clears the #102 score floor; "*altura" never matches
    anything, so pairing it with anything still floors out to `[]`.
    """
    starred = search(["*altura", "puerta"], substrate)
    assert starred == []  # no record's norm literally contains "*altura"
    assert ids(search(["altura", "puerta"], substrate)) != ids(starred)


def test_an_unbalanced_paren_in_a_term_does_not_raise(substrate):
    """`Ley 5/2010` is #56's other example: agent-generated text that must read
    as a literal search, never a syntax error. An unmatched `(` is the shape
    that would otherwise raise `re.error: missing ), unterminated subpattern`.
    """
    assert search(["(informe"], substrate) == []


def test_case_and_accent_folding_matches_query_side_to_norm(substrate):
    """A term is normalized through the same function that produced `norm`
    (`normalize`'s own docstring makes this the contract), so a caller need not
    already have folded the case or the accents by hand.

    Each casing/accent variant is paired with "puerta" so the sections under
    test clear the #102 score floor.
    """
    assert ids(search(["ALTURA", "puerta"], substrate)) == ids(
        search(["altura", "puerta"], substrate)
    )
    accented = search(["condición", "puerta"], substrate)
    plain = search(["condicion", "puerta"], substrate)
    assert ids(accented) == ids(plain)


# --------------------------------------------------------------------------- #
# norm, never text -- #33's measured 16% loss
# --------------------------------------------------------------------------- #


def test_the_sweep_matches_norm_where_text_would_miss(substrate):
    """`norm` folds every spelling of the unit to `m2` (`m²`, `m 2`, `m2`);
    `text` keeps what the page prints. A sweep scoped to `text` would find zero
    of these -- the exact defect #33 measured as a silent 16% loss on `altura`.

    Paired with "cocina" (co-occurring with "m2" in the same records) so both
    target sections clear the #102 score floor.
    """
    hits = search(["m2", "cocina"], substrate)
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
    are named rather than counted.

    The two single-matches (`SUA:p31:1.2`, `SUA:p32:§13`, score 1 each) are
    exactly the #102 floor's target: present in an unfiltered sweep, absent
    from what `search` actually returns.
    """
    ranked = search(["ancho", "libre", "paso"], substrate)
    assert [(r.section_id, r.score) for r in ranked] == [
        ("D128:p21:A.2.2", 2),
        ("D128:p24:A.3.2.1", 2),
    ]


def test_the_ranked_list_is_complete_and_untruncated(substrate):
    """No rank-based top-N: every section clearing the #102 score floor comes
    back, named in full rather than sampled -- floored sections are excluded
    by score, never by a position cutoff among the survivors."""
    ranked = search(["condicion", "puerta", "altura", "instal"], substrate)
    assert {r.section_id for r in ranked} == {
        "SUA:p31:1.2",
        "SUA:p32:§9",
        "SUA:p32:§13",
        "SUA:p32:§16",
        "SUA:p76:B.1.1.1.3",
        "SUA:p76:B.1.1.1.3.2",
    }
    assert all(r.score >= 2 for r in ranked)


def test_a_term_with_no_hits_returns_an_empty_list_not_an_error(substrate):
    assert search(["zzzznohitzzzz"], substrate) == []


# --------------------------------------------------------------------------- #
# the #102 score floor: score == 1 dropped, score >= 2 kept
# --------------------------------------------------------------------------- #


def test_a_single_term_search_never_returns_anything(substrate):
    """No section can score above 1 against one term, and score 1 is floored
    out -- so a single-term search is always `[]`, matches or not."""
    assert search(["condicion"], substrate) == []


def test_a_section_matching_exactly_one_term_is_excluded(substrate):
    """`cocina` alone matches four D128 sections (score 1 each); none of them
    come back."""
    cocina_only_sections = {
        "D128:p21:A.2.2",
        "D128:p24:A.3.2.1",
        "D128:p31:A.4.2",
        "D128:p31:A.4.2.1",
    }
    ranked = search(["cocina", "puerta"], substrate)  # "puerta" never matches D128
    assert cocina_only_sections.isdisjoint({r.section_id for r in ranked})
    assert ranked == []


def test_a_section_matching_two_or_more_terms_is_included_at_its_ordinary_rank(
    substrate,
):
    """The same section, once a second term gives it a second matched slot,
    is included and ranks by that score like any other."""
    ranked = search(["cocina", "m2"], substrate)
    assert ("D128:p21:A.2.2", 2) in [(r.section_id, r.score) for r in ranked]
    assert all(r.score >= 2 for r in ranked)


# --------------------------------------------------------------------------- #
# the ranked entry's shape
# --------------------------------------------------------------------------- #


def test_each_entry_carries_score_doc_page_ancestors_id_and_matched_children(
    substrate,
):
    """The full shape #56 requires on every line: enough to judge relevance and
    to know exactly which children to `get`, without a round trip.

    Paired with "minimo" (present in the same three children as "ancho") so
    the section clears the #102 score floor; the matched children are the
    same three either way."""
    (entry,) = [
        r
        for r in search(["ancho", "minimo"], substrate)
        if r.section_id == "D128:p21:A.2.2"
    ]
    assert entry.score == 2
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
    children are empty rather than inherited from anywhere.

    Paired with "funcional" (also in the heading's own text, "Condiciones
    funcionales") so the section clears the #102 score floor."""
    (entry,) = [
        r
        for r in search(["condicion", "funcional"], substrate)
        if r.section_id == "D128:p21:A.2"
    ]
    assert entry.matched_children == []
    assert entry.ancestors == []  # A.2 has no parent_id of its own
