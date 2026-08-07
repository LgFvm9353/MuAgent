from dataclasses import dataclass

from app.skills.contracts import SkillDefinition
from app.skills.registry import SkillRegistry


@dataclass(frozen=True, slots=True)
class ResolvedSkill:
    id: str
    instructions: str
    metadata: dict[str, object]
    allowed_tools: frozenset[str]
    max_tool_rounds: int
    max_tool_calls: int
    output_schema: dict[str, object] | None


class SkillResolver:
    """Turns a manifest into AgentLoop configuration without coupling the loop."""

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def resolve(
        self,
        skill_id: str,
        *,
        agent_id: str,
        agent_tools: frozenset[str],
        request_tools: frozenset[str] | None = None,
    ) -> ResolvedSkill:
        skill: SkillDefinition = self._registry.get(skill_id)
        allowed = self._registry.effective_tools(skill_id, agent_id, agent_tools, request_tools)
        return ResolvedSkill(
            id=skill.id,
            instructions=skill.instructions,
            metadata={
                "id": skill.id,
                "version": skill.manifest.version,
                "description": skill.manifest.description,
                "references": skill.manifest.references,
                "content_hash": skill.content_hash,
            },
            allowed_tools=allowed,
            max_tool_rounds=skill.manifest.max_tool_rounds,
            max_tool_calls=skill.manifest.max_tool_calls,
            output_schema=skill.output_schema,
        )
