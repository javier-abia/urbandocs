# Normativa search

The retrieval substrate over local construction-permit legislation. A technical
architect reviewing a permit file asks it a question; it returns the passages
that govern the answer, with citations they can verify against the source PDF.

## Language

**Normativa**:
The body of legal documents a permit is checked against — the local and national
regulations held as PDFs in this repo.
_Avoid_: regulation, legislation, docs

**Expediente**:
A client's construction-permit file, reviewed against the normativa by a
technical architect. Reviewing one is downstream of this engine, not part of it.
_Avoid_: case, application, permit file

**Articulado**:
The numbered normative body of a document — its articles and their provisions —
as opposed to its preamble, contents pages, or annexes.

**Provision**:
The smallest addressable unit of normativa: one numbered or lettered passage that
states a rule. The unit a citation names and retrieval returns.
_Avoid_: clause, paragraph, chunk

**Commentary**:
Ministry explanation printed alongside the normative text, non-binding. The
engine retrieves it without distinguishing it; the architect verifies at the
source.

**Cite**:
The address a document prints for a provision (`Artículo 14.1.a)`, `tabla 1.2`).
It may repeat within a document and may be absent, so it locates a provision but
does not uniquely identify one — distinct from the engine's own `id`.

**Pointer**:
A phrase inside a provision that names another addressable unit by its printed
cite (`según la tabla 1.2`, `lo regulado en el anexo II`). *In-corpus* when the
target is a held document, *external* when it names a norm the corpus does not
hold (`Ley 39/2015`, `DB SI`).
_Avoid_: reference, link, cross-reference

**Relative mention**:
A phrase naming another unit by relation rather than address (`el apartado
anterior`). Carries no cite, so it cannot be resolved by lookup. Not a pointer.

**Corpus**:
The set of normativa documents the engine holds and searches.
