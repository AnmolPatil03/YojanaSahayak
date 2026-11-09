"""Shared vocabularies: states, scheme sections, categories and profile values.

These are lookup tables for normalising text, not scheme facts.
"""

from __future__ import annotations

import re
import unicodedata

STATES: dict[str, list[str]] = {
    "Andhra Pradesh": ["andhra pradesh", "आंध्र प्रदेश"],
    "Arunachal Pradesh": ["arunachal pradesh", "अरुणाचल प्रदेश"],
    "Assam": ["assam", "असम"],
    "Bihar": ["bihar", "बिहार"],
    "Chhattisgarh": ["chhattisgarh", "छत्तीसगढ़"],
    "Goa": ["goa", "गोवा"],
    "Gujarat": ["gujarat", "गुजरात"],
    "Haryana": ["haryana", "हरियाणा"],
    "Himachal Pradesh": ["himachal pradesh", "हिमाचल प्रदेश"],
    "Jharkhand": ["jharkhand", "झारखंड"],
    "Karnataka": ["karnataka", "कर्नाटक"],
    "Kerala": ["kerala", "केरल"],
    "Madhya Pradesh": ["madhya pradesh", "मध्य प्रदेश"],
    "Maharashtra": ["maharashtra", "महाराष्ट्र"],
    "Manipur": ["manipur", "मणिपुर"],
    "Meghalaya": ["meghalaya", "मेघालय"],
    "Mizoram": ["mizoram", "मिज़ोरम", "मिजोरम"],
    "Nagaland": ["nagaland", "नागालैंड"],
    "Odisha": ["odisha", "orissa", "ओडिशा"],
    "Punjab": ["punjab", "पंजाब"],
    "Rajasthan": ["rajasthan", "राजस्थान"],
    "Sikkim": ["sikkim", "सिक्किम"],
    "Tamil Nadu": ["tamil nadu", "तमिलनाडु", "तमिल नाडु"],
    "Telangana": ["telangana", "तेलंगाना"],
    "Tripura": ["tripura", "त्रिपुरा"],
    "Uttar Pradesh": ["uttar pradesh", "उत्तर प्रदेश"],
    "Uttarakhand": ["uttarakhand", "उत्तराखंड"],
    "West Bengal": ["west bengal", "पश्चिम बंगाल"],
    "Andaman and Nicobar Islands": ["andaman and nicobar", "andaman", "अंडमान"],
    "Chandigarh": ["chandigarh", "चंडीगढ़"],
    "Dadra and Nagar Haveli and Daman and Diu": ["dadra", "daman and diu", "दादरा"],
    "Delhi": ["delhi", "new delhi", "दिल्ली"],
    "Jammu and Kashmir": ["jammu and kashmir", "jammu & kashmir", "जम्मू"],
    "Ladakh": ["ladakh", "लद्दाख"],
    "Lakshadweep": ["lakshadweep", "लक्षद्वीप"],
    "Puducherry": ["puducherry", "pondicherry", "पुडुचेरी"],
}

ALL_STATES = "ALL"

SECTIONS: dict[str, dict[str, str]] = {
    "overview": {"en": "Overview", "hi": "विवरण"},
    "benefits": {"en": "Benefits", "hi": "लाभ"},
    "eligibility": {"en": "Eligibility", "hi": "पात्रता"},
    "exclusions": {"en": "Exclusions", "hi": "अपवर्जन"},
    "documents": {"en": "Documents Required", "hi": "आवश्यक दस्तावेज़"},
    "application": {"en": "How to Apply", "hi": "आवेदन कैसे करें"},
    "faq": {"en": "FAQ", "hi": "सामान्य प्रश्न"},
    "other": {"en": "Other", "hi": "अन्य"},
}

_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "documents",
        re.compile(r"document|papers required|checklist|दस्तावेज|दस्तावेज़|कागजात|प्रमाण पत्र", re.I),
    ),
    ("exclusions", re.compile(r"exclusion|not eligible|ineligib|अपवर्जन|अपात्र|बहिष्कर", re.I)),
    ("eligibility", re.compile(r"eligib|who can apply|criteria|पात्रता|योग्यता|कौन आवेदन", re.I)),
    ("benefits", re.compile(r"benefit|assistance|entitlement|incentive|लाभ|सहायता|फायदे", re.I)),
    (
        "application",
        re.compile(r"how to apply|application|apply|procedure|process|आवेदन|प्रक्रिया|कैसे करें", re.I),
    ),
    ("faq", re.compile(r"faq|frequently asked|questions|सामान्य प्रश्न|प्रश्नोत्तर", re.I)),
    (
        "overview",
        re.compile(
            r"overview|details|about|introduction|description|objective|summary|"
            r"विवरण|परिचय|उद्देश्य|योजना के बारे",
            re.I,
        ),
    ),
]

CATEGORIES: dict[str, dict[str, str]] = {
    "education": {"en": "Education & Scholarships", "hi": "शिक्षा और छात्रवृत्ति"},
    "agriculture": {"en": "Agriculture & Farmers", "hi": "कृषि और किसान"},
    "business": {"en": "Business & Startups", "hi": "व्यवसाय और स्टार्टअप"},
    "women_child": {"en": "Women & Children", "hi": "महिला और बाल"},
    "disability": {"en": "Persons with Disabilities", "hi": "दिव्यांगजन"},
    "employment": {"en": "Skills & Employment", "hi": "कौशल और रोज़गार"},
    "health": {"en": "Health", "hi": "स्वास्थ्य"},
    "housing": {"en": "Housing", "hi": "आवास"},
    "social_welfare": {"en": "Social Welfare", "hi": "सामाजिक कल्याण"},
    "other": {"en": "Other", "hi": "अन्य"},
}

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "education": [
        "scholarship",
        "student",
        "education",
        "school",
        "college",
        "fellowship",
        "tuition",
        "छात्रवृत्ति",
        "छात्र",
        "शिक्षा",
        "विद्यार्थी",
    ],
    "agriculture": [
        "farmer",
        "agricultur",
        "crop",
        "kisan",
        "irrigation",
        "livestock",
        "fisher",
        "किसान",
        "कृषि",
        "फसल",
    ],
    "business": [
        "startup",
        "start-up",
        "entrepreneur",
        "enterprise",
        "msme",
        "business",
        "loan",
        "credit",
        "स्टार्टअप",
        "उद्यम",
        "व्यवसाय",
        "उद्यमी",
    ],
    "women_child": [
        "women",
        "woman",
        "girl",
        "mother",
        "maternity",
        "widow",
        "child",
        "महिला",
        "बालिका",
        "मातृ",
        "विधवा",
    ],
    "disability": [
        "disabilit",
        "divyang",
        "handicap",
        "pwd",
        "differently abled",
        "दिव्यांग",
        "विकलांग",
    ],
    "employment": [
        "skill",
        "employment",
        "job",
        "training",
        "apprentice",
        "कौशल",
        "रोजगार",
        "रोज़गार",
        "प्रशिक्षण",
    ],
    "health": ["health", "hospital", "medical", "insurance", "स्वास्थ्य", "चिकित्सा", "बीमा"],
    "housing": ["housing", "house", "awas", "shelter", "आवास", "मकान"],
    "social_welfare": ["pension", "welfare", "senior citizen", "old age", "पेंशन", "कल्याण"],
}

GENDERS = ["male", "female", "transgender"]
SOCIAL_CATEGORIES = ["general", "obc", "sc", "st", "ews", "minority"]
RESIDENCE = ["rural", "urban"]
EDUCATION_LEVELS = [
    "below_10th",
    "10th",
    "12th",
    "diploma",
    "graduate",
    "postgraduate",
    "phd",
]
OCCUPATIONS = [
    "student",
    "farmer",
    "entrepreneur",
    "self_employed",
    "salaried",
    "unemployed",
    "labourer",
    "artisan",
    "fisherman",
    "homemaker",
    "retired",
]

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_EDGE_BEFORE = r"(?<![\w\u0900-\u097F])"
_EDGE_AFTER = r"(?![\w\u0900-\u097F])"
_WS = re.compile(r"[ \t ​]+")
_NL = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """NFC-normalise, collapse runs of spaces and blank lines, strip each line."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WS.sub(" ", line).strip() for line in text.split("\n")]
    return _NL.sub("\n\n", "\n".join(lines)).strip()


def devanagari_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha() or _DEVANAGARI.match(c)]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _DEVANAGARI.match(c)) / len(letters)


def detect_script_language(text: str) -> str:
    """'hi' when the text is mostly Devanagari, otherwise 'en'."""
    return "hi" if devanagari_ratio(text) >= 0.3 else "en"


def canonical_section(heading: str) -> str | None:
    """Map a heading such as 'Documents Required' or 'पात्रता' to a section key."""
    cleaned = heading.strip().strip(":").strip()
    if not cleaned or len(cleaned) > 80:
        return None
    for key, pattern in _SECTION_PATTERNS:
        if pattern.search(cleaned):
            return key
    return None


def section_label(key: str, language: str = "en") -> str:
    return SECTIONS.get(key, SECTIONS["other"]).get(language, key)


def find_states(text: str) -> list[str]:
    """Return canonical state names mentioned in text, in order of first mention."""
    lowered = text.lower()
    hits: list[tuple[int, str]] = []
    for state, aliases in STATES.items():
        positions = [
            m.start()
            for alias in aliases
            for m in re.finditer(_EDGE_BEFORE + re.escape(alias) + _EDGE_AFTER, lowered)
        ]
        if positions:
            hits.append((min(positions), state))
    return [state for _, state in sorted(hits)]


def normalize_state(value: str | None) -> str | None:
    if not value:
        return None
    if value.strip().upper() == ALL_STATES:
        return ALL_STATES
    found = find_states(value)
    return found[0] if found else None


def score_categories(text: str) -> dict[str, int]:
    lowered = text.lower()
    return {
        key: sum(lowered.count(word) for word in words)
        for key, words in _CATEGORY_KEYWORDS.items()
        if any(word in lowered for word in words)
    }


def guess_category(text: str) -> str:
    """Pick the category whose keywords appear most often; 'other' if none do."""
    scores = score_categories(text)
    if not scores:
        return "other"
    return max(scores.items(), key=lambda item: item[1])[0]


def slugify(text: str, max_length: int = 80) -> str:
    """ASCII-ish slug that keeps Devanagari letters intact."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\u0900-\u097F]+", "-", text).strip("-")
    return text[:max_length].strip("-") or "item"
