from __future__ import annotations

import pytest

from yojana.agent.slots import UserProfile, extract_profile, parse_amount


def test_extracts_a_full_english_profile() -> None:
    profile = extract_profile(
        "I'm a 22 year old SC female student from Bihar, doing B.Tech, "
        "family income is 1.8 lakh, we live in a village"
    )
    assert profile == UserProfile(
        age=22,
        gender="female",
        state="Bihar",
        annual_family_income=180000,
        social_category="sc",
        occupation="student",
        education_level="graduate",
        residence="rural",
    )


def test_extracts_hindi_profile() -> None:
    profile = extract_profile("मैं 35 साल का किसान हूँ, महाराष्ट्र के गाँव में रहता हूँ, आय 2 लाख है")
    assert profile.age == 35
    assert profile.occupation == "farmer"
    assert profile.state == "Maharashtra"
    assert profile.residence == "rural"
    assert profile.annual_family_income == 200000


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("family income ₹2,50,000 per year", 250000),
        ("annual income of Rs. 3 lakh", 300000),
        ("my income is 15000 per month", 180000),
        ("earning 50k", 50000),
        ("income 1.2 crore", 12000000),
    ],
)
def test_income_parsing(text: str, expected: int) -> None:
    assert extract_profile(text).annual_family_income == expected


def test_bsc_and_ordinals_are_not_read_as_categories() -> None:
    profile = extract_profile("I finished B.Sc in 1st division")
    assert profile.social_category is None
    assert profile.education_level == "graduate"


def test_disability_negation() -> None:
    assert extract_profile("I have no disability").disability is False
    assert extract_profile("I am a divyang person").disability is True
    assert extract_profile("hello").disability is None


def test_nothing_found_is_empty() -> None:
    assert extract_profile("What schemes exist?").is_empty()


def test_profile_normalises_values_and_merges() -> None:
    base = UserProfile(gender="Woman", social_category="Scheduled Caste", state="kerala")
    assert (base.gender, base.social_category, base.state) == ("female", "sc", "Kerala")
    merged = base.merged(UserProfile(age=30, state="Goa"))
    assert merged.age == 30 and merged.state == "Goa" and merged.gender == "female"
    assert merged.known_fields() == ["age", "gender", "state", "social_category"]


def test_profile_rejects_impossible_age() -> None:
    with pytest.raises(ValueError):
        UserProfile(age=400)


def test_parse_amount() -> None:
    assert parse_amount("2,50,000", None) == 250000
    assert parse_amount("2.5", "lakh") == 250000
    assert parse_amount("x", None) is None
