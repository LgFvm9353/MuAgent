from pathlib import Path
from uuid import UUID


class WorkspacePreconditionError(RuntimeError):
    """Raised when a task workspace no longer satisfies an execution plan."""


def ensure_task_directory(workspace_root: Path, task_id: UUID) -> Path:
    tasks_root = (workspace_root / "tasks").resolve()
    task_directory = tasks_root / str(task_id)
    task_directory.mkdir(parents=True, exist_ok=True)
    return task_directory.resolve(strict=True)
