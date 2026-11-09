"""Metadata filters derived from the query and the user's profile."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from yojana.index.store import sql_in
from yojana.ingest.models import Chunk
from yojana.taxonomy import ALL_STATES, find_states, normalize_state, score_categories


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Constraints applied identically to the dense and the sparse retriever."""

    states: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    scheme_ids: tuple[str, ...] = ()
    sections: tuple[str, ...] = field(default=())

    @property
    def empty(self) -> bool:
        return not (self.states or self.categories or self.scheme_ids or self.sections)

    def where(self) -> str | None:
        """SQL predicate for LanceDB, or None when there is nothing to filter."""
        clauses = []
        if self.states:
            clauses.append(sql_in("state", self.states))
        if self.categories:
            clauses.append(sql_in("category", self.categories))
        if self.scheme_ids:
            clauses.append(sql_in("scheme_id", self.scheme_ids))
        if self.sections:
            clauses.append(sql_in("section", self.sections))
        return " AND ".join(clauses) or None

    def allows(self, chunk: Chunk) -> bool:
        return (
            (not self.states or chunk.state in self.states)
            and (not self.categories or chunk.category in self.categories)
            and (not self.scheme_ids or chunk.scheme_id in self.scheme_ids)
            and (not self.sections or chunk.section in self.sections)
        )

    def without_categories(self) -> SearchFilters:
        return replace(self, categories=())

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "states": list(self.states),
            "categories": list(self.categories),
            "scheme_ids": list(self.scheme_ids),
            "sections": list(self.sections),
        }


def build_filters(
    query: str,
    *,
    profile_state: str | None = None,
    scheme_ids: list[str] | None = None,
    sections: list[str] | None = None,
    use_categories: bool = True,
) -> SearchFilters:
    """Derive filters: a state from the query or profile, categories from keywords.

    National schemes are stored with state `ALL`, so a state filter always keeps them.
    """
    mentioned = find_states(query)
    state = mentioned[0] if mentioned else normalize_state(profile_state)
    states: tuple[str, ...] = ()
    if state and state != ALL_STATES:
        states = (state, ALL_STATES)
    categories: tuple[str, ...] = ()
    if use_categories and not scheme_ids:
        scores = score_categories(query)
        if scores:
            categories = tuple(sorted(scores, key=lambda k: -scores[k]))
    return SearchFilters(
        states=states,
        categories=categories,
        scheme_ids=tuple(scheme_ids or ()),
        sections=tuple(sections or ()),
    )
