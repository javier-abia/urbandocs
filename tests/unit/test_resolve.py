"""`get_by_cite`: resolve a printed cite to every candidate address (#61).

A resolver, never a getter -- these tests assert addresses (id, doc, page,
ancestor chain) come back, never legal text, and that an ambiguous cite
returns every candidate rather than a pick.
"""

from __future__ import annotations

import pytest

from urbandocs.resolve import get_by_cite
from urbandocs.substrate import load_substrate


@pytest.fixture(scope="module")
def substrate(fixture_dir):
    return load_substrate(corpus_path=fixture_dir / "corpus.tsv")


# --------------------------------------------------------------------------- #
# a unique cite: one candidate, and it is an address, not text
# --------------------------------------------------------------------------- #


def test_a_unique_cite_resolves_to_one_candidate(substrate):
    (candidate,) = get_by_cite("1.2", substrate)
    assert candidate.id == "SUA:p31:1.2"
    assert candidate.doc == "SUA"
    assert candidate.page == 31
    assert candidate.ancestors == [
        "Sección SUA 2 Seguridad frente al riesgo de impacto o de atrapamiento",
        "1 Impacto",
    ]


def test_a_candidate_carries_no_legal_text(substrate):
    """`CiteCandidate` has no `text` field at all -- an address, never a
    record (#61's own framing)."""
    (candidate,) = get_by_cite("1.2", substrate)
    assert not hasattr(candidate, "text")


def test_a_top_level_cite_has_no_ancestors(substrate):
    (candidate,) = get_by_cite("Anejo B", substrate)
    assert candidate.id == "SUA:p74:anejoB"
    assert candidate.ancestors == []


# --------------------------------------------------------------------------- #
# ambiguity: every candidate comes back, never a pick
# --------------------------------------------------------------------------- #


def test_an_ambiguous_cite_returns_every_candidate(substrate):
    """`a)` is printed under every article in D128 (#18) -- the corpus's own
    ambiguity, not something this function may resolve by picking one."""
    candidates = get_by_cite("a)", substrate)
    ids = {c.id for c in candidates}
    assert ids == {
        "SUA:p76:B.1.1.1.3.2.a",
        "SUA:p76:B.1.1.2.1.a",
        "D128:p25:A.3.2.1.a",
        "D128:p32:A.4.2.1.a",
        "D128:p32:A.4.2.1~2.a",
        "D128:p32:A.4.2.1~3.a",
    }


def test_a_bare_cite_resolves_to_several_documents(substrate):
    candidates = get_by_cite("B.1", substrate)
    assert {(c.id, c.doc) for c in candidates} == {
        ("SUA:p74:B.1", "SUA"),
        ("D128:p32:B.1", "D128"),
    }


# --------------------------------------------------------------------------- #
# doc: a filter, not a disambiguator
# --------------------------------------------------------------------------- #


def test_doc_filters_a_cross_document_collision_down_to_one(substrate):
    (candidate,) = get_by_cite("B.1", substrate, doc="D128")
    assert candidate.id == "D128:p32:B.1"


def test_doc_does_not_collapse_an_ambiguity_inside_one_document(substrate):
    """`a)` collides four times within D128 alone -- filtering to D128 must
    not silently pick one (#61's own acceptance criterion)."""
    candidates = get_by_cite("a)", substrate, doc="D128")
    assert {c.id for c in candidates} == {
        "D128:p25:A.3.2.1.a",
        "D128:p32:A.4.2.1.a",
        "D128:p32:A.4.2.1~2.a",
        "D128:p32:A.4.2.1~3.a",
    }
    assert all(c.doc == "D128" for c in candidates)


def test_doc_filtering_to_a_document_with_no_match_returns_empty(substrate):
    assert get_by_cite("Anejo B", substrate, doc="D128") == []


# --------------------------------------------------------------------------- #
# absence: empty, never an error
# --------------------------------------------------------------------------- #


def test_a_cite_absent_from_the_corpus_returns_empty(substrate):
    assert get_by_cite("no-such-cite", substrate) == []


def test_an_empty_cite_string_returns_empty_not_every_uncited_record(substrate):
    """A record with no cite is unreachable by this operation -- that is not
    an error, but it must also not mean an empty query matches all of them."""
    assert get_by_cite("", substrate) == []
