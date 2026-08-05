"""The normativa retrieval engine.

Deliberately empty of re-exports. The engine's own modules do not exist yet --
what `search`/`get`/`get_by_cite`/`get_page` must do is decided on
[#42](https://github.com/javier-abia/urbandocs/issues/42), and the internal
module structure belongs to whoever builds them (#46). What is here is the
pipeline that produces the substrate they will read:

    python -m urbandocs.ingest         # tuned docling JSON -> corpus/corpus.tsv
    python -m urbandocs.check_corpus   # acceptance gate over that corpus
"""
