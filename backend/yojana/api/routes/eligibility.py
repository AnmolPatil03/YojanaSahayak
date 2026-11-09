"""Profile-based eligibility across all schemes with reviewed rules."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from yojana.agent.questions import select_question
from yojana.agent.slots import UserProfile
from yojana.api.routes.schemes import summary

router = APIRouter(prefix="/api", tags=["eligibility"])


class EligibilityRequest(BaseModel):
    profile: UserProfile = Field(default_factory=UserProfile)
    scheme_ids: list[str] | None = None
    asked_fields: list[str] = Field(default_factory=list)


@router.post("/eligibility")
def check_eligibility(body: EligibilityRequest, request: Request) -> dict[str, Any]:
    """Rank schemes as eligible, partially eligible or ineligible for a profile."""
    svc = request.app.state.services
    scheme_ids = body.scheme_ids or [r.scheme_id for r in svc.registry.all()]
    verdicts, pending = svc.orchestrator.eligibility_for(scheme_ids, body.profile)
    results = []
    for verdict in verdicts:
        record = svc.registry.get(verdict.scheme_id)
        criteria = []
        for criterion in verdict.criteria:
            item = criterion.model_dump()
            chunk = svc.chunks.get(criterion.chunk_id) if criterion.chunk_id else None
            item["source"] = (
                {
                    "chunk_id": chunk.chunk_id,
                    "source_url": chunk.source_url,
                    "page": chunk.page,
                    "text": chunk.text,
                    "section": chunk.section,
                }
                if chunk
                else None
            )
            criteria.append(item)
        results.append(
            {
                **verdict.model_dump(exclude={"criteria"}),
                "criteria": criteria,
                "scheme": summary(record, svc) if record else None,
            }
        )
    question = select_question(verdicts, asked=body.asked_fields)
    return {
        "results": results,
        "counts": {
            kind: sum(1 for v in verdicts if v.verdict == kind)
            for kind in ("eligible", "partial", "ineligible", "unknown")
        },
        "pending_review": pending,
        "question": question.model_dump() if question else None,
        "profile": body.profile.model_dump(),
    }
