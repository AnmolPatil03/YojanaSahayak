"""Eligibility rule models and the on-disk store for reviewed rules."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, field_validator

from yojana.agent.slots import (
    normalize_category,
    normalize_education,
    normalize_gender,
    normalize_occupation,
    normalize_residence,
)
from yojana.taxonomy import ALL_STATES, normalize_state

V = TypeVar("V")


class RuleValue(BaseModel, Generic[V]):
    """A rule value together with the chunk it was read from."""

    value: V | None = None
    chunk_id: str | None = None


class OtherCondition(BaseModel):
    text: str
    chunk_id: str | None = None


def _normalize_list(values: Any, normalizer: Any) -> list[str] | None:
    if values is None:
        return None
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    for item in values:
        norm = normalizer(item)
        if norm and norm not in out:
            out.append(norm)
    return out or None


class EligibilityRules(BaseModel):
    """Structured eligibility criteria for one scheme. `None` means not stated."""

    min_age: RuleValue[int] = Field(default_factory=RuleValue[int])
    max_age: RuleValue[int] = Field(default_factory=RuleValue[int])
    genders: RuleValue[list[str]] = Field(default_factory=RuleValue[list[str]])
    states: RuleValue[list[str]] = Field(default_factory=RuleValue[list[str]])
    max_annual_family_income: RuleValue[int] = Field(default_factory=RuleValue[int])
    social_categories: RuleValue[list[str]] = Field(default_factory=RuleValue[list[str]])
    occupations: RuleValue[list[str]] = Field(default_factory=RuleValue[list[str]])
    education_levels: RuleValue[list[str]] = Field(default_factory=RuleValue[list[str]])
    disability_required: RuleValue[bool] = Field(default_factory=RuleValue[bool])
    residence: RuleValue[str] = Field(default_factory=RuleValue[str])
    other_conditions: list[OtherCondition] = Field(default_factory=list)

    @field_validator("genders", mode="after")
    @classmethod
    def _genders(cls, v: RuleValue[list[str]]) -> RuleValue[list[str]]:
        return RuleValue[list[str]](
            value=_normalize_list(v.value, normalize_gender), chunk_id=v.chunk_id
        )

    @field_validator("states", mode="after")
    @classmethod
    def _states(cls, v: RuleValue[list[str]]) -> RuleValue[list[str]]:
        states = _normalize_list(v.value, normalize_state)
        if states and ALL_STATES in states:
            states = None
        return RuleValue[list[str]](value=states, chunk_id=v.chunk_id)

    @field_validator("social_categories", mode="after")
    @classmethod
    def _categories(cls, v: RuleValue[list[str]]) -> RuleValue[list[str]]:
        return RuleValue[list[str]](
            value=_normalize_list(v.value, normalize_category), chunk_id=v.chunk_id
        )

    @field_validator("occupations", mode="after")
    @classmethod
    def _occupations(cls, v: RuleValue[list[str]]) -> RuleValue[list[str]]:
        return RuleValue[list[str]](
            value=_normalize_list(v.value, normalize_occupation), chunk_id=v.chunk_id
        )

    @field_validator("education_levels", mode="after")
    @classmethod
    def _education(cls, v: RuleValue[list[str]]) -> RuleValue[list[str]]:
        return RuleValue[list[str]](
            value=_normalize_list(v.value, normalize_education), chunk_id=v.chunk_id
        )

    @field_validator("residence", mode="after")
    @classmethod
    def _residence(cls, v: RuleValue[str]) -> RuleValue[str]:
        return RuleValue[str](value=normalize_residence(v.value), chunk_id=v.chunk_id)

    def cited_chunk_ids(self) -> set[str]:
        ids = {
            getattr(self, name).chunk_id
            for name in RULE_FIELDS
            if getattr(self, name).chunk_id and getattr(self, name).value is not None
        }
        ids.update(c.chunk_id for c in self.other_conditions if c.chunk_id)
        return {i for i in ids if i}

    def is_empty(self) -> bool:
        return (
            all(getattr(self, n).value is None for n in RULE_FIELDS) and not self.other_conditions
        )


RULE_FIELDS = (
    "min_age",
    "max_age",
    "genders",
    "states",
    "max_annual_family_income",
    "social_categories",
    "occupations",
    "education_levels",
    "disability_required",
    "residence",
)


class RulesRecord(BaseModel):
    """Rules for one scheme plus review status and provenance."""

    scheme_id: str
    scheme_name: str
    rules: EligibilityRules
    needs_review: bool = True
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    extracted_at: str | None = None
    extracted_by: str | None = None
    content_hash: str | None = None
    source_chunk_ids: list[str] = Field(default_factory=list)
    previous: EligibilityRules | None = None
    notes: str | None = None

    def mark_reviewed(self, reviewer: str | None = None) -> None:
        self.needs_review = False
        self.reviewed_at = datetime.now(UTC).isoformat(timespec="seconds")
        self.reviewed_by = reviewer


class RulesStore:
    """Rules as one JSON file per scheme under `data/processed/rules/`."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, scheme_id: str) -> Path:
        return self.directory / f"{scheme_id}.json"

    def get(self, scheme_id: str) -> RulesRecord | None:
        path = self.path(scheme_id)
        if not path.is_file():
            return None
        return RulesRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, record: RulesRecord) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.path(record.scheme_id).with_suffix(".tmp")
        tmp.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path(record.scheme_id))

    def all(self) -> list[RulesRecord]:
        if not self.directory.is_dir():
            return []
        return [
            RulesRecord.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted(self.directory.glob("*.json"))
        ]

    def usable(self, scheme_id: str, *, allow_unreviewed: bool) -> RulesRecord | None:
        """Rules the engine may use: reviewed ones, or any when explicitly allowed."""
        record = self.get(scheme_id)
        if record is None or (record.needs_review and not allow_unreviewed):
            return None
        return record

    def install_samples(self, sample_rules_dir: Path) -> int:
        """Copy the hand-reviewed rules for the fictional sample schemes."""
        if not sample_rules_dir.is_dir():
            return 0
        self.directory.mkdir(parents=True, exist_ok=True)
        count = 0
        for source in sorted(sample_rules_dir.glob("*.json")):
            shutil.copyfile(source, self.directory / source.name)
            count += 1
        return count
