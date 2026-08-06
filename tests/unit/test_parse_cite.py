"""`parse_cite` classifies a heading, which is what drives the spine.

The `num`/`ns` split is the whole nesting model: `num` nests by dotted prefix,
`ns` opens a fresh numbering space at a rank. Getting the kind wrong reparents a
provision, and a reparented provision is a wrong ancestor chain in a citation --
the one thing the engine promises to get right.
"""

from urbandocs.ingest import parse_cite


def test_dotted_numbering_is_num_with_no_rank():
    # `num` nests by prefix, so it carries no rank of its own.
    assert parse_cite("B.2.6") == ("B.2.6", "num", None)
    assert parse_cite("4.2.1") == ("4.2.1", "num", None)


def test_namespace_headings_carry_a_rank():
    # `Anejo` and `Sección` open a namespace at the outer rank; `Artículo` sits
    # inside one, so it ranks lower (higher number = deeper).
    assert parse_cite("Anejo A") == ("Anejo A", "ns", 1)
    assert parse_cite("Sección SUA 1") == ("Sección SUA 1", "ns", 1)
    assert parse_cite("Artículo 14") == ("Artículo 14", "ns", 2)


def test_articulo_nests_inside_seccion():
    _, _, seccion = parse_cite("Sección SUA 1")
    _, _, articulo = parse_cite("Artículo 14")
    assert seccion is not None and articulo is not None, "both are namespaces"
    assert articulo > seccion, "Artículo must nest inside Sección"


def test_non_heading_returns_the_empty_triple():
    # Body text must be rejected wholesale: a false positive here promotes a
    # sentence to a heading and reparents everything after it.
    assert parse_cite("not a heading") == (None, None, None)
    assert parse_cite("") == (None, None, None)


def test_surrounding_whitespace_is_stripped_from_the_printed_cite():
    assert parse_cite("  Artículo 3  ") == ("Artículo 3", "ns", 2)
