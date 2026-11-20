"""The claim taxonomy: what kinds of factual claims exist and how each is governed."""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

ClaimType = Literal[
    "product_fact",
    "statistic",
    "comparison",
    "superlative",
    "health",
    "environmental",
    "pricing",
    "testimonial",
    "other",
]
ClaimVerdict = Literal["supported", "unsupported", "prohibited"]


class ClaimCategory(BaseModel):
    """How one claim type is defined and governed."""

    model_config = ConfigDict(frozen=True)

    description: str
    example: str
    regulated: bool  # code rules block it unless an approved fact covers the exact wording
    detectable: bool  # recognizable from wording alone, so a brand can ban the whole type


CLAIM_TAXONOMY: dict[ClaimType, ClaimCategory] = {
    "product_fact": ClaimCategory(
        description="A verifiable attribute of the product.",
        example="Roasted within 48 hours of shipping.",
        regulated=False,
        detectable=False,
    ),
    "statistic": ClaimCategory(
        description="A number, percentage, or ratio presented as a measured result.",
        example="9 in 10 subscribers renew.",
        regulated=False,
        detectable=True,
    ),
    "comparison": ClaimCategory(
        description="A claim that measures the product against something else.",
        example="Smoother than a typical dark roast.",
        regulated=False,
        detectable=True,
    ),
    "superlative": ClaimCategory(
        description="A claim of being the best, first, only, or top in a field.",
        example="The #1 commuter e-bike.",
        regulated=True,
        detectable=True,
    ),
    "health": ClaimCategory(
        description="A claim about health, medical, or physical or mental wellbeing effects.",
        example="Reduces anxiety.",
        regulated=True,
        detectable=True,
    ),
    "environmental": ClaimCategory(
        description="A claim about environmental or ethical sourcing benefits.",
        example="Carbon-neutral delivery.",
        regulated=True,
        detectable=True,
    ),
    "pricing": ClaimCategory(
        description="A price, discount, financing term, or guarantee.",
        example="Free shipping on orders over $40.",
        regulated=True,
        detectable=True,
    ),
    "testimonial": ClaimCategory(
        description="A customer quote, rating, review, or third-party endorsement.",
        example="Rated 4.9 stars by riders.",
        regulated=True,
        detectable=True,
    ),
    "other": ClaimCategory(
        description="A factual claim that fits no other category.",
        example="Family owned since 2014.",
        regulated=False,
        detectable=False,
    ),
}
ALL_CLAIM_TYPES: tuple[ClaimType, ...] = get_args(ClaimType)
BANNABLE_CLAIM_TYPES = frozenset(t for t, c in CLAIM_TAXONOMY.items() if c.detectable)
