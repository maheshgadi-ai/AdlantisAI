"""The judge: compares two unnamed campaigns for an evaluation."""

from __future__ import annotations

import secrets
from typing import ClassVar

from adlantis.agents.base import BaseAgent
from adlantis.schemas.judge import PairwiseRequest, PairwiseVerdict


class Judge(BaseAgent[PairwiseRequest, PairwiseVerdict]):
    """Scores two campaigns by position, on a model that wrote neither of them."""

    name: ClassVar[str] = "judge"
    role: ClassVar[str] = "judge"
    prompt_file: ClassVar[str] = "judge"
    input_schema: ClassVar[type[PairwiseRequest]] = PairwiseRequest
    output_schema: ClassVar[type[PairwiseVerdict]] = PairwiseVerdict

    def render_input(self, data: PairwiseRequest) -> str:
        """The brief, then each campaign inside a boundary its text cannot forge."""
        mark = secrets.token_hex(12)
        return (
            f"Brief:\n{data.brief}\n\n"
            f"{_wrapped('campaign_a', data.campaign_a, mark)}\n\n"
            f"{_wrapped('campaign_b', data.campaign_b, mark)}"
        )


def _wrapped(tag: str, text: str, mark: str) -> str:
    return f'<{tag} boundary="{mark}">\n{text}\n</{tag} boundary="{mark}">'
