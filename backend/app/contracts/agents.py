from typing import Literal

from pydantic import Field

from app.contracts.base import ContractModel


class AgentProposal(ContractModel):
    summary: str = Field(min_length=1, max_length=5_000)
    assumptions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    expected_artifacts: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)


class Critique(ContractModel):
    proposal_index: int = Field(ge=0)
    findings: tuple[str, ...] = Field(min_length=1)
    required_revisions: tuple[str, ...] = ()


class CritiqueSet(ContractModel):
    critiques: tuple[Critique, ...] = Field(min_length=1)


class AgentDecision(ContractModel):
    selected_proposal_index: int = Field(ge=0)
    rationale: str = Field(min_length=1, max_length=5_000)
    rejected_reasons: dict[int, str]
    may_plan: bool
    confidence: float = Field(ge=0, le=1)


class VerificationReport(ContractModel):
    verdict: Literal["passed", "failed", "needs_review"]
    criterion_results: dict[str, bool]
    rationale: str = Field(min_length=1, max_length=5_000)
    recommendation: Literal["complete", "retry", "replan", "terminate", "review"]
