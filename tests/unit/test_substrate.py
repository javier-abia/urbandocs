"""`load_substrate` is the fail-loud gate every other operation stands behind.

A missing file, a mismatched header, or a wrong column count must refuse to
load rather than silently yield a short corpus (#38, #58) -- that is this
engine's worst failure mode (#45), and the one this suite holds hardest.
"""

from __future__ import annotations

import pytest

from urbandocs.ingest import COLUMNS
from urbandocs.substrate import SubstrateError, load_substrate


def test_missing_substrate_refuses_to_load(tmp_path):
    with pytest.raises(SubstrateError, match="missing substrate"):
        load_substrate(corpus_path=tmp_path / "does-not-exist.tsv")


def test_header_mismatch_refuses_to_load(tmp_path):
    bad = tmp_path / "corpus.tsv"
    bad.write_text("id\tdoc\tpage\n1\tSUA\t1\n")
    with pytest.raises(SubstrateError, match="header mismatch"):
        load_substrate(corpus_path=bad)


def test_wrong_column_count_refuses_to_load(tmp_path):
    """A ragged row -- the exact shape an unescaped tab in `text` would produce
    (#33) -- must not be silently padded or truncated into a short corpus."""
    bad = tmp_path / "corpus.tsv"
    bad.write_text(
        "\t".join(COLUMNS) + "\n" + "SUA:p1:1\tSUA\t1\t1\t\tsection_header\tonly six\n"
    )
    with pytest.raises(SubstrateError, match="line 2"):
        load_substrate(corpus_path=bad)


def test_a_quoted_record_loads_with_its_fields_intact(fixture_dir, corpus_rows):
    """The record a default `csv.reader` merges (#33): its text opens mid-string
    with a `"`, and a quoting reader would swallow every tab after it until the
    next quote closes -- three fewer fields, a corrupted row, and no error.

    `load_substrate` never builds a `csv.reader`, so the row must come back
    exactly as `corpus_rows` (read with `csv.QUOTE_NONE`, the known-correct
    reader) has it.
    """
    substrate = load_substrate(corpus_path=fixture_dir / "corpus.tsv")
    want = next(r for r in corpus_rows if r["id"] == "SUA:p32:§7")
    got = substrate.by_id["SUA:p32:§7"]
    assert '"ojo de buey"' in got["text"]
    assert got["text"] == want["text"]
    assert got["norm"] == want["norm"]
    assert got["parent_id"] == want["parent_id"]


def test_loads_every_record_no_row_lost_to_merging(fixture_dir, corpus_rows):
    """The row count is the cheapest proof that no `"` merged two records into
    one -- a merge would silently come back short, never with an error."""
    substrate = load_substrate(corpus_path=fixture_dir / "corpus.tsv")
    assert len(substrate.records) == len(corpus_rows)


def test_by_cite_index_groups_by_printed_cite(fixture_dir):
    """The index `get_by_cite` resolves through (#61) -- built once at load
    time, same as `children`."""
    substrate = load_substrate(corpus_path=fixture_dir / "corpus.tsv")
    assert set(substrate.by_cite["a)"]) >= {
        "D128:p25:A.3.2.1.a",
        "D128:p32:A.4.2.1.a",
    }
    assert all(substrate.by_id[rid]["cite"] == "a)" for rid in substrate.by_cite["a)"])


def test_by_cite_index_excludes_records_with_no_cite(fixture_dir):
    substrate = load_substrate(corpus_path=fixture_dir / "corpus.tsv")
    assert "" not in substrate.by_cite


def test_children_index_groups_by_parent_id(fixture_dir):
    """The adjacency `search`'s child-matching and `get`'s ancestor walk both
    need (#56) -- built once at load time rather than scanned per call."""
    substrate = load_substrate(corpus_path=fixture_dir / "corpus.tsv")
    # D128:p21:A.2.2 is the hand-verified heading from `check_corpus.py`'s own
    # ancestor-chain assertion; its direct children include the 60º provision.
    assert "D128:p22:A.2.2.e" in substrate.children["D128:p21:A.2.2"]
    assert all(
        substrate.by_id[child_id]["parent_id"] == "D128:p21:A.2.2"
        for child_id in substrate.children["D128:p21:A.2.2"]
    )
