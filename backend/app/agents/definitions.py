from pathlib import Path

from app.config import Settings
from app.contracts.agents import AgentDecision, AgentProposal, CritiqueSet, VerificationReport
from app.contracts.execution import ExecutionPlan
from app.harness.registry import AgentDefinition, AgentRegistry


def build_agent_registry(settings: Settings, prompts_root: Path) -> AgentRegistry:
    model = settings.anthropic_model
    common = {"model": model, "prompt_version": "v1", "schema_version": "v1", "timeout_seconds": settings.model_timeout_seconds, "max_retries": 2}
    return AgentRegistry(
        (
            AgentDefinition(agent_id="analyst", role="task analysis", prompt_path=prompts_root / "analyst/v1.txt", output_model=AgentProposal, allowed_tools=frozenset(), **common),
            AgentDefinition(agent_id="domain_expert", role="domain proposal", prompt_path=prompts_root / "domain_expert/v1.txt", output_model=AgentProposal, allowed_tools=frozenset(), **common),
            AgentDefinition(agent_id="critic", role="cross review", prompt_path=prompts_root / "critic/v1.txt", output_model=CritiqueSet, allowed_tools=frozenset(), **common),
            AgentDefinition(agent_id="judge", role="independent decision", prompt_path=prompts_root / "judge/v1.txt", output_model=AgentDecision, allowed_tools=frozenset(), **common),
            AgentDefinition(agent_id="planner", role="execution planning", prompt_path=prompts_root / "planner/v1.txt", output_model=ExecutionPlan, allowed_tools=frozenset(), **common),
            AgentDefinition(agent_id="verifier", role="independent verification", prompt_path=prompts_root / "verifier/v1.txt", output_model=VerificationReport, allowed_tools=frozenset(), **common),
        )
    )
