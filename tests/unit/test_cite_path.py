"""`cite_path` turns a printed cite into the slug that goes inside an id.

The distinction it encodes is load-bearing and easy to erode: `cite` keeps what
the page prints, `id` keeps what is addressable. A change that made ids carry the
printed punctuation would not break any rebuild -- the corpus would still have
4,924-odd rows and every band in `check_corpus` would still pass -- it would just
quietly change every id in every citation the engine emits. That is what these
asserts are here to catch.
"""

from urbandocs.ingest import cite_path


def test_trailing_punctuation_is_dropped():
    # The comment in cite_path states the rule: `art14.1.a` reads as an id,
    # `art14.1.a)` reads as a typo. The closing paren is part of the printed
    # cite and never part of the address.
    assert cite_path("Artículo 14.1.a)") == "art14.1.a"
    assert cite_path("1.") == "1"


def test_named_prefixes_are_abbreviated():
    assert cite_path("Artículo 14") == "art14"
    assert cite_path("Anejo A") == "anejoA"
    assert cite_path("Sección SUA 1") == "secSUA1"
    assert cite_path("Capítulo II") == "capII"
    assert cite_path("Título 1") == "tit1"


def test_accents_are_folded_but_case_is_kept():
    # Accents are stripped so an id is typeable; case is *not* folded, because
    # `anejoA` and `secSUA1` rely on it to stay readable.
    assert cite_path("Artículo 14") == "art14"
    assert "í" not in cite_path("Título 1")
    assert cite_path("Anejo A").endswith("A")


def test_bare_dotted_numbering_passes_through():
    # No prefix to abbreviate and no punctuation to strip: the cite is already
    # the address.
    assert cite_path("B.2.6") == "B.2.6"
    assert cite_path("A.2.2") == "A.2.2"


def test_internal_whitespace_is_removed():
    assert " " not in cite_path("Sección SUA 1")
