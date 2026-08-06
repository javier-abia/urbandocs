"""The fixture corpus is a second corpus, and a second corpus can drift.

These are tests *of the fixture*, not of the engine -- the engine does not exist
yet (#49). They exist because the fixture's whole value is being the same shape as
the thing it stands in for: the moment it stops being that, every test written
against it is asserting something about a format `ingest` no longer emits, and
passing.

The drift that matters is format, not content. `--check` on
`tests/fixtures/make_fixture_corpus.py` catches content drift by re-deriving the
fixture from the docling JSON, but it needs the real documents to run, so it
belongs in the corpus job rather than here. These run on the committed bytes
alone.
"""

from __future__ import annotations

import csv

from urbandocs import ingest

PROVENANCE_COLUMNS = ["doc", "page_from", "page_to", "source"]


def test_header_is_ingests_columns(fixture_dir):
    """The one assertion that makes the fixture format-compatible by construction.

    Add a column to `ingest.COLUMNS` and this fails until the fixture is
    regenerated -- which is the correct order of events, because a test reading
    the new column off the old fixture would read an empty string and pass.
    """
    with (fixture_dir / "corpus.tsv").open() as fh:
        header = fh.readline().rstrip("\n").split("\t")
    assert header == ingest.COLUMNS


def test_provenance_header_matches_ingest(provenance_rows):
    assert list(provenance_rows[0]) == PROVENANCE_COLUMNS


def test_every_row_has_exactly_the_column_count(fixture_dir):
    """No ragged rows -- an unescaped tab in `text` would split a record in two.

    `write_tsv` strips tabs and newlines on the way in precisely because the
    format has no escaping (#33). This is that guarantee, asserted on the artifact
    rather than on the writer.
    """
    with (fixture_dir / "corpus.tsv").open() as fh:
        for n, line in enumerate(fh, start=1):
            assert line.endswith("\n"), f"line {n} has no terminator"
            assert len(line.rstrip("\n").split("\t")) == len(ingest.COLUMNS), \
                f"line {n} is ragged"


def test_no_field_contains_a_tab_or_newline(corpus_rows):
    for r in corpus_rows:
        for column, value in r.items():
            assert "\t" not in value and "\r" not in value, f"{r['id']}.{column}"


def test_a_quote_reader_would_disagree_with_the_writer(fixture_dir):
    """Guards the reader, not the file: `QUOTE_NONE` is part of the contract.

    If a record ever opens with `"`, a default `csv.reader` silently swallows it
    and glues fields together. Rather than wait for that record to appear, assert
    the two readings agree today -- so the day one does appear, this is the test
    that says which reader is right.
    """
    with (fixture_dir / "corpus.tsv").open(newline="") as fh:
        lenient = list(csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))
    with (fixture_dir / "corpus.tsv").open(newline="") as fh:
        default = list(csv.reader(fh, delimiter="\t"))
    assert lenient == default


# --------------------------------------------------------------------------- #
# integrity: what a consumer is allowed to assume
# --------------------------------------------------------------------------- #

def test_ids_are_unique(corpus_rows):
    ids = [r["id"] for r in corpus_rows]
    assert len(ids) == len(set(ids))


def test_every_parent_id_resolves(corpus_rows):
    """Ancestor closure. A chain that dead-ends is not a chain, and `get` promises
    the chain (#4, #8)."""
    ids = {r["id"] for r in corpus_rows}
    for r in corpus_rows:
        assert not r["parent_id"] or r["parent_id"] in ids, r["id"]


def test_no_parent_cycles(corpus_rows):
    by_id = {r["id"]: r for r in corpus_rows}
    for r in corpus_rows:
        seen, cur = {r["id"]}, r
        while cur["parent_id"]:
            assert cur["parent_id"] not in seen, f"cycle at {r['id']}"
            seen.add(cur["parent_id"])
            cur = by_id[cur["parent_id"]]


def test_no_record_parents_across_documents(corpus_rows):
    by_id = {r["id"]: r for r in corpus_rows}
    for r in corpus_rows:
        if r["parent_id"]:
            assert by_id[r["parent_id"]]["doc"] == r["doc"], r["id"]


def test_id_prefix_matches_the_documents_code(corpus_rows):
    """`HAB` is deliberately dead, so the code is not derivable -- it is looked up.

    A fixture record whose id said `DOG` while its `doc` said `dog-habitabilidad`
    would resolve to the wrong decree, which is the exact failure #41 renamed the
    code to prevent.
    """
    for r in corpus_rows:
        code = ingest.DOC_CODES[r["doc"]]
        assert r["id"].startswith(f"{code}:p{r['page']}:"), r["id"]


def test_every_records_page_falls_in_a_provenance_range(corpus_rows, provenance_rows):
    """#27 derives fidelity from `doc` + `page`, so a page outside every range has
    no answer at all -- worse than a wrong one, because nothing is disclosed."""
    ranges = [(p["doc"], int(p["page_from"]), int(p["page_to"]), p["source"])
              for p in provenance_rows]
    for r in corpus_rows:
        hits = [s for doc, a, b, s in ranges
                if doc == r["doc"] and a <= int(r["page"]) <= b]
        assert len(hits) == 1, f"{r['id']} matched {len(hits)} ranges"


def test_norm_is_what_normalize_produces(corpus_rows):
    """The fixture's `norm` must be `normalize(text)` and not a frozen old answer.

    `search` matches `norm` and normalizes the query with the same function, so the
    two sides only agree if this holds. It is also the cheapest way to notice that
    a change to `normalize` has orphaned the committed fixture.
    """
    for r in corpus_rows:
        assert r["norm"] == ingest.normalize(r["text"]), r["id"]


# --------------------------------------------------------------------------- #
# coverage: the shapes #49 requires, asserted on the artifact
# --------------------------------------------------------------------------- #

def test_covers_at_least_two_documents(corpus_rows):
    assert len({r["doc"] for r in corpus_rows}) >= 2


def test_has_a_deeply_nested_ancestor_chain(corpus_rows):
    by_id = {r["id"]: r for r in corpus_rows}

    def depth(r):
        d, cur = 0, r
        while cur["parent_id"]:
            cur, d = by_id[cur["parent_id"]], d + 1
        return d

    assert max(depth(r) for r in corpus_rows) >= 5


def test_has_a_cite_repeated_within_one_document(corpus_rows):
    """The ambiguity `get_by_cite` must handle. It is the source's, not the
    engine's: the decree prints `a)` under every article (#18)."""
    seen = {}
    for r in corpus_rows:
        if r["cite"]:
            seen.setdefault((r["doc"], r["cite"]), 0)
            seen[(r["doc"], r["cite"])] += 1
    assert any(n > 1 for n in seen.values())


def test_has_an_id_disambiguated_by_suffix(corpus_rows):
    """`~n` is what `make_id` appends when doc+page+cite is not unique -- the
    printed cite locates but does not identify (#4)."""
    assert any("~" in r["id"] for r in corpus_rows)


def test_has_a_record_with_no_cite(corpus_rows):
    """An empty `cite` is a fact about the source, not an extraction defect (#27):
    194 provisions corpus-wide print no recoverable marker."""
    assert any(not r["cite"] for r in corpus_rows)
    assert any(":§" in r["id"] for r in corpus_rows)


def test_has_a_table_serialized_with_row_separators(corpus_rows):
    tables = [r for r in corpus_rows if r["label"] == "table"]
    assert tables
    assert any(" ¶ " in r["text"] and " | " in r["text"] for r in tables)


def test_has_a_picture_record_and_a_caption(corpus_rows):
    """Figure *positions* are in scope, figure *content* is not (#3): a picture
    record carries no text, and the caption beside it is how the agent points at
    something it cannot read."""
    pictures = [r for r in corpus_rows if r["label"] == "picture"]
    assert pictures
    assert any(not r["text"] for r in pictures)
    assert any(r["label"] == "caption" for r in corpus_rows)


def test_has_a_record_whose_parent_is_on_an_earlier_page(corpus_rows):
    """The page-boundary case. A *record* never spans pages -- its page comes from
    a single `prov` entry -- so what crosses the boundary is the chain: a provision
    on p.76 hanging off a heading on p.74. `get` must climb across it."""
    by_id = {r["id"]: r for r in corpus_rows}
    assert any(r["parent_id"] and by_id[r["parent_id"]]["page"] != r["page"]
               for r in corpus_rows)


def test_unit_spellings_fold_together_in_norm(corpus_rows):
    """What survives of the OCR-damage requirement in #49.

    The `m?` repair is dead -- it only fires on an OCR'd page and #41 retired the
    OCR programme, so no record in the corpus carries `m?` any more. The
    *searchable* consequence is still real and still here: the page prints `m²`,
    docling also splits it as `m 2`, and `norm` collapses every spelling to `m2` so
    one query reaches all of them.
    """
    assert any("m²" in r["text"] and "m2" in r["norm"] for r in corpus_rows)
    assert ingest.normalize("30 m²") == ingest.normalize("30 m 2") == "30 m2"


def test_provenance_covers_both_fidelities_across_the_fixtures(provenance_rows,
                                                               mixed_provenance_rows):
    """The real corpus is all-native since #41, so the `ocr` branch of #27's
    disclosure is only reachable through the hand-written sidecar. Asserted
    together so deleting that fixture fails here rather than silently halving the
    disclosure's test coverage."""
    assert {r["source"] for r in provenance_rows} == {"native"}
    assert {r["source"] for r in mixed_provenance_rows} == {"native", "ocr"}


def test_the_generator_is_committed_beside_the_fixture(fixture_dir):
    """The fixture is frozen, not regenerated at test time -- so the recipe has to
    be readable, or in a year nobody knows why these pages."""
    assert (fixture_dir.parent / "make_fixture_corpus.py").is_file()
    assert (fixture_dir / "README.md").is_file()


def test_fixture_is_small_enough_to_read_in_a_diff(corpus_rows):
    """A bound, not a measurement (#47): the point is that it stays reviewable, not
    that it is exactly this size. Set well above the current 121 records."""
    assert len(corpus_rows) <= 400
