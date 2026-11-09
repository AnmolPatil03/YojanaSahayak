"""Choose the one follow-up question that settles the most eligibility verdicts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from yojana.agent.eligibility import SchemeEligibility, format_rupees
from yojana.taxonomy import EDUCATION_LEVELS, OCCUPATIONS, STATES

_PRIORITY = [
    "state",
    "age",
    "annual_family_income",
    "social_category",
    "gender",
    "occupation",
    "education_level",
    "residence",
    "disability",
]

_QUESTIONS: dict[str, dict[str, str]] = {
    "age": {"en": "How old are you?", "hi": "आपकी उम्र कितनी है?"},
    "gender": {"en": "What is your gender?", "hi": "आपका लिंग क्या है?"},
    "state": {"en": "Which state do you live in?", "hi": "आप किस राज्य में रहते हैं?"},
    "annual_family_income": {
        "en": "What is your family's annual income?",
        "hi": "आपके परिवार की सालाना आय कितनी है?",
    },
    "social_category": {
        "en": "Which social category do you belong to?",
        "hi": "आप किस सामाजिक वर्ग से हैं?",
    },
    "occupation": {"en": "What do you do for a living?", "hi": "आप क्या काम करते हैं?"},
    "education_level": {
        "en": "What is your highest level of education?",
        "hi": "आपकी सबसे ऊँची शिक्षा क्या है?",
    },
    "disability": {"en": "Do you have a disability?", "hi": "क्या आप दिव्यांग हैं?"},
    "residence": {
        "en": "Do you live in a rural or an urban area?",
        "hi": "आप गाँव में रहते हैं या शहर में?",
    },
}

_CHOICE_LABELS: dict[str, dict[str, tuple[str, str]]] = {
    "gender": {
        "female": ("Female", "महिला"),
        "male": ("Male", "पुरुष"),
        "transgender": ("Transgender", "ट्रांसजेंडर"),
    },
    "social_category": {
        "general": ("General", "सामान्य"),
        "obc": ("OBC", "ओबीसी"),
        "sc": ("SC", "अनुसूचित जाति"),
        "st": ("ST", "अनुसूचित जनजाति"),
        "ews": ("EWS", "ईडब्ल्यूएस"),
        "minority": ("Minority", "अल्पसंख्यक"),
    },
    "residence": {"rural": ("Rural", "ग्रामीण"), "urban": ("Urban", "शहरी")},
    "disability": {"yes": ("Yes", "हाँ"), "no": ("No", "नहीं")},
    "education_level": {
        "below_10th": ("Below 10th", "10वीं से कम"),
        "10th": ("10th pass", "10वीं पास"),
        "12th": ("12th pass", "12वीं पास"),
        "diploma": ("Diploma / ITI", "डिप्लोमा / आईटीआई"),
        "graduate": ("Graduate", "स्नातक"),
        "postgraduate": ("Postgraduate", "स्नातकोत्तर"),
        "phd": ("PhD", "पीएचडी"),
    },
    "occupation": {
        "student": ("Student", "छात्र"),
        "farmer": ("Farmer", "किसान"),
        "entrepreneur": ("Entrepreneur", "उद्यमी"),
        "self_employed": ("Self-employed", "स्वरोज़गार"),
        "salaried": ("Salaried", "नौकरीपेशा"),
        "unemployed": ("Unemployed", "बेरोज़गार"),
        "labourer": ("Labourer", "मज़दूर"),
        "artisan": ("Artisan", "कारीगर"),
        "fisherman": ("Fisher", "मछुआरा"),
        "homemaker": ("Homemaker", "गृहिणी"),
        "retired": ("Retired", "सेवानिवृत्त"),
    },
}


class QuickReply(BaseModel):
    label: str
    label_hi: str
    value: Any


class ClarifyQuestion(BaseModel):
    """A follow-up question with optional quick replies."""

    field: str
    question: str
    question_hi: str
    input: str = "choice"
    options: list[QuickReply] = Field(default_factory=list)
    resolves: int = 0
    affects: int = 0


def _lakh(amount: int) -> str:
    lakhs = amount / 100_000
    return f"{lakhs:g} lakh" if amount >= 100_000 else format_rupees(amount)


def _income_options(thresholds: list[int]) -> list[QuickReply]:
    """Buckets whose edges are the income limits of the schemes still in play."""
    options: list[QuickReply] = []
    previous: int | None = None
    for limit in thresholds:
        if previous is None:
            label, label_hi = f"Up to ₹{_lakh(limit)}", f"₹{_lakh(limit)} तक"
        else:
            label = f"₹{_lakh(previous)} – ₹{_lakh(limit)}"
            label_hi = label
        options.append(QuickReply(label=label, label_hi=label_hi, value=limit))
        previous = limit
    if previous is not None:
        options.append(
            QuickReply(
                label=f"Above ₹{_lakh(previous)}",
                label_hi=f"₹{_lakh(previous)} से अधिक",
                value=previous + 1,
            )
        )
    return options


def _choice_options(field: str, values: list[str]) -> list[QuickReply]:
    labels = _CHOICE_LABELS.get(field, {})
    return [
        QuickReply(label=labels.get(v, (v, v))[0], label_hi=labels.get(v, (v, v))[1], value=v)
        for v in values
    ]


def _options_for(field: str, verdicts: Sequence[SchemeEligibility]) -> tuple[str, list[QuickReply]]:
    expected: list[Any] = []
    for verdict in verdicts:
        for criterion in verdict.criteria:
            if criterion.field == field and criterion.status == "unknown":
                expected.extend(criterion.expected_values)

    if field == "annual_family_income":
        thresholds = sorted({int(v) for v in expected if isinstance(v, int)})
        return "choice", _income_options(thresholds)
    if field == "age":
        return "number", []
    if field == "disability":
        return "choice", [
            QuickReply(label="Yes", label_hi="हाँ", value=True),
            QuickReply(label="No", label_hi="नहीं", value=False),
        ]
    if field == "state":
        mentioned = [s for s in dict.fromkeys(str(v) for v in expected) if s in STATES][:6]
        return "choice", [QuickReply(label=s, label_hi=STATES[s][-1], value=s) for s in mentioned]
    vocab = {
        "gender": ["female", "male", "transgender"],
        "social_category": ["general", "obc", "sc", "st", "ews", "minority"],
        "residence": ["rural", "urban"],
        "education_level": EDUCATION_LEVELS,
        "occupation": OCCUPATIONS,
    }.get(field, [])
    if field in ("occupation", "education_level"):
        wanted = set(map(str, expected))
        ordered = [v for v in vocab if v in wanted]
        others = [v for v in vocab if v not in wanted]
        values = (ordered + others)[:6]
        return "choice", _choice_options(field, values)
    return "choice", _choice_options(field, vocab)


def select_question(
    verdicts: Sequence[SchemeEligibility],
    *,
    asked: Sequence[str] = (),
) -> ClarifyQuestion | None:
    """Pick the profile field whose answer makes the most verdicts definite.

    A scheme becomes definite when the field is its only unanswered criterion
    (whatever the answer, it ends up eligible or ineligible). Schemes where the
    field is one of several unknowns can only become definite if the answer rules
    them out, so they break ties. Already-ineligible schemes are ignored, and
    fields asked earlier in the conversation are skipped.
    """
    open_verdicts = [v for v in verdicts if v.verdict == "partial"]
    if not open_verdicts:
        return None
    scores: dict[str, tuple[int, int]] = {}
    for verdict in open_verdicts:
        missing = set(verdict.missing_fields) - set(asked)
        for field in missing:
            full, partial = scores.get(field, (0, 0))
            if missing == {field}:
                full += 1
            else:
                partial += 1
            scores[field] = (full, partial)
    if not scores:
        return None
    best = max(
        scores,
        key=lambda f: (
            scores[f][0],
            scores[f][1],
            -_PRIORITY.index(f) if f in _PRIORITY else -99,
        ),
    )
    kind, options = _options_for(best, open_verdicts)
    return ClarifyQuestion(
        field=best,
        question=_QUESTIONS[best]["en"],
        question_hi=_QUESTIONS[best]["hi"],
        input=kind,
        options=options,
        resolves=scores[best][0],
        affects=scores[best][0] + scores[best][1],
    )
