"""`get`: verbatim text plus the ancestor chain and direct children (#60).

A rule returned without its qualifier is not 80% correct; it is incorrect
(#60's own framing) -- so these tests name the exact ancestor and child ids
expected, never assert "some context came back".
"""

from __future__ import annotations

import pytest

from urbandocs.read import UnknownPageError, get, get_page
from urbandocs.substrate import load_substrate


@pytest.fixture(scope="module")
def substrate(fixture_dir):
    return load_substrate(corpus_path=fixture_dir / "corpus.tsv")


# --------------------------------------------------------------------------- #
# the ancestor chain: complete to the root, heading text only
# --------------------------------------------------------------------------- #


def test_ancestor_chain_is_complete_to_the_root_root_first(substrate):
    """`SUA:p76:B.1.1.1.3.2.a.i` is the fixture's deepest chain (7, per the
    fixture README) -- walking it must not stop early and must not reverse."""
    (record,) = get(["SUA:p76:B.1.1.1.3.2.a.i"], substrate).records
    assert record.ancestors == [
        "Anejo B Características de las instalaciones de protección frente al rayo",
        "B.1 Sistema externo",
        "B.1.1 Diseño de la instalación de dispositivos captadores",
        "B.1.1.1 Volumen protegido mediante puntas Franklin y mallas conductoras",
        "B.1.1.1.3 Método de la malla",
        "2 Las condiciones para que la protección sea efectiva son las siguientes:",
        "los conductores captadores situados en la cubierta deben estar colocados en:",
    ]


def test_a_top_level_record_has_no_ancestors(substrate):
    (record,) = get(["SUA:p74:anejoB"], substrate).records
    assert record.ancestors == []


# --------------------------------------------------------------------------- #
# children: direct only, no grandchildren, no leaking into an ancestor
# --------------------------------------------------------------------------- #


def test_direct_children_arrive_and_grandchildren_do_not(substrate):
    """`D128:p21:A.2` has one direct child, `A.2.2`, which itself has ~20
    children of its own -- none of *those* may appear here."""
    (record,) = get(["D128:p21:A.2"], substrate).records
    assert [child.id for child in record.children] == ["D128:p21:A.2.2"]


def test_a_parents_other_children_do_not_arrive_alongside_the_parent(substrate):
    """`A.2.2.e` is one of ~20 children of `A.2.2`. Asking for `A.2.2.e`
    itself must not pull its siblings in as if they were its own children --
    it has none of its own in this fixture."""
    (record,) = get(["D128:p22:A.2.2.e"], substrate).records
    assert record.children == []
    assert record.ancestors == [
        "A.2. Condiciones funcionales.",
        "A.2.2. Composición y compartimentación.",
    ]


def test_children_carry_verbatim_text_not_a_paraphrase(substrate):
    (record,) = get(["D128:p21:A.2.2"], substrate).records
    child = next(c for c in record.children if c.id == "D128:p22:A.2.2.e")
    assert child.text == substrate.by_id["D128:p22:A.2.2.e"]["text"]


# --------------------------------------------------------------------------- #
# match vs context, and the citation shape
# --------------------------------------------------------------------------- #


def test_every_record_carries_doc_page_chain_and_id(substrate):
    (record,) = get(["D128:p21:A.2.2"], substrate).records
    assert record.id == "D128:p21:A.2.2"
    assert record.doc == "D128"
    assert record.page == 21
    assert record.ancestors == ["A.2. Condiciones funcionales."]


def test_the_records_own_text_is_verbatim_not_a_paraphrase(substrate):
    (record,) = get(["D128:p21:A.2.2"], substrate).records
    assert record.text == substrate.by_id["D128:p21:A.2.2"]["text"]


def test_match_and_context_are_distinguishable(substrate):
    """The record's own text is the match; `ancestors` and `children` are
    context -- separate fields, not a mix an agent has to sort out."""
    (record,) = get(["D128:p21:A.2.2"], substrate).records
    assert record.text not in record.ancestors
    assert record.text not in [child.text for child in record.children]


# --------------------------------------------------------------------------- #
# batching: several ids, an unknown id, an oversized batch
# --------------------------------------------------------------------------- #


def test_several_ids_in_one_call_return_several_records(substrate):
    response = get(["D128:p21:A.2", "D128:p21:A.2.2", "SUA:p74:anejoB"], substrate)
    assert [r.id for r in response.records] == [
        "D128:p21:A.2",
        "D128:p21:A.2.2",
        "SUA:p74:anejoB",
    ]
    assert response.unknown_ids == []


def test_an_unknown_id_is_reported_and_the_rest_of_the_batch_still_returns(substrate):
    response = get(["D128:p21:A.2", "HAB:p20:art14.1.a", "SUA:p74:anejoB"], substrate)
    assert [r.id for r in response.records] == ["D128:p21:A.2", "SUA:p74:anejoB"]
    assert response.unknown_ids == ["HAB:p20:art14.1.a"]


def test_a_void_id_never_resolves_to_a_different_record(substrate):
    """#56's own example: `HAB` stays dead. A stale `HAB:p20:art14.1.a` must
    fail loudly as unknown rather than land on whatever id happens to be
    lexically near it."""
    response = get(["HAB:p20:art14.1.a"], substrate)
    assert response.records == []
    assert response.unknown_ids == ["HAB:p20:art14.1.a"]


def test_an_oversized_batch_is_disclosed_never_truncated_never_refused(substrate):
    """Every known id in the fixture, requested in one call -- nothing here
    caps the batch, so the response is exactly as long as the request."""
    all_ids = [record["id"] for record in substrate.records]
    response = get(all_ids, substrate)
    assert [r.id for r in response.records] == all_ids
    assert response.unknown_ids == []


# --------------------------------------------------------------------------- #
# `get_page`: every record on one page, in bbox reading order (#62)
# --------------------------------------------------------------------------- #


def test_records_come_back_in_bbox_order_not_id_order(substrate):
    """`SUA` p.76's ids interleave `B.n.n` headings with positional `§n`
    markers -- sorted by id, `§1` would land before `B.1.1.1.3.1` and after
    `B.1.1.1.3`, not where it actually sits on the page. This is the fixture's
    reading order (its README), not a lexical one -- any implementation that
    re-sorts the ids fails this."""
    records = get_page("SUA", 76, substrate)
    assert [r.id for r in records] == [
        "SUA:p76:B.1.1.1.3",
        "SUA:p76:B.1.1.1.3.1",
        "SUA:p76:§1",
        "SUA:p76:§2",
        "SUA:p76:B.1.1.1.3.2",
        "SUA:p76:B.1.1.1.3.2.a",
        "SUA:p76:B.1.1.1.3.2.a.i",
        "SUA:p76:§3",
        "SUA:p76:§4",
        "SUA:p76:B.1.1.1.3.2.b",
        "SUA:p76:B.1.1.1.3.2.c",
        "SUA:p76:B.1.1.1.3.3",
        "SUA:p76:B.1.1.2",
        "SUA:p76:B.1.1.2.1",
        "SUA:p76:B.1.1.2.1.a",
        "SUA:p76:§5",
        "SUA:p76:§6",
        "SUA:p76:§7",
        "SUA:p76:§8",
        "SUA:p76:§9",
        "SUA:p76:§10",
        "SUA:p76:B.1.1.2.1.b",
    ]


def test_every_record_carries_its_id_and_label(substrate):
    """`DOG` p.1 mixes text, headings and picture placeholders -- `label` is
    what tells a picture's empty `text` apart from a record that lost its text
    some other way."""
    records = get_page("DOG", 1, substrate)
    assert [r.id for r in records] == [f"DOG:p1:§{n}" for n in range(1, 22)]
    pictures = [r for r in records if r.label == "picture"]
    assert [r.id for r in pictures] == ["DOG:p1:§1", "DOG:p1:§13", "DOG:p1:§14"]
    assert all(r.text == "" for r in pictures)


def test_a_page_with_no_records_returns_empty_not_an_error(substrate):
    """`SUA` p.2 is inside the document (1-79) but carries no record in this
    fixture -- absence, not a bad page number."""
    assert get_page("SUA", 2, substrate) == []


def test_a_page_number_past_the_documents_last_page_is_reported(substrate):
    """`SUA` runs 1-79 per the provenance sidecar; p.80 does not exist."""
    with pytest.raises(UnknownPageError):
        get_page("SUA", 80, substrate)


def test_page_zero_is_reported_not_treated_as_empty(substrate):
    with pytest.raises(UnknownPageError):
        get_page("SUA", 0, substrate)


def test_an_unknown_doc_is_reported(substrate):
    with pytest.raises(UnknownPageError):
        get_page("NOSUCHDOC", 1, substrate)
