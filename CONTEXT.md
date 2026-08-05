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

**Citation**:
What the engine emits so a finding can be checked at the source: file, PDF page,
and the provision's full ancestor chain. It promises a *location* — that the
governing provision is there — not that the returned text matches the page
glyph for glyph, which OCR'd documents cannot honour.
_Avoid_: reference, source, quote

**Printed page**:
The page number a page prints on itself. Absent on some pages, and offset from
the PDF page in some documents (`Pág. 36525` on DOG_2025's first page). Carried
for reading aloud only — architects navigate by PDF page, so nothing derives it.

**Disclosure**:
A statement attached to returned evidence about how faithfully it was extracted
— never a filter, and never a reason to withhold a passage. The engine discloses
and still returns; deciding what the damage means is the architect's.

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

**Substrate**:
The one flat table the engine searches — `corpus/corpus.tsv`, one record per
addressable unit, rebuilt in seconds from the committed docling JSON. The agent
never opens a document file.
_Avoid_: index, database, store

**Record**:
One row of the substrate: a provision, heading, table, or figure position, with
its `id`, `cite`, `parent_id`, page, verbatim `text` and searchable `norm`. What
a lookup returns and what a citation is built from.
_Avoid_: chunk, row, entry
