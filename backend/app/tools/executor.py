import asyncio
import hashlib
import json
from dataclasses import dataclass
from time import monotonic
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.contracts.execution import EvidenceRecord, ExecutionStep
from app.tools.check_tool import CheckCommandOutput
from app.tools.file_tools import FileContentOutput, WriteFileOutput
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
        if definition.validate_input is not None:
            definition.validate_input(request)
        started = monotonic()
        async with asyncio.timeout(definition.timeout_seconds):
            output = await definition.handler(request)
        validated = definition.output_model.model_validate(output)
        serialized = validated.model_dump_json()
        if len(serialized.encode()) > definition.max_output_bytes:
            raise ValueError("tool output size limit exceeded")
        key = idempotency_key(task_id, plan_version, step)
        sha256: str | None = None
        exit_code: int | None = None
        kind = "tool_result"
        artifact_path: str | None = None
        if isinstance(validated, (FileContentOutput, WriteFileOutput)):
            kind = "file"
            sha256 = validated.sha256
            artifact_path = validated.path
        elif isinstance(validated, CheckCommandOutput):
            kind = "check"
            exit_code = validated.exit_code
        evidence = EvidenceRecord(
            evidence_id=uuid4(),
            task_id=task_id,
            step_id=step.step_id,
            kind=kind,
            summary=serialized,
            sha256=sha256,
            artifact_path=artifact_path,
            exit_code=exit_code,
            duration_ms=int((monotonic() - started) * 1000),
            idempotency_key=key,
        )
        return ToolExecution(output=validated, evidence=evidence)
