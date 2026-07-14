import hashlib
from pathlib import Path
from uuid import UUID, uuid4

from app.contracts.execution import EvidenceRecord


class EvidenceCollector:
    def __init__(self, artifacts_root: Path, *, inline_limit: int = 32_768) -> None:
        self._artifacts_root = artifacts_root
        self._inline_limit = inline_limit

    def file_evidence(
        self,
        *,
        task_id: UUID,
        step_id: str,
        path: Path,
        workspace_root: Path,
        duration_ms: int,
        idempotency_key: str,
    ) -> EvidenceRecord:
        resolved = path.resolve(strict=True)
        root = workspace_root.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError("evidence path must be a workspace file")
        data = resolved.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        relative = resolved.relative_to(root).as_posix()
        artifact_path: str | None = None
        summary = f"file={relative} size={len(data)} sha256={digest}"
        if len(data) > self._inline_limit:
            destination = self._artifacts_root / str(task_id) / step_id / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            artifact_path = destination.relative_to(self._artifacts_root).as_posix()
        return EvidenceRecord(
            evidence_id=uuid4(),
            task_id=task_id,
            step_id=step_id,
            kind="file",
            summary=summary,
            sha256=digest,
            artifact_path=artifact_path,
            duration_ms=duration_ms,
            idempotency_key=idempotency_key,
        )
