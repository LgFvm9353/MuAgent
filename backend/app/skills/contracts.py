from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SkillManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    description: str = Field(min_length=1, max_length=500)
    allowed_agents: frozenset[str] = Field(min_length=1)
    allowed_tools: frozenset[str] = frozenset()
    denied_tools: frozenset[str] = frozenset()
    required_tools: frozenset[str] = frozenset()
    references: tuple[str, ...] = ()
    output_schema: str | None = None

    @model_validator(mode="after")
    def validate_tool_policy(self) -> SkillManifest:
        if self.allowed_tools & self.denied_tools:
            raise ValueError("allowed and denied tools must not overlap")
        if not self.required_tools <= self.allowed_tools:
            raise ValueError("required tools must be included in allowed tools")
        return self


class SkillDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest: SkillManifest
    instructions: str = Field(min_length=1, max_length=100_000)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    references: dict[str, str] = Field(default_factory=dict)
    output_schema: dict[str, object] | None = None

    @property
    def id(self) -> str:
        return self.manifest.id
