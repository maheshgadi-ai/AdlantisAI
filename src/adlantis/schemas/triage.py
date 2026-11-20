"""Inputs and outputs of claim triage, which sorts rejected claims by what they mean."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from adlantis.schemas.brand import BrandKit
from adlantis.schemas.facts import FactSheet
from adlantis.schemas.product import ProductBrief

TriageCategory = Literal["call_to_action", "supported_by_fact", "not_supported"]


class TriageItem(BaseModel):
    """The checker's reading of one rejected statement."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(description="The statement's number in the list.")
    category: TriageCategory
    fact_ids: list[str] = Field(
        default_factory=list,
        description="For supported_by_fact: the fact IDs or glossary terms that state it.",
    )
    reason: str


class TriageDraft(BaseModel):
    """Every reading the checker returns."""

    model_config = ConfigDict(extra="forbid")

    items: list[TriageItem] = Field(default_factory=list)


class TriageRequest(BaseModel):
    """Rejected statements and the approved material to read them against."""

    model_config = ConfigDict(extra="forbid")

    brand: BrandKit
    product: ProductBrief
    facts: FactSheet
    today: date
    claims: list[str] = Field(min_length=1)
