"""The brand kit (`brand.yaml`): voice, audience, and what the brand must never say."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from adlantis.schemas.claims import BANNABLE_CLAIM_TYPES, ClaimType


class BrandVoice(BaseModel):
    """How the brand sounds, with examples to imitate and avoid."""

    model_config = ConfigDict(extra="forbid")

    tone: list[str] = Field(min_length=1)
    do: list[str] = Field(min_length=1)
    dont: list[str] = Field(min_length=1)


class BrandColor(BaseModel):
    """A named brand color."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class Competitor(BaseModel):
    """A competitor that must never be disparaged, with any short names it goes by."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2)
    aliases: list[str] = Field(default_factory=list)
    common_word: bool = Field(
        default=False,
        description="The name is also an ordinary word, so lowercase uses are not mentions.",
    )

    @property
    def names(self) -> tuple[str, ...]:
        """The full name and every alias."""
        return (self.name, *self.aliases)


class GlossaryEntry(BaseModel):
    """An approved explanation of a term. Copy may use it, word for word, without a citation."""

    model_config = ConfigDict(extra="forbid")

    term: str = Field(min_length=2)
    definition: str = Field(min_length=1)

    @property
    def wording(self) -> str:
        """The only form in which copy may use this entry."""
        return f"{self.term}: {self.definition}"


class BrandKit(BaseModel):
    """Everything the campaign must respect about the brand."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    aliases: list[str] = Field(
        default_factory=list, description="Other names the brand goes by. Names are not claims."
    )
    voice: BrandVoice
    audience: str = Field(min_length=1)
    values: list[str] = Field(min_length=1)
    colors: list[BrandColor] = Field(min_length=1)
    banned_words: list[str] = Field(default_factory=list)
    banned_claim_types: list[ClaimType] = Field(default_factory=list)
    competitors: list[Competitor] = Field(default_factory=list)
    glossary: list[GlossaryEntry] = Field(default_factory=list)

    @field_validator("glossary")
    @classmethod
    def _terms_are_unique(cls, glossary: list[GlossaryEntry]) -> list[GlossaryEntry]:
        terms = [entry.term.casefold() for entry in glossary]
        if len(terms) != len(set(terms)):
            raise ValueError("glossary terms must not repeat")
        return glossary

    @field_validator("banned_words")
    @classmethod
    def _words_are_not_blank(cls, words: list[str]) -> list[str]:
        if any(not word.strip() for word in words):
            raise ValueError("banned_words must not contain blank entries")
        return words

    @field_validator("banned_claim_types")
    @classmethod
    def _types_can_be_enforced(cls, types: list[ClaimType]) -> list[ClaimType]:
        unenforceable = sorted(set(types) - BANNABLE_CLAIM_TYPES)
        if unenforceable:
            raise ValueError(
                f"cannot be detected from wording, so cannot be banned: {unenforceable}"
            )
        return types
