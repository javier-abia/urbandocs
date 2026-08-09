"""`get_by_cite`: resolve a printed cite to every candidate address (#61).

A resolver, never a getter: returns addresses -- id, doc, page, ancestor
chain -- and nothing else, because a printed cite locates a record but does
not uniquely identify one; most cites in this corpus are ambiguous, so the
agent calls `get` on whichever candidate it picks (#18, #61).

`doc` is an optional filter, not a disambiguator -- it narrows candidates to
one document without resolving a collision that lives inside that document,
since most of the corpus's ambiguity is intra-document (#61).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from urbandocs.substrate import ancestor_chain

if TYPE_CHECKING:
    from urbandocs.substrate import Substrate


@dataclass(frozen=True)
class CiteCandidate:
    """One candidate address for a resolved cite -- location only, no legal
    text (#61): call `get(id)` on whichever candidate is the right one.
    """

    id: str
    doc: str
    page: int
    #: Root-first text of each ancestor heading, this record's own text
    #: excluded -- the same shape `get`'s and `search`'s ancestors already
    #: use (#56, #58, #60).
    ancestors: list[str]


def get_by_cite(
    cite: str, substrate: Substrate, doc: str | None = None
) -> list[CiteCandidate]:
    """Resolve a printed cite to every record that prints it, as addresses.

    Matches the `cite` column literally, in corpus reading order. A cite
    absent from the corpus, or an empty string, returns `[]` rather than
    erroring -- a record with no cite is simply unreachable here (#4, #61).

    `doc`, when given, filters the candidates to that document (#61).
    """
    candidates = []
    for record_id in substrate.by_cite.get(cite, []):
        record = substrate.by_id[record_id]
        if doc is not None and record["doc"] != doc:
            continue
        candidates.append(
            CiteCandidate(
                id=record_id,
                doc=record["doc"],
                page=record["page"],
                ancestors=ancestor_chain(record_id, substrate),
            )
        )
    return candidates
