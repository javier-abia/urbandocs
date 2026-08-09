"""The sweep and the ranking, as plain Python functions over the substrate.

Everything `search` does except cross a wire (#58): given a list of terms, sweep
the whole corpus, group hits into sections, and return the complete ranked list
of sections -- never truncated, because the cutoff is the calling agent's
judgement over heading chains, not a top-N this module imposes (#56).

Three things this gets wrong silently if it gets them wrong at all (#58):

- Match is word-boundary + literal prefix against `norm`, never `text` -- `norm`
  is the stemming that makes `anch` reach both `ancho` and `anchura` (#9).
- Terms are agent-generated and untrusted: escaped as regex literals so
  `*altura` and `Ley 5/2010` are searches, never a crash or a silently
  different query.
- Sections score by *distinct slots matched*, never raw hit count, so one term
  hit forty times in a section never outranks four terms hit once each.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from urbandocs.ingest import normalize
from urbandocs.substrate import ancestor_chain

if TYPE_CHECKING:
    from urbandocs.substrate import Substrate


@dataclass(frozen=True)
class RankedSection:
    """One line of `search`'s ranked list. An address, never legal text (#56):
    call `get(section_id)` or `get(matched_children)` for the provision itself.
    """

    #: Distinct terms (slots) this section matched -- the ranking key.
    score: int
    doc: str
    page: int
    #: Root-first text of each ancestor heading, the section's own text
    #: excluded -- the section is already named by `section_id`, and `get`'s
    #: own ancestor contract (#56) is the same shape: each ancestor's own text,
    #: nothing dragged in from a sibling subtree.
    ancestors: list[str]
    section_id: str
    #: Ids of the direct children that matched, in corpus reading order --
    #: empty when the section matched through its own text rather than a
    #: child's (see `search`'s docstring on self-matching sections).
    matched_children: list[str]


def _term_pattern(term: str) -> re.Pattern[str]:
    """Compile one search term into a word-boundary literal-prefix pattern.

    `normalize` is the exact function that produced the `norm` column (its own
    docstring says so: "Query-side normalization must call this same function,
    or the two sides stop agreeing"), so a term matches regardless of the
    case or accents it arrived in.

    `re.escape` runs on the *normalized* term, after folding, so an
    agent-generated term is always read as a literal -- `*altura` does not
    silently degrade to `altura` (it would otherwise be `\\b*altura`, a `*`
    with nothing to repeat, a compile-time crash) and `Ley 5/2010` is a search
    rather than a `re.error` (#56).
    """
    return re.compile(r"\b" + re.escape(normalize(term)))


def search(terms: list[str], substrate: Substrate) -> list[RankedSection]:
    """Sweep the whole corpus for `terms`, group hits into sections, rank them.

    Each term is one slot (#56). A record matches a slot when its `norm` field
    contains that term as a word-boundary literal prefix. A matching record's
    *section* is its `parent_id` -- the heading (or list item) that owns it --
    or, when a record has no parent at all (a top-level heading matching on its
    own text), the record itself; such a section carries no matched children,
    because nothing is subordinate to it in this sweep.

    A section's score is the count of distinct slots matched anywhere under it,
    never the number of matching records nor the number of hits within one
    record -- the ranking #56 requires so that a section repeating one term
    forty times cannot outrank one that matched every term once.

    Returns the complete list, never truncated (#56), ordered by score
    descending and then by the section's first appearance in the corpus, for a
    result stable across runs. A term matching nothing contributes no section;
    if no term matches anything the result is `[]`, not an error.
    """
    patterns = [_term_pattern(term) for term in terms]
    record_order = {record["id"]: i for i, record in enumerate(substrate.records)}

    slots: dict[str, set[int]] = defaultdict(set)
    matched_children: dict[str, set[str]] = defaultdict(set)

    for record in substrate.records:
        norm = record["norm"]
        if not norm:
            continue
        for slot, pattern in enumerate(patterns):
            if pattern.search(norm):
                section_id = record["parent_id"] or record["id"]
                slots[section_id].add(slot)
                if record["parent_id"]:
                    matched_children[section_id].add(record["id"])

    ranked = [
        RankedSection(
            score=len(matched_slots),
            doc=section["doc"],
            page=section["page"],
            ancestors=ancestor_chain(section_id, substrate),
            section_id=section_id,
            matched_children=sorted(
                matched_children.get(section_id, set()),
                key=lambda child_id: record_order[child_id],
            ),
        )
        for section_id, matched_slots in slots.items()
        # The loader guarantees every parent_id resolves (#58); `by_id` is
        # consulted rather than assumed so a corrupt substrate fails here
        # loudly instead of KeyError-ing three lines down.
        if (section := substrate.by_id.get(section_id)) is not None
    ]
    ranked.sort(key=lambda r: (-r.score, record_order[r.section_id]))
    return ranked
