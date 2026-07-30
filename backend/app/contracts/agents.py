from typing import Literal

from pydantic import Field

from app.contracts.base import ContractModel

HandoffIntent = Literal["delegate", "question", "review", "revise", "execute", "done_notify"]


class AgentHandoff(ContractModel):
    target_agent_id: str = Field(min_length=1, max_length=100)
    intent: HandoffIntent = "delegate"
    objective: str = Field(min_length=1, max_length=4_000)
    context_summary: str = Field(default="", max_length=4_000)
    expected_output: str = Field(default="", max_length=2_000)
    reply_required: bool = True


class ChatAgentReply(ContractModel):
    text: str = Field(min_length=1, max_length=20_000)
    handoffs: tuple[AgentHandoff, ...] = ()


class AgentProposal(ContractModel):
    summary: str = Field(min_length=1, max_length=5_000)
    assumptions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    expected_artifacts: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)


class ReviewFeedback(ContractModel):
    summary: str = Field(min_length=1, max_length=5_000)
    findings: tuple[str, ...] = ()
    required_tests: tuple[str, ...] = ()
    blocking_issues: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)


class DesignFeedback(ContractModel):
    summary: str = Field(min_length=1, max_length=5_000)
    recommendations: tuple[str, ...] = ()
    interaction_risks: tuple[str, ...] = ()
    applicable: bool = True
    confidence: float = Field(ge=0, le=1)


class VerificationReport(ContractModel):
    verdict: Literal["passed", "failed", "needs_review"]
    criterion_results: dict[str, bool]
    rationale: str = Field(min_length=1, max_length=5_000)
    recommendation: Literal["complete", "retry", "replan", "terminate", "review"]
