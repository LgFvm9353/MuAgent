from pathlib import Path

from app.skills.contracts import SkillDefinition
from app.skills.loader import SkillLoadError, load_skill
from app.tools.registry import ToolRegistry, UnknownToolError


class UnknownSkillError(LookupError):
    pass


class SkillRegistry:
    def __init__(self, skills: tuple[SkillDefinition, ...]) -> None:
        self._skills = {skill.id: skill for skill in skills}
        if len(self._skills) != len(skills):
            raise SkillLoadError("duplicate skill ID")

    @classmethod
    def load(cls, root: Path, tools: ToolRegistry) -> "SkillRegistry":
        if not root.exists():
            return cls(())
        skills: list[SkillDefinition] = []
        for directory in sorted(root.iterdir(), key=lambda path: path.name):
            if directory.name.startswith("."):
                continue
            skill = load_skill(directory)
            for tool_name in skill.manifest.allowed_tools:
                try:
                    tools.get(tool_name)
                except UnknownToolError as error:
                    raise SkillLoadError(
                        f"skill {skill.id} references unknown tool: {tool_name}"
                    ) from error
            skills.append(skill)
        return cls(tuple(skills))

    def get(self, skill_id: str) -> SkillDefinition:
        try:
            return self._skills[skill_id]
        except KeyError as error:
            raise UnknownSkillError(skill_id) from error

    def list_for_agent(self, agent_id: str) -> tuple[SkillDefinition, ...]:
        return tuple(
            skill
            for skill in sorted(self._skills.values(), key=lambda item: item.id)
            if agent_id in skill.manifest.allowed_agents
        )

    def effective_tools(
        self,
        skill_id: str,
        agent_id: str,
        agent_tools: frozenset[str],
        request_tools: frozenset[str] | None = None,
    ) -> frozenset[str]:
        skill = self.get(skill_id)
        if agent_id not in skill.manifest.allowed_agents:
            raise PermissionError(f"agent cannot use skill: {skill_id}")
        allowed = agent_tools & skill.manifest.allowed_tools
        if request_tools is not None:
            allowed &= request_tools
        allowed -= skill.manifest.denied_tools
        if not skill.manifest.required_tools <= allowed:
            raise PermissionError(f"required skill tools are unavailable: {skill_id}")
        return allowed
