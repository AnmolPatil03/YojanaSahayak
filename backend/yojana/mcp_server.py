"""MCP stdio server exposing scheme search, details, eligibility and checklists.

Run with `python -m yojana.mcp_server`. No LLM is called here: retrieval and the
rule engine return citable facts, and the MCP client's own model does the reasoning.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from mcp.server.mcpserver import MCPServer

from yojana.agent.eligibility import evaluate, rank
from yojana.agent.slots import UserProfile
from yojana.catalog import checklist_items, scheme_details
from yojana.config import Settings, get_settings
from yojana.ingest.registry import SchemeRegistry
from yojana.logging_setup import configure_logging
from yojana.retrieve.filters import build_filters
from yojana.retrieve.hybrid import HybridRetriever
from yojana.rules import RulesStore
from yojana.taxonomy import CATEGORIES

logger = logging.getLogger(__name__)

INSTRUCTIONS = """Tools for Indian government welfare schemes, backed by scheme documents.
Every passage carries a source URL; cite it when you use it. Eligibility verdicts come
from a deterministic rule engine over reviewed rules: report them as given and do not
infer eligibility yourself. If search_schemes reports `abstained`, the documents do not
cover the question."""


class Backend:
    """Loads indexes on first use so the server starts instantly."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        retriever: HybridRetriever | None = None,
        registry: SchemeRegistry | None = None,
        rules: RulesStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._retriever = retriever
        self._registry = registry
        self._rules = rules

    @property
    def retriever(self) -> HybridRetriever:
        if self._retriever is None:
            self._retriever = HybridRetriever.from_settings(self.settings)
        return self._retriever

    @property
    def registry(self) -> SchemeRegistry:
        if self._registry is None:
            self._registry = SchemeRegistry.load(self.settings.processed_dir / "schemes.json")
        return self._registry

    @property
    def rules(self) -> RulesStore:
        if self._rules is None:
            self._rules = RulesStore(self.settings.processed_dir / "rules")
        return self._rules


def build_server(backend: Backend | None = None) -> MCPServer:
    """Create the MCP server with its four tools."""
    backend = backend or Backend()
    server = MCPServer("yojana-sahayak", instructions=INSTRUCTIONS)

    @server.tool()
    def search_schemes(
        query: str,
        state: str | None = None,
        category: str | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Search scheme documents (English or Hindi) and return reranked passages.

        Args:
            query: What to look for, e.g. "scholarships for SC students in Bihar".
            state: Optional Indian state; national schemes are always included.
            category: Optional category key, one of: education, agriculture, business,
                women_child, disability, employment, health, housing, social_welfare.
            top_k: Number of passages to return (1-10).
        """
        retriever = backend.retriever
        top_k = max(1, min(top_k, 10))
        filters = build_filters(query, profile_state=state)
        if category in CATEGORIES:
            filters = replace(filters, categories=(category,))
        cfg = retriever.cfg.model_copy(update={"final_top_k": top_k})
        result = retriever.retrieve(query, filters, cfg=cfg)
        return {
            "query": query,
            "abstained": result.abstained,
            "top_score": result.top_score,
            "filters": result.filters.as_dict(),
            "results": [
                {
                    "citation": f"[{rank_}]",
                    "chunk_id": item.chunk.chunk_id,
                    "scheme_id": item.chunk.scheme_id,
                    "scheme_name": item.chunk.scheme_name,
                    "section": item.chunk.section,
                    "text": item.chunk.text,
                    "source_url": item.chunk.source_url,
                    "page": item.chunk.page,
                    "language": item.chunk.language,
                    "score": round(item.score, 4),
                    "is_sample": item.chunk.is_sample,
                }
                for rank_, item in enumerate(result.chunks, start=1)
            ],
        }

    @server.tool()
    def get_scheme_details(scheme_id: str) -> dict[str, Any]:
        """Full details of one scheme: sections, eligibility rules, sources and documents.

        Args:
            scheme_id: Id returned by search_schemes, e.g. "pm-kisan".
        """
        record = backend.registry.get(scheme_id)
        if record is None:
            return {"error": f"Unknown scheme_id {scheme_id!r}"}
        return scheme_details(
            record,
            backend.rules,
            backend.retriever.chunks,
            allow_unreviewed=backend.settings.allow_unreviewed_rules,
        )

    @server.tool()
    def check_eligibility(
        profile: UserProfile, scheme_ids: list[str] | None = None
    ) -> dict[str, Any]:
        """Run the deterministic eligibility engine for a profile.

        Every criterion is met, unmet or unknown, with the chunk that states it.
        Only schemes with reviewed rules are evaluated.

        Args:
            profile: Known facts: age, gender, state, annual_family_income (rupees per
                year), social_category, occupation, education_level, disability,
                residence. Leave unknown fields out.
            scheme_ids: Optional subset of schemes; all schemes when omitted.
        """
        ids = scheme_ids or [r.scheme_id for r in backend.registry.all()]
        results = []
        pending = []
        for scheme_id in ids:
            record = backend.rules.usable(
                scheme_id, allow_unreviewed=backend.settings.allow_unreviewed_rules
            )
            if record is None:
                if backend.rules.get(scheme_id) is not None:
                    pending.append(scheme_id)
                continue
            results.append(evaluate(record, profile))
        chunks = backend.retriever.chunks
        ranked = []
        for verdict in rank(results):
            item = verdict.model_dump()
            for criterion in item["criteria"]:
                chunk = chunks.get(criterion["chunk_id"]) if criterion["chunk_id"] else None
                criterion["source_url"] = chunk.source_url if chunk else None
            ranked.append(item)
        return {"results": ranked, "pending_review": pending}

    @server.tool()
    def list_required_documents(scheme_id: str) -> dict[str, Any]:
        """The documents a scheme asks for, each with the passage it comes from.

        Args:
            scheme_id: Id returned by search_schemes.
        """
        record = backend.registry.get(scheme_id)
        if record is None:
            return {"error": f"Unknown scheme_id {scheme_id!r}"}
        return {
            "scheme_id": scheme_id,
            "scheme_name": record.name,
            "documents": checklist_items(record, backend.retriever.chunks),
        }

    return server


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    build_server(Backend(settings)).run("stdio")


if __name__ == "__main__":
    main()
