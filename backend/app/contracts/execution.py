from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.base import ContractModel
from app.contracts.task import RiskLevel


class ExecutionStep(ContractModel):
    step_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    depends_on: frozenset[str] = frozenset()
    tool_name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any]
    risk: RiskLevel
    expected_result: str = Field(min_length=1)
    verification_method: str = Field(min_length=1)


class ExecutionPlan(ContractModel):
    plan_id: UUID
    task_id: UUID
    version: int = Field(ge=1)
    steps: tuple[ExecutionStep, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dag(self) -> "ExecutionPlan":
        graph = {step.step_id: step.depends_on for step in self.steps}
        if len(graph) != len(self.steps):
            raise ValueError("step IDs must be unique")
        known = set(graph)
        if any(not dependencies <= known for dependencies in graph.values()):
            raise ValueError("step dependency does not exist")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("execution plan must be acyclic")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)
        return self


class EvidenceRecord(ContractModel):
    evidence_id: UUID
    task_id: UUID
    step_id: str
    kind: str
    summary: str = Field(min_length=1, max_length=10_000)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    artifact_path: str | None = None
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1)
