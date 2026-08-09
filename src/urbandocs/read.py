"""`get`: verbatim provision text, its ancestor chain, and its direct children.

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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from urbandocs.substrate import ancestor_chain

if TYPE_CHECKING:
    from urbandocs.substrate import Substrate


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

    `records` holds one `GetRecord` per known id, in the order requested.
    `unknown_ids` names every id that was not in the substrate, in the order
    requested -- reported, not swallowed, and it never fails the rest of the
    batch (#56). Nothing here caps batch size: a large batch is disclosed by
    the shape of this response -- `records` as long as the known ids, nothing
    trimmed -- never truncated and never refused.
    """

    records: list[GetRecord]
    unknown_ids: list[str]


def get(ids: list[str], substrate: Substrate) -> GetResponse:
    """Return each requested record with its ancestor chain and direct children.

    Batched: one call over many ids is one pass over the substrate's indices,
    not one round trip per id. An id absent from the substrate is collected
    into `unknown_ids` rather than raising -- one bad id in a batch of ten must
    not cost the other nine (#56).
    """
    records: list[GetRecord] = []
    unknown_ids: list[str] = []

    for record_id in ids:
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
