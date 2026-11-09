from __future__ import annotations

import pytest

from yojana.agent.eligibility import evaluate, format_rupees, rank
from yojana.agent.slots import UserProfile
from yojana.rules import EligibilityRules, OtherCondition, RulesRecord, RuleValue

CHUNK = "test-scheme-alpha::x::eligibility::000"


def record(needs_review: bool = False, **fields: object) -> RulesRecord:
    data: dict[str, object] = {}
    for name, value in fields.items():
        if name == "other_conditions":
            data[name] = value
        else:
            data[name] = {"value": value, "chunk_id": CHUNK}
    return RulesRecord(
        scheme_id="test-scheme-alpha",
        scheme_name="Test Scheme Alpha",
        rules=EligibilityRules.model_validate(data),
        needs_review=needs_review,
    )


def statuses(result) -> dict[str, str]:
    return {c.field: c.status for c in result.criteria}


ALPHA = record(
    min_age=17,
    max_age=25,
    max_annual_family_income=250000,
    social_categories=["sc", "st", "obc"],
    occupations=["student"],
    education_levels=["graduate"],
)


def test_fully_eligible_profile() -> None:
    profile = UserProfile(
        age=20,
        annual_family_income=200000,
        social_category="sc",
        occupation="student",
        education_level="graduate",
    )
    result = evaluate(ALPHA, profile)
    assert result.verdict == "eligible"
    assert result.met == result.total == 5
    assert result.score == 1.0
    assert all(c.chunk_id == CHUNK for c in result.criteria)


def test_any_unmet_criterion_makes_scheme_ineligible() -> None:
    profile = UserProfile(age=30, social_category="sc")
    result = evaluate(ALPHA, profile)
    assert result.verdict == "ineligible"
    assert statuses(result)["age"] == "unmet"


def test_missing_fields_give_partial_verdict() -> None:
    result = evaluate(ALPHA, UserProfile(age=20))
    assert result.verdict == "partial"
    assert result.missing_fields == [
        "annual_family_income",
        "education_level",
        "occupation",
        "social_category",
    ]
    assert result.score == pytest.approx(1 / 5)


def test_empty_profile_is_partial_not_eligible() -> None:
    result = evaluate(ALPHA, UserProfile())
    assert result.verdict == "partial"
    assert result.met == 0


@pytest.mark.parametrize(
    ("age", "status"),
    [(16, "unmet"), (17, "met"), (25, "met"), (26, "unmet")],
)
def test_age_bounds_are_inclusive(age: int, status: str) -> None:
    assert statuses(evaluate(ALPHA, UserProfile(age=age)))["age"] == status


def test_only_minimum_or_maximum_age() -> None:
    at_least = evaluate(record(min_age=18), UserProfile(age=18))
    at_most = evaluate(record(max_age=60), UserProfile(age=61))
    assert at_least.criteria[0].expected == "At least 18 years"
    assert at_least.verdict == "eligible"
    assert at_most.criteria[0].expected == "At most 60 years"
    assert at_most.verdict == "ineligible"


@pytest.mark.parametrize(("income", "status"), [(250000, "met"), (250001, "unmet"), (0, "met")])
def test_income_limit_is_inclusive(income: int, status: str) -> None:
    result = evaluate(ALPHA, UserProfile(annual_family_income=income))
    assert statuses(result)["annual_family_income"] == status


def test_general_category_does_not_match_reserved_list() -> None:
    result = evaluate(ALPHA, UserProfile(social_category="general"))
    assert statuses(result)["social_category"] == "unmet"


def test_gender_and_state_membership() -> None:
    rules = record(genders=["female"], states=["Karnataka"])
    assert evaluate(rules, UserProfile(gender="female", state="Karnataka")).verdict == "eligible"
    assert evaluate(rules, UserProfile(gender="male", state="Karnataka")).verdict == "ineligible"
    assert evaluate(rules, UserProfile(gender="female", state="Kerala")).verdict == "ineligible"


def test_nationwide_state_rule_is_not_a_criterion() -> None:
    rules = record(states=["ALL"], min_age=18)
    assert [c.field for c in evaluate(rules, UserProfile()).criteria] == ["age"]


def test_disability_required() -> None:
    rules = record(disability_required=True)
    assert evaluate(rules, UserProfile(disability=True)).verdict == "eligible"
    assert evaluate(rules, UserProfile(disability=False)).verdict == "ineligible"
    assert evaluate(rules, UserProfile()).verdict == "partial"


def test_disability_false_in_rules_is_no_constraint() -> None:
    assert evaluate(record(disability_required=False), UserProfile()).verdict == "unknown"


def test_residence() -> None:
    rules = record(residence="rural")
    assert evaluate(rules, UserProfile(residence="rural")).verdict == "eligible"
    assert evaluate(rules, UserProfile(residence="urban")).verdict == "ineligible"


def test_other_conditions_are_listed_but_do_not_block_eligibility() -> None:
    rules = record(
        min_age=18,
        other_conditions=[OtherCondition(text="Must own farmland.", chunk_id=CHUNK)],
    )
    result = evaluate(rules, UserProfile(age=40))
    other = [c for c in result.criteria if c.field == "other"]
    assert result.verdict == "eligible"
    assert other[0].status == "unknown" and not other[0].resolvable
    assert result.total == 1


def test_scheme_without_structured_rules_is_unknown() -> None:
    rules = record(other_conditions=[OtherCondition(text="Case by case.")])
    assert evaluate(rules, UserProfile(age=30)).verdict == "unknown"


def test_rule_values_are_normalised() -> None:
    rules = record(
        genders=["Women"],
        social_categories=["Scheduled Caste", "OBC"],
        states=["tamil nadu"],
        occupations=["Farmer", "unknown job"],
        education_levels=["Graduation"],
    )
    assert rules.rules.genders.value == ["female"]
    assert rules.rules.social_categories.value == ["sc", "obc"]
    assert rules.rules.states.value == ["Tamil Nadu"]
    assert rules.rules.occupations.value == ["farmer"]
    assert rules.rules.education_levels.value == ["graduate"]


def test_review_flag_is_reported() -> None:
    assert not evaluate(record(needs_review=True, min_age=1), UserProfile()).rules_reviewed


def test_ranking_order() -> None:
    eligible = evaluate(record(min_age=18), UserProfile(age=20))
    partial = evaluate(ALPHA, UserProfile(age=20))
    ineligible = evaluate(record(min_age=60), UserProfile(age=20))
    assert [r.verdict for r in rank([ineligible, partial, eligible])] == [
        "eligible",
        "partial",
        "ineligible",
    ]


def test_rupee_formatting() -> None:
    assert format_rupees(250000) == "₹2,50,000"
    assert format_rupees(12000000) == "₹1,20,00,000"
    assert format_rupees(999) == "₹999"


def test_rule_value_default_is_empty() -> None:
    assert RuleValue[int]().value is None
