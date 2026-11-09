from __future__ import annotations

from yojana.agent.eligibility import evaluate
from yojana.agent.questions import select_question
from yojana.agent.slots import UserProfile
from yojana.rules import EligibilityRules, RulesRecord


def scheme(sid: str, **fields: object) -> RulesRecord:
    rules = EligibilityRules.model_validate(
        {k: {"value": v, "chunk_id": f"{sid}::c"} for k, v in fields.items()}
    )
    return RulesRecord(scheme_id=sid, scheme_name=sid, rules=rules, needs_review=False)


def verdicts(profile: UserProfile, *records: RulesRecord):
    return [evaluate(r, profile) for r in records]


def test_picks_field_that_resolves_most_schemes() -> None:
    results = verdicts(
        UserProfile(),
        scheme("a", max_annual_family_income=250000),
        scheme("b", max_annual_family_income=800000),
        scheme("c", min_age=18),
        scheme("d", min_age=18, genders=["female"]),
    )
    question = select_question(results)
    assert question is not None
    assert question.field == "annual_family_income"
    assert question.resolves == 2


def test_partial_counts_break_ties() -> None:
    results = verdicts(
        UserProfile(),
        scheme("a", min_age=18),
        scheme("b", genders=["female"]),
        scheme("c", genders=["female"], states=["Goa"]),
    )
    question = select_question(results)
    assert question is not None and question.field == "gender"
    assert (question.resolves, question.affects) == (1, 2)


def test_priority_breaks_remaining_ties() -> None:
    results = verdicts(UserProfile(), scheme("a", genders=["female"]), scheme("b", min_age=18))
    question = select_question(results)
    assert question is not None and question.field == "age"
    assert question.input == "number" and question.options == []


def test_ineligible_and_definite_schemes_are_ignored() -> None:
    results = verdicts(
        UserProfile(age=10),
        scheme("a", min_age=18, genders=["female"]),
        scheme("b", min_age=5),
    )
    assert select_question(results) is None


def test_already_asked_fields_are_skipped() -> None:
    results = verdicts(UserProfile(), scheme("a", min_age=18, residence="rural"))
    question = select_question(results, asked=["age"])
    assert question is not None and question.field == "residence"
    assert [o.value for o in question.options] == ["rural", "urban"]


def test_income_options_follow_scheme_thresholds() -> None:
    results = verdicts(
        UserProfile(),
        scheme("a", max_annual_family_income=250000),
        scheme("b", max_annual_family_income=800000),
    )
    question = select_question(results)
    assert question is not None
    assert [o.value for o in question.options] == [250000, 800000, 800001]
    assert question.options[0].label == "Up to ₹2.5 lakh"
    assert question.options[-1].label == "Above ₹8 lakh"


def test_categorical_options_and_hindi_text() -> None:
    results = verdicts(UserProfile(), scheme("a", social_categories=["sc", "st"]))
    question = select_question(results)
    assert question is not None
    assert question.question_hi == "आप किस सामाजिक वर्ग से हैं?"
    assert {o.value for o in question.options} >= {"sc", "st", "general"}


def test_disability_options_are_booleans() -> None:
    results = verdicts(UserProfile(), scheme("a", disability_required=True))
    question = select_question(results)
    assert question is not None
    assert [o.value for o in question.options] == [True, False]


def test_state_options_come_from_rules() -> None:
    results = verdicts(UserProfile(), scheme("a", states=["Kerala"]), scheme("b", states=["Goa"]))
    question = select_question(results)
    assert question is not None and question.field == "state"
    assert [o.value for o in question.options] == ["Kerala", "Goa"]


def test_answering_the_question_makes_verdicts_definite() -> None:
    records = [
        scheme("a", max_annual_family_income=250000),
        scheme("b", max_annual_family_income=800000),
    ]
    question = select_question(verdicts(UserProfile(), *records))
    assert question is not None
    chosen = question.options[1].value
    after = verdicts(UserProfile(annual_family_income=chosen), *records)
    assert [v.verdict for v in after] == ["ineligible", "eligible"]
