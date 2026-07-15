import asyncio
import hashlib
import json
from dataclasses import dataclass
from time import monotonic
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.contracts.execution import EvidenceRecord, ExecutionStep
from app.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class ToolExecution:
    output: BaseModel
    evidence: EvidenceRecord


def idempotency_key(task_id: UUID, plan_version: int, step: ExecutionStep) -> str:
    payload = {
        "task_id": str(task_id),
        "plan_version": plan_version,
        "step_id": step.step_id,
        "tool_name": step.tool_name,
        "arguments": step.arguments,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, task_id: UUID, plan_version: int, step: ExecutionStep) -> ToolExecution:
        definition = self._registry.get(step.tool_name)
        request = definition.input_model.model_validate(step.arguments)
        started = monotonic()
        async with asyncio.timeout(definition.timeout_seconds):
            output = await definition.handler(request)
        validated = definition.output_model.model_validate(output)
        serialized = validated.model_dump_json()
        if len(serialized.encode()) > definition.max_output_bytes:
            raise ValueError("tool output size limit exceeded")
        key = idempotency_key(task_id, plan_version, step)
        evidence = EvidenceRecord(
            evidence_id=uuid4(),
            task_id=task_id,
            step_id=step.step_id,
            kind="tool_result",
            summary=serialized,
            duration_ms=int((monotonic() - started) * 1000),
            idempotency_key=key,
        )
        return ToolExecution(output=validated, evidence=evidence)
