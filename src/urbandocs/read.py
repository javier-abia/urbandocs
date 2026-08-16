"""`get`: verbatim provision text, its ancestor chain, and its direct children.
`get_page`: every record on one PDF page, in reading order.

Everything `get` does except cross a wire (#60). `search` returns addresses;
this is where an agent spends those addresses on text. Two things a rule can
lose if this gets them wrong:

- The qualifier that lives one level up -- `art14.1.a`'s encimera applies only
  under `art14.1`'s no-new-rooms condition. Dropping the ancestor chain drops
  the condition silently.
- The obligation that lives one level down -- a provision ending in
  `deberá cumplir:` states nothing on its own. Dropping the children drops the
  obligation silently.

So every requested record comes back with both, and neither drags in more than
it should: ancestors are each ancestor's own heading text, root first, with no
sibling subtree attached; children are direct children only, no grandchildren.

`get_page` (#62) reaches sideways instead of vertically -- the escape hatch for
context the ancestor walk cannot see, called on judgement rather than as a
phase of the loop. Deliberately no range parameter: a long article is walked
one page at a time rather than pulled in one call whose token cost is invisible
at the call site (#62's own example -- one article spans pp. 43-79).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from urbandocs.substrate import ancestor_chain

if TYPE_CHECKING:
    from urbandocs.substrate import Substrate


def _expand_id(entry: str) -> list[str]:
    """Expand one requested id, plain or compact-grouped, to its full id(s).

    A compact group names several ids sharing a `doc:pPage` prefix without
    repeating it (#100): `"DOC:pN:tail1,tail2"` in place of
    `"DOC:pN:tail1"` and `"DOC:pN:tail2"` -- the same grouping `search`'s
    wire format prints `matched_children` in, so those ids can be passed to
    `get` straight from a `search` result. A plain id has no `,` in its
    tail and expands to itself unchanged; no id in the corpus contains a
    literal `,` (`ingest.cite_path` never produces one), so the comma is an
    unambiguous marker rather than a character a real id could collide with.
    """
    prefix, sep, tail = entry.rpartition(":")
    if not sep or "," not in tail:
        return [entry]
    return [f"{prefix}:{one}" for one in tail.split(",")]


def _expand_ids(ids: list[str]) -> list[str]:
    """Flatten a batch of plain and compact-grouped ids into plain ids, in
    order -- a group expands to its members in place, at its own position
    in the batch.
    """
    expanded: list[str] = []
    for entry in ids:
        expanded.extend(_expand_id(entry))
    return expanded


@dataclass(frozen=True)
class ChildRecord:
    """One direct child of a requested record -- context, not the match.

    Id and text only, the same restraint `search`'s ancestors already apply
    (#58): a child is context for the record that was asked for, not a record
    in its own right here. An agent that wants it as the match calls `get` on
    its `id`.
    """

    id: str
    text: str


@dataclass(frozen=True)
class GetRecord:
    """One requested record: the match, plus the context #56 requires around
    it.

    `text` is the match -- this record's own verbatim text. `ancestors` and
    `children` are context: root-first ancestor heading text with no sibling
    subtree attached, and this record's direct children with no grandchildren
    -- keeping match and context distinguishable by where they sit rather
    than by a repeated label on every field.
    """

    id: str
    doc: str
    page: int
    ancestors: list[str]
    text: str
    children: list[ChildRecord]


@dataclass(frozen=True)
class GetResponse:
    """The result of one `get` call.

    `records` holds one `GetRecord` per known id, in the order requested --
    a compact-grouped id in the request expands to its members in order, in
    its own place in the sequence. `unknown_ids` names every id that was not
    in the substrate, in the same order -- reported, not swallowed, and it
    never fails the rest of the batch (#56). Nothing here caps batch size: a
    large batch is disclosed by the shape of this response -- `records` as
    long as the known ids, nothing trimmed -- never truncated and never
    refused.
    """

    records: list[GetRecord]
    unknown_ids: list[str]


def get(ids: list[str], substrate: Substrate) -> GetResponse:
    """Return each requested record with its ancestor chain and direct children.

    `ids` accepts compact-grouped ids as well as plain ones (#100) -- each
    is expanded to its full ids before anything else here runs, so a
    `search` result's `matched_children` can be passed straight through
    without expanding it client-side first.

    Batched: one call over many ids is one pass over the substrate's indices,
    not one round trip per id. An id absent from the substrate is collected
    into `unknown_ids` rather than raising -- one bad id in a batch of ten must
    not cost the other nine (#56).
    """
    records: list[GetRecord] = []
    unknown_ids: list[str] = []

    for record_id in _expand_ids(ids):
        record = substrate.by_id.get(record_id)
        if record is None:
            unknown_ids.append(record_id)
            continue

        records.append(
            GetRecord(
                id=record["id"],
                doc=record["doc"],
                page=record["page"],
                ancestors=ancestor_chain(record_id, substrate),
                text=record["text"],
                children=[
                    ChildRecord(id=child_id, text=substrate.by_id[child_id]["text"])
                    for child_id in substrate.children.get(record_id, [])
                ],
            )
        )

    return GetResponse(records=records, unknown_ids=unknown_ids)


class UnknownPageError(ValueError):
    """`get_page` refuses a page outside the document rather than returning
    empty silently -- the one distinction that lets a caller tell "nothing on
    this page" from "no such page" (#62).
    """


@dataclass(frozen=True)
class PageRecord:
    """One record on a page, in bbox reading order (#62).

    `label` is here and not on `GetRecord`: a page mixes headings, body text,
    tables and picture placeholders, and a picture's `text` is empty by
    construction -- without `label`, that empty string is indistinguishable
    from a record that lost its text some other way.
    """

    id: str
    label: str
    text: str


def get_page(doc: str, page: int, substrate: Substrate) -> list[PageRecord]:
    """Return every record on one PDF page, in bbox reading order.

    Order comes from `substrate.records`/`by_page`, not from re-sorting here --
    `ingest` already derives it from `prov.bbox`, because the docling JSON's
    `texts` array itself is misordered (#8).

    `doc`/`page` outside the document raises `UnknownPageError`; a page inside
    the document with no records returns `[]` (#62).
    """
    n_pages = substrate.doc_pages.get(doc)
    if n_pages is None or not 1 <= page <= n_pages:
        raise UnknownPageError(f"{doc!r} has no page {page}")

    return [
        PageRecord(
            id=record_id,
            label=substrate.by_id[record_id]["label"],
            text=substrate.by_id[record_id]["text"],
        )
        for record_id in substrate.by_page.get((doc, page), [])
    ]
