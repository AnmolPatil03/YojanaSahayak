"""The user's eligibility profile and deterministic slot extraction from messages."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from yojana.taxonomy import (
    EDUCATION_LEVELS,
    OCCUPATIONS,
    SOCIAL_CATEGORIES,
    find_states,
    normalize_state,
)

ProfileField = Literal[
    "age",
    "gender",
    "state",
    "annual_family_income",
    "social_category",
    "occupation",
    "education_level",
    "disability",
    "residence",
]
PROFILE_FIELDS: tuple[ProfileField, ...] = (
    "age",
    "gender",
    "state",
    "annual_family_income",
    "social_category",
    "occupation",
    "education_level",
    "disability",
    "residence",
)

_GENDER_SYNONYMS = {
    "female": "female",
    "woman": "female",
    "women": "female",
    "girl": "female",
    "f": "female",
    "male": "male",
    "man": "male",
    "men": "male",
    "boy": "male",
    "m": "male",
    "transgender": "transgender",
    "trans": "transgender",
    "third gender": "transgender",
}
_CATEGORY_SYNONYMS = {
    "sc": "sc",
    "scheduled caste": "sc",
    "scheduled castes": "sc",
    "st": "st",
    "scheduled tribe": "st",
    "scheduled tribes": "st",
    "obc": "obc",
    "other backward class": "obc",
    "other backward classes": "obc",
    "ews": "ews",
    "economically weaker section": "ews",
    "general": "general",
    "gen": "general",
    "open": "general",
    "minority": "minority",
    "minorities": "minority",
}
_EDUCATION_SYNONYMS = {
    "below 10th": "below_10th",
    "below_10th": "below_10th",
    "10th": "10th",
    "class 10": "10th",
    "matric": "10th",
    "ssc": "10th",
    "secondary": "10th",
    "12th": "12th",
    "class 12": "12th",
    "hsc": "12th",
    "intermediate": "12th",
    "higher secondary": "12th",
    "diploma": "diploma",
    "iti": "diploma",
    "polytechnic": "diploma",
    "graduate": "graduate",
    "graduation": "graduate",
    "undergraduate": "graduate",
    "bachelor": "graduate",
    "degree": "graduate",
    "postgraduate": "postgraduate",
    "post graduate": "postgraduate",
    "post-graduate": "postgraduate",
    "master": "postgraduate",
    "masters": "postgraduate",
    "phd": "phd",
    "doctorate": "phd",
}
_OCCUPATION_SYNONYMS = {
    "student": "student",
    "farmer": "farmer",
    "cultivator": "farmer",
    "agriculturist": "farmer",
    "entrepreneur": "entrepreneur",
    "startup founder": "entrepreneur",
    "founder": "entrepreneur",
    "self employed": "self_employed",
    "self-employed": "self_employed",
    "self_employed": "self_employed",
    "salaried": "salaried",
    "employee": "salaried",
    "unemployed": "unemployed",
    "job seeker": "unemployed",
    "labourer": "labourer",
    "laborer": "labourer",
    "worker": "labourer",
    "artisan": "artisan",
    "weaver": "artisan",
    "craftsman": "artisan",
    "fisherman": "fisherman",
    "fisher": "fisherman",
    "homemaker": "homemaker",
    "housewife": "homemaker",
    "retired": "retired",
    "pensioner": "retired",
}


def normalize_choice(value: Any, synonyms: dict[str, str], allowed: list[str]) -> str | None:
    """Map free text such as 'Scheduled Caste' onto a vocabulary value like 'sc'."""
    if value is None:
        return None
    text = str(value).strip().lower().replace("_", " ")
    if not text:
        return None
    if text.replace(" ", "_") in allowed:
        return text.replace(" ", "_")
    return synonyms.get(text)


def normalize_gender(value: Any) -> str | None:
    return normalize_choice(value, _GENDER_SYNONYMS, ["male", "female", "transgender"])


def normalize_category(value: Any) -> str | None:
    return normalize_choice(value, _CATEGORY_SYNONYMS, SOCIAL_CATEGORIES)


def normalize_education(value: Any) -> str | None:
    return normalize_choice(value, _EDUCATION_SYNONYMS, EDUCATION_LEVELS)


def normalize_occupation(value: Any) -> str | None:
    return normalize_choice(value, _OCCUPATION_SYNONYMS, OCCUPATIONS)


def normalize_residence(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in ("rural", "village"):
        return "rural"
    if text in ("urban", "city", "town"):
        return "urban"
    return None


class UserProfile(BaseModel):
    """What the user has told us about themselves. Every field is optional."""

    age: int | None = Field(default=None, ge=0, le=120)
    gender: str | None = None
    state: str | None = None
    annual_family_income: int | None = Field(default=None, ge=0)
    social_category: str | None = None
    occupation: str | None = None
    education_level: str | None = None
    disability: bool | None = None
    residence: str | None = None

    @field_validator("gender", mode="before")
    @classmethod
    def _gender(cls, v: Any) -> str | None:
        return normalize_gender(v)

    @field_validator("state", mode="before")
    @classmethod
    def _state(cls, v: Any) -> str | None:
        state = normalize_state(v) if v else None
        return None if state == "ALL" else state

    @field_validator("social_category", mode="before")
    @classmethod
    def _category(cls, v: Any) -> str | None:
        return normalize_category(v)

    @field_validator("occupation", mode="before")
    @classmethod
    def _occupation(cls, v: Any) -> str | None:
        return normalize_occupation(v)

    @field_validator("education_level", mode="before")
    @classmethod
    def _education(cls, v: Any) -> str | None:
        return normalize_education(v)

    @field_validator("residence", mode="before")
    @classmethod
    def _residence(cls, v: Any) -> str | None:
        return normalize_residence(v)

    def is_empty(self) -> bool:
        return all(getattr(self, f) is None for f in PROFILE_FIELDS)

    def known_fields(self) -> list[str]:
        return [f for f in PROFILE_FIELDS if getattr(self, f) is not None]

    def merged(self, update: UserProfile | dict[str, Any]) -> UserProfile:
        """Return a copy where non-empty values in `update` replace ours."""
        values = update.model_dump() if isinstance(update, UserProfile) else dict(update)
        data = self.model_dump()
        for key, value in values.items():
            if key in data and value is not None:
                data[key] = value
        return UserProfile.model_validate(data)


_AGE = [
    re.compile(r"\b(?:age|aged)\s*(?:is|:|of)?\s*(\d{1,3})\b", re.I),
    re.compile(r"\b(\d{1,3})\s*(?:years?|yrs?)(?:\s*old)?\b", re.I),
    re.compile(r"\b(\d{1,3})[- ]year[- ]old\b", re.I),
    re.compile(r"\bi\s*(?:am|'m)\s*(\d{1,3})\b", re.I),
    re.compile(r"(\d{1,3})\s*(?:वर्ष|साल)"),
    re.compile(r"(?:उम्र|आयु)\s*(?:है)?\s*(\d{1,3})"),
]
_INCOME = re.compile(
    r"(?:income|earn(?:s|ing)?|salary|आय|कमाई|आमदनी)[^\d₹]{0,30}"
    r"(?:₹|rs\.?|inr|रु\.?|रुपये)?\s*(\d[\d,]*(?:\.\d+)?)\s*"
    r"(lakhs?|lacs?|lpa|लाख|crores?|करोड़|k\b|thousand|हज़ार|हजार)?",
    re.I,
)
_INCOME_TRAILING = re.compile(
    r"(?:₹|rs\.?|inr)\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|lpa|crores?|k\b|thousand)?"
    r"[^.\n]{0,40}(?:income|per year|annual|a year|p\.?a\.?)",
    re.I,
)
_UNIT = {
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "lpa": 100_000,
    "लाख": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "करोड़": 10_000_000,
    "k": 1_000,
    "thousand": 1_000,
    "हज़ार": 1_000,
    "हजार": 1_000,
}
_MONTHLY = re.compile(r"per month|a month|monthly|/month|महीना|मासिक|प्रति माह", re.I)

_KEYWORDS: dict[str, list[tuple[re.Pattern[str], Any]]] = {
    "gender": [
        (re.compile(r"\b(woman|women|female|girl|lady|widow|mother|daughter)\b", re.I), "female"),
        (re.compile(r"महिला|लड़की|स्त्री|विधवा|बेटी"), "female"),
        (re.compile(r"\btrans(?:gender)?\b|third gender|किन्नर|ट्रांसजेंडर", re.I), "transgender"),
        (re.compile(r"\b(man|male|boy|son)\b", re.I), "male"),
        (re.compile(r"पुरुष|लड़का|बेटा"), "male"),
    ],
    "social_category": [
        (re.compile(r"(?i:\bscheduled\s+tribes?\b)|(?<![.\w])ST\b|अनुसूचित जनजाति"), "st"),
        (re.compile(r"(?i:\bscheduled\s+castes?\b)|(?<![.\w])SC\b|अनुसूचित जाति"), "sc"),
        (re.compile(r"\bOBC\b|other backward|पिछड़ा वर्ग|ओबीसी", re.I), "obc"),
        (re.compile(r"\bEWS\b|economically weaker|आर्थिक रूप से कमजोर", re.I), "ews"),
        (re.compile(r"\bminority\b|अल्पसंख्यक", re.I), "minority"),
        (re.compile(r"\bgeneral category\b|\bgeneral caste\b|सामान्य वर्ग", re.I), "general"),
    ],
    "occupation": [
        (re.compile(r"\bstudent\b|\bstudying\b|छात्र|छात्रा|विद्यार्थी|पढ़ाई", re.I), "student"),
        (re.compile(r"\bfarmer\b|\bfarming\b|\bkisan\b|किसान|खेती", re.I), "farmer"),
        (
            re.compile(r"\bentrepreneur\b|\bstart-?up\b|\bfounder\b|उद्यमी|स्टार्टअप", re.I),
            "entrepreneur",
        ),
        (re.compile(r"\bunemployed\b|\bjobless\b|बेरोजगार|बेरोज़गार", re.I), "unemployed"),
        (re.compile(r"\bself[- ]employed\b|स्वरोजगार", re.I), "self_employed"),
        (re.compile(r"\blabou?rer\b|daily wage|मजदूर|मज़दूर", re.I), "labourer"),
        (re.compile(r"\bartisan\b|\bweaver\b|कारीगर|बुनकर", re.I), "artisan"),
        (re.compile(r"\bfisher(?:man|men|folk)?\b|मछुआरा", re.I), "fisherman"),
        (re.compile(r"\bhomemaker\b|\bhousewife\b|गृहिणी", re.I), "homemaker"),
        (re.compile(r"\bretired\b|\bpensioner\b|सेवानिवृत्त", re.I), "retired"),
        (re.compile(r"\bsalaried\b|\bemployee\b|नौकरी करता|नौकरीपेशा", re.I), "salaried"),
    ],
    "education_level": [
        (re.compile(r"\bph\.?d\b|doctorate|पीएचडी", re.I), "phd"),
        (
            re.compile(
                r"\bpost[- ]?graduat\w*|\bmasters?\b|\bm\.?tech\b|\bmba\b|\bm\.?sc\b|"
                r"\bm\.?com\b|\bm\.?a\.?\b(?=\s)|स्नातकोत्तर",
                re.I,
            ),
            "postgraduate",
        ),
        (
            re.compile(
                r"\bgraduat\w*|\bundergrad\w*|\bbachelor\w*|\bb\.?tech\b|\bb\.?e\.?\b(?=\s)|"
                r"\bb\.?sc\b|\bb\.?com\b|\bb\.?a\.?\b(?=\s)|\bdegree\b|\bcollege\b|स्नातक",
                re.I,
            ),
            "graduate",
        ),
        (re.compile(r"\bdiploma\b|\bpolytechnic\b|\biti\b|डिप्लोमा", re.I), "diploma"),
        (re.compile(r"\b12th\b|\bclass 12\b|\bhsc\b|\bintermediate\b|12वीं|बारहवीं", re.I), "12th"),
        (re.compile(r"\b10th\b|\bclass 10\b|\bssc\b|\bmatric\w*|10वीं|दसवीं", re.I), "10th"),
    ],
    "residence": [
        (re.compile(r"\brural\b|\bvillage\b|गांव|गाँव|ग्रामीण", re.I), "rural"),
        (re.compile(r"\burban\b|\bcity\b|शहर|शहरी|नगर", re.I), "urban"),
    ],
}
_DISABILITY_NO = re.compile(
    r"\bno disabilit\w*|\bnot disabled\b|\bwithout (?:any )?disabilit\w*|दिव्यांग नहीं|विकलांग नहीं",
    re.I,
)
_DISABILITY_YES = re.compile(
    r"\bdisabilit\w*|\bdisabled\b|\bdivyang\b|\bhandicap\w*|\bwheelchair\b|"
    r"\bvisually impaired\b|\bblind\b|\bdeaf\b|दिव्यांग|विकलांग",
    re.I,
)


def parse_amount(number: str, unit: str | None) -> int | None:
    """'2,50,000' -> 250000, '2.5' + 'lakh' -> 250000."""
    try:
        value = float(number.replace(",", ""))
    except ValueError:
        return None
    multiplier = _UNIT.get((unit or "").lower().strip(), 1)
    return round(value * multiplier)


def _extract_income(text: str) -> int | None:
    match = _INCOME.search(text) or _INCOME_TRAILING.search(text)
    if not match:
        return None
    amount = parse_amount(match.group(1), match.group(2))
    if amount is None:
        return None
    window = text[match.start() : match.end() + 30]
    if _MONTHLY.search(window):
        amount *= 12
    return amount


def _extract_age(text: str) -> int | None:
    for pattern in _AGE:
        match = pattern.search(text)
        if match:
            age = int(match.group(1))
            if 0 < age <= 110:
                return age
    return None


def extract_profile(text: str) -> UserProfile:
    """Pull explicit profile facts out of one message with regular expressions.

    This runs on every turn, so the assistant still understands "I'm a 22 year old
    SC student from Bihar" when every LLM provider is unavailable.
    """
    values: dict[str, Any] = {}
    age = _extract_age(text)
    if age is not None:
        values["age"] = age
    income = _extract_income(text)
    if income is not None:
        values["annual_family_income"] = income
    states = find_states(text)
    if states:
        values["state"] = states[0]
    for field, patterns in _KEYWORDS.items():
        for pattern, value in patterns:
            if pattern.search(text):
                values[field] = value
                break
    if _DISABILITY_NO.search(text):
        values["disability"] = False
    elif _DISABILITY_YES.search(text):
        values["disability"] = True
    return UserProfile.model_validate(values)
