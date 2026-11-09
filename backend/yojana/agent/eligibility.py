"""Deterministic eligibility engine. The LLM never decides eligibility; this does."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field

from yojana.agent.slots import UserProfile
from yojana.rules import EligibilityRules, RulesRecord

CriterionStatus = Literal["met", "unmet", "unknown"]
Verdict = Literal["eligible", "partial", "ineligible", "unknown"]

_LABELS = {
    "age": "Age",
    "gender": "Gender",
    "state": "State of residence",
    "annual_family_income": "Annual family income",
    "social_category": "Social category",
    "occupation": "Occupation",
    "education_level": "Education level",
    "disability": "Disability",
    "residence": "Rural / urban residence",
    "other": "Other condition",
}


class Criterion(BaseModel):
    """One checked condition, with the chunk that states it."""

    field: str
    label: str
    status: CriterionStatus
    expected: str
    expected_values: list[str | int | bool] = Field(default_factory=list)
    actual: str | None = None
    chunk_id: str | None = None
    resolvable: bool = True


class SchemeEligibility(BaseModel):
    scheme_id: str
    scheme_name: str
    verdict: Verdict
    criteria: list[Criterion]
    met: int
    total: int
    score: float
    missing_fields: list[str]
    rules_reviewed: bool


def format_rupees(amount: int) -> str:
    """Indian digit grouping: 250000 -> '₹2,50,000'."""
    digits = str(int(amount))
    if len(digits) <= 3:
        return f"₹{digits}"
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join([*groups, tail])


def _pretty(values: Iterable[str]) -> str:
    return ", ".join(
        v.replace("_", " ").upper() if len(v) <= 3 else v.replace("_", " ") for v in values
    )


def _membership(
    field: str,
    allowed: list[str] | None,
    actual: str | None,
    chunk_id: str | None,
) -> Criterion | None:
    if not allowed:
        return None
    if actual is None:
        status: CriterionStatus = "unknown"
    else:
        status = "met" if actual in allowed else "unmet"
    return Criterion(
        field=field,
        label=_LABELS[field],
        status=status,
        expected=f"One of: {_pretty(allowed)}",
        expected_values=list(allowed),
        actual=actual,
        chunk_id=chunk_id,
    )


def _age(rules: EligibilityRules, age: int | None) -> Criterion | None:
    low, high = rules.min_age.value, rules.max_age.value
    if low is None and high is None:
        return None
    if low is not None and high is not None:
        expected = f"Between {low} and {high} years"
    elif low is not None:
        expected = f"At least {low} years"
    else:
        expected = f"At most {high} years"
    if age is None:
        status: CriterionStatus = "unknown"
    else:
        ok = (low is None or age >= low) and (high is None or age <= high)
        status = "met" if ok else "unmet"
    return Criterion(
        field="age",
        label=_LABELS["age"],
        status=status,
        expected=expected,
        expected_values=[v for v in (low, high) if v is not None],
        actual=None if age is None else str(age),
        chunk_id=rules.min_age.chunk_id if low is not None else rules.max_age.chunk_id,
    )


def _income(rules: EligibilityRules, income: int | None) -> Criterion | None:
    limit = rules.max_annual_family_income.value
    if limit is None:
        return None
    if income is None:
        status: CriterionStatus = "unknown"
    else:
        status = "met" if income <= limit else "unmet"
    return Criterion(
        field="annual_family_income",
        label=_LABELS["annual_family_income"],
        status=status,
        expected=f"At most {format_rupees(limit)} a year",
        expected_values=[limit],
        actual=None if income is None else format_rupees(income),
        chunk_id=rules.max_annual_family_income.chunk_id,
    )


def _disability(rules: EligibilityRules, disability: bool | None) -> Criterion | None:
    if rules.disability_required.value is not True:
        return None
    if disability is None:
        status: CriterionStatus = "unknown"
    else:
        status = "met" if disability else "unmet"
    return Criterion(
        field="disability",
        label=_LABELS["disability"],
        status=status,
        expected="Applicant must have a disability",
        expected_values=[True],
        actual=None if disability is None else ("yes" if disability else "no"),
        chunk_id=rules.disability_required.chunk_id,
    )


def _residence(rules: EligibilityRules, residence: str | None) -> Criterion | None:
    required = rules.residence.value
    if required is None:
        return None
    criterion = _membership("residence", [required], residence, rules.residence.chunk_id)
    if criterion is not None:
        criterion.expected = f"Must live in a {required} area"
    return criterion


def evaluate_rules(
    rules: EligibilityRules,
    profile: UserProfile,
) -> list[Criterion]:
    """Check every stated rule against the profile."""
    checks = [
        _age(rules, profile.age),
        _membership("gender", rules.genders.value, profile.gender, rules.genders.chunk_id),
        _membership("state", rules.states.value, profile.state, rules.states.chunk_id),
        _income(rules, profile.annual_family_income),
        _membership(
            "social_category",
            rules.social_categories.value,
            profile.social_category,
            rules.social_categories.chunk_id,
        ),
        _membership(
            "occupation", rules.occupations.value, profile.occupation, rules.occupations.chunk_id
        ),
        _membership(
            "education_level",
            rules.education_levels.value,
            profile.education_level,
            rules.education_levels.chunk_id,
        ),
        _disability(rules, profile.disability),
        _residence(rules, profile.residence),
    ]
    criteria = [c for c in checks if c is not None]
    criteria.extend(
        Criterion(
            field="other",
            label=_LABELS["other"],
            status="unknown",
            expected=condition.text,
            chunk_id=condition.chunk_id,
            resolvable=False,
        )
        for condition in rules.other_conditions
    )
    return criteria


def evaluate(record: RulesRecord, profile: UserProfile) -> SchemeEligibility:
    """Evaluate one scheme's rules against a profile.

    The verdict is `ineligible` if any criterion is unmet, `eligible` if every
    criterion that a profile field can answer is met, and `partial` otherwise.
    Free-text conditions cannot be checked automatically; they are listed as
    `unknown` but do not stop a scheme from being `eligible`.
    """
    criteria = evaluate_rules(record.rules, profile)
    resolvable = [c for c in criteria if c.resolvable]
    met = sum(1 for c in resolvable if c.status == "met")
    missing = sorted({c.field for c in resolvable if c.status == "unknown"})
    if not resolvable:
        verdict: Verdict = "unknown"
    elif any(c.status == "unmet" for c in resolvable):
        verdict = "ineligible"
    elif missing:
        verdict = "partial"
    else:
        verdict = "eligible"
    return SchemeEligibility(
        scheme_id=record.scheme_id,
        scheme_name=record.scheme_name,
        verdict=verdict,
        criteria=criteria,
        met=met,
        total=len(resolvable),
        score=round(met / len(resolvable), 4) if resolvable else 0.0,
        missing_fields=missing,
        rules_reviewed=not record.needs_review,
    )


_VERDICT_ORDER = {"eligible": 0, "partial": 1, "unknown": 2, "ineligible": 3}


def rank(results: Iterable[SchemeEligibility]) -> list[SchemeEligibility]:
    """Eligible first, then partially eligible by share of criteria met, then the rest."""
    return sorted(
        results,
        key=lambda r: (_VERDICT_ORDER[r.verdict], -r.score, -r.met, r.scheme_name.lower()),
    )
