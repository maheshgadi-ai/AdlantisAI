"""Claim triage: reads rejected statements against the approved facts, for evaluation."""

from __future__ import annotations

import json
import secrets
from typing import ClassVar

from adlantis.agents.base import BaseAgent
from adlantis.llm.types import Message
from adlantis.schemas.triage import TriageDraft, TriageRequest


class ClaimTriage(BaseAgent[TriageRequest, TriageDraft]):
    """Runs on the claim checker's model. Code decides what its readings may count as."""

    name: ClassVar[str] = "claim_triage"
    role: ClassVar[str] = "claim_checker"
    prompt_file: ClassVar[str] = "claim_triage"
    input_schema: ClassVar[type[TriageRequest]] = TriageRequest
    output_schema: ClassVar[type[TriageDraft]] = TriageDraft

    def render_input(self, data: TriageRequest) -> str:
        """The approved material, then the statements inside a boundary."""
        approved = {
            "product": data.product.name,
            "approved_facts": [
                {
                    "id": fact.id,
                    "claim": fact.claim,
                    "approved_phrasings": fact.approved_phrasings,
                    "paraphrase_scope": fact.paraphrase_scope,
                }
                for fact in data.facts.facts
                if not fact.is_expired(data.today)
            ],
            "glossary": {entry.term: entry.wording for entry in data.brand.glossary},
        }
        mark = secrets.token_hex(12)
        listed = "\n".join(f"{n}. {claim}" for n, claim in enumerate(data.claims, 1))
        return (
            f"{json.dumps(approved, indent=2)}\n\n"
            f'<statements boundary="{mark}">\n{listed}\n</statements boundary="{mark}">'
        )

    def _run(self, data: TriageRequest) -> TriageDraft:
        messages = [Message.system(self.system_prompt), Message.user(self.render_input(data))]
        llm = self.router.for_role(self.role)
        return llm.structured(messages, TriageDraft, trace_name="claim_triage.llm")
