import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    agent_id: str
    role: str
    model: str
    prompt_path: Path
    prompt_version: str
    schema_version: str
    output_model: type[BaseModel]
    allowed_tools: frozenset[str]
    timeout_seconds: float
    max_retries: int
    display_name: str = ""
    description: str = ""
    capabilities: frozenset[str] = frozenset()
    mention_aliases: tuple[str, ...] = ()
    routing_keywords: tuple[str, ...] = ()
    handoff_targets: frozenset[str] = frozenset()
    enabled: bool = True
    stage_prompts: dict[str, Path] | None = None
    stage_output_models: dict[str, type[BaseModel]] | None = None

    def prompt_path_for(self, stage: str) -> Path:
        if self.stage_prompts is not None and stage in self.stage_prompts:
            return self.stage_prompts[stage]
        return self.prompt_path

    def config_hash(self, stage: str = "default") -> str:
        prompt_path = self.prompt_path_for(stage)
        output_model = (self.stage_output_models or {}).get(stage, self.output_model)
        payload: dict[str, Any] = {
            "agent_id": self.agent_id,
            "role": self.role,
            "display_name": self.display_name,
            "description": self.description,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "prompt_path": prompt_path.as_posix(),
            "schema_version": self.schema_version,
            "output_schema": output_model.model_json_schema(),
            "allowed_tools": sorted(self.allowed_tools),
            "capabilities": sorted(self.capabilities),
            "mention_aliases": self.mention_aliases,
            "routing_keywords": self.routing_keywords,
            "handoff_targets": sorted(self.handoff_targets),
            "enabled": self.enabled,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class AgentRegistry:
    def __init__(self, definitions: tuple[AgentDefinition, ...]) -> None:
        self._definitions: dict[str, AgentDefinition] = {}
        for definition in definitions:
            if definition.agent_id in self._definitions:
                raise ValueError(f"duplicate agent ID: {definition.agent_id}")
            if not definition.prompt_path.is_file():
                raise ValueError(f"prompt does not exist: {definition.prompt_path}")
            for stage_prompt in (definition.stage_prompts or {}).values():
                if not stage_prompt.is_file():
                    raise ValueError(f"prompt does not exist: {stage_prompt}")
            self._definitions[definition.agent_id] = definition

    def get(self, agent_id: str) -> AgentDefinition:
        try:
            definition = self._definitions[agent_id]
        except KeyError as error:
            raise LookupError(agent_id) from error
        if not definition.enabled:
            raise LookupError(agent_id)
        return definition

    def all(self) -> tuple[AgentDefinition, ...]:
        return tuple(definition for definition in self._definitions.values() if definition.enabled)

    def resolve_mention(self, alias: str) -> AgentDefinition | None:
        normalized = alias.casefold().lstrip("@")
        for definition in self.all():
            aliases = (definition.agent_id, *definition.mention_aliases)
            if any(candidate.casefold().lstrip("@") == normalized for candidate in aliases):
                return definition
        return None

    def prompt(self, agent_id: str, stage: str = "default") -> str:
        return self.get(agent_id).prompt_path_for(stage).read_text(encoding="utf-8")
