from typing import Literal

from pydantic import Field

from app.contracts.base import ContractModel


class ChatAgentReply(ContractModel):
    text: str = Field(min_length=1, max_length=20_000)


class VerificationReport(ContractModel):
    verdict: Literal["passed", "failed", "needs_review"]
    criterion_results: dict[str, bool]
    rationale: str = Field(min_length=1, max_length=5_000)
    recommendation: Literal["complete", "retry", "replan", "terminate", "review"]
