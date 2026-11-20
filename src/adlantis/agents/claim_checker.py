"""The claim checker: reads every claim in an asset and tests it against its cited sources."""

from __future__ import annotations

import json
import secrets
from typing import ClassVar

from adlantis.agents.base import BaseAgent
from adlantis.llm.router import ModelRouter
from adlantis.llm.types import Message
from adlantis.rules.claim_gate import settle_claims
from adlantis.rules.context import RuleContext
from adlantis.rules.engine import check_asset
from adlantis.schemas.claim_check import ClaimCheckDraft, ClaimCheckResult
from adlantis.schemas.copy import CampaignAsset
from adlantis.schemas.evidence_store import EvidenceStore
from adlantis.tools.untrusted import render_untrusted


class ClaimChecker(BaseAgent[CampaignAsset, ClaimCheckResult]):
    """Proposes verdicts with a model; code rules and proof checks have the last word."""

    name: ClassVar[str] = "claim_checker"
    role: ClassVar[str] = "claim_checker"
    prompt_file: ClassVar[str] = "claim_checker"
    input_schema: ClassVar[type[CampaignAsset]] = CampaignAsset
    output_schema: ClassVar[type[ClaimCheckResult]] = ClaimCheckResult

    def __init__(self, router: ModelRouter, ctx: RuleContext, evidence: EvidenceStore) -> None:
        super().__init__(router)
        self.ctx = ctx
        self.evidence = evidence

    def render_input(self, data: CampaignAsset) -> str:
        """The asset and its cited facts as JSON, with cited web text kept as untrusted data."""
        facts = [self.ctx.facts.get(reference) for reference in data.references]
        records = [self.evidence.get(reference) for reference in data.references]
        review = {
            "asset": data.model_dump(mode="json"),
            "banned_claim_types": self.ctx.brand.banned_claim_types,
            "approved_glossary": [entry.wording for entry in self.ctx.brand.glossary],
            "cited_facts": [fact.model_dump(mode="json") for fact in facts if fact],
        }
        web = render_untrusted([r for r in records if r], secrets.token_hex(12))
        return f"{json.dumps(review, indent=2)}\n\nCited web evidence:\n{web}"

    def _run(self, data: CampaignAsset) -> ClaimCheckResult:
        report = check_asset(data, self.ctx)
        messages = [Message.system(self.system_prompt), Message.user(self.render_input(data))]
        llm = self.router.for_role(self.role)
        draft = llm.structured(messages, ClaimCheckDraft, trace_name="claim_checker.llm")
        return settle_claims(draft.claims, data, self.ctx, self.evidence, report)
