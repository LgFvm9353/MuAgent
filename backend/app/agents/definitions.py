from pathlib import Path

from pydantic import BaseModel

from app.config import Settings
from app.contracts.agents import AgentProposal, DesignFeedback, ReviewFeedback, VerificationReport
from app.contracts.execution import ExecutionPlan
from app.harness.registry import AgentDefinition, AgentRegistry


def build_agent_registry(settings: Settings, prompts_root: Path) -> AgentRegistry:
    def definition(
        agent_id: str,
        role: str,
        prompt: str,
        output_model: type[BaseModel],
        model: str,
    ) -> AgentDefinition:
        return AgentDefinition(
            agent_id=agent_id,
            role=role,
            model=model,
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
            definition(
                "architect",
                "software architecture and execution planning",
                "architect/v1.txt",
                AgentProposal,
                settings.agent_model("architect"),
            ),
            definition(
                "architect_planner",
                "software architecture and execution planning",
                "architect/planner-v1.txt",
                ExecutionPlan,
                settings.agent_model("architect_planner"),
            ),
            definition(
                "reviewer",
                "code review and test strategy",
                "reviewer/v1.txt",
                ReviewFeedback,
                settings.agent_model("reviewer"),
            ),
            definition(
                "designer",
                "creative direction and interface design",
                "designer/v1.txt",
                DesignFeedback,
                settings.agent_model("designer"),
            ),
            definition(
                "verifier",
                "independent verification",
                "verifier/v1.txt",
                VerificationReport,
                settings.agent_model("verifier"),
            ),
        )
    )
