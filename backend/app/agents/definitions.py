from pathlib import Path

from pydantic import BaseModel

from app.config import Settings
from app.contracts.agents import AgentDecision, AgentProposal, CritiqueSet, VerificationReport
from app.contracts.execution import ExecutionPlan
from app.harness.registry import AgentDefinition, AgentRegistry


def build_agent_registry(settings: Settings, prompts_root: Path) -> AgentRegistry:
    def definition(
        agent_id: str,
        role: str,
        prompt: str,
        output_model: type[BaseModel],
    ) -> AgentDefinition:
        return AgentDefinition(
            agent_id=agent_id,
            role=role,
            model=settings.anthropic_model,
            prompt_path=prompts_root / prompt,
            prompt_version="v1",
            schema_version="v1",
            output_model=output_model,
            allowed_tools=frozenset(),
            timeout_seconds=settings.model_timeout_seconds,
            max_retries=2,
        )

    return AgentRegistry(
        (
            definition("analyst", "task analysis", "analyst/v1.txt", AgentProposal),
            definition(
                "domain_expert",
                "domain proposal",
                "domain_expert/v1.txt",
                AgentProposal,
            ),
            definition("critic", "cross review", "critic/v1.txt", CritiqueSet),
            definition("judge", "independent decision", "judge/v1.txt", AgentDecision),
            definition("planner", "execution planning", "planner/v1.txt", ExecutionPlan),
            definition(
                "verifier",
                "independent verification",
                "verifier/v1.txt",
                VerificationReport,
            ),
        )
    )
