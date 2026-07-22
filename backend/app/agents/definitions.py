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
        *,
        stage_prompts: dict[str, str] | None = None,
        stage_output_models: dict[str, type[BaseModel]] | None = None,
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
            stage_prompts={stage: prompts_root / path for stage, path in stage_prompts.items()}
            if stage_prompts
            else None,
            stage_output_models=stage_output_models,
        )

    return AgentRegistry(
        (
            definition(
                "architect",
                "software architecture, execution planning, and replanning",
                "architect/v1.txt",
                AgentProposal,
                settings.agent_model("architect"),
                stage_prompts={
                    "planning": "architect/planner-v1.txt",
                    "replanning": "architect/planner-v1.txt",
                },
                stage_output_models={
                    "planning": ExecutionPlan,
                    "replanning": ExecutionPlan,
                },
            ),
            definition(
                "reviewer",
                "code review, test strategy, and independent verification",
                "reviewer/v1.txt",
                ReviewFeedback,
                settings.agent_model("reviewer"),
                stage_prompts={"verification": "verifier/v1.txt"},
                stage_output_models={"verification": VerificationReport},
            ),
            definition(
                "designer",
                "creative direction and interface design",
                "designer/v1.txt",
                DesignFeedback,
                settings.agent_model("designer"),
            ),
        )
    )
