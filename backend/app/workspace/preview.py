from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.workspace.paths import Workspace, WorkspaceViolationError

PreviewType = Literal["text", "markdown", "json", "code", "unsupported"]
MAX_PREVIEW_BYTES = 256 * 1024

_TEXT_SUFFIXES = frozenset({".txt", ".log", ".csv"})
_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
_JSON_SUFFIXES = frozenset({".json"})
_CODE_SUFFIXES = frozenset(
    {
        ".css", ".go", ".html", ".java", ".js", ".jsx", ".mjs", ".py",
        ".rs", ".sh", ".sql", ".ts", ".tsx", ".vue", ".xml", ".yaml", ".yml",
    }
)


class ArtifactPreviewError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ArtifactInfo:
    path: str
    name: str
    size_bytes: int
    modified_at: datetime
    preview_type: PreviewType


@dataclass(frozen=True, slots=True)
class ArtifactContent(ArtifactInfo):
    content: str


def preview_type(path: Path) -> PreviewType:
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        return "text"
    if suffix in _MARKDOWN_SUFFIXES:
        return "markdown"
    if suffix in _JSON_SUFFIXES:
        return "json"
    if suffix in _CODE_SUFFIXES:
        return "code"
    return "unsupported"


def task_workspace(workspace_root: Path, task_id: str) -> Path | None:
    raw_root = workspace_root / "tasks" / task_id
    if not raw_root.is_dir() or raw_root.is_symlink():
        return None
    root = raw_root.resolve(strict=True)
    tasks_root = (workspace_root / "tasks").resolve()
    if not root.is_relative_to(tasks_root):
        return None
    return root


def list_artifacts(workspace_root: Path, task_id: str) -> tuple[ArtifactInfo, ...]:
    root = task_workspace(workspace_root, task_id)
    if root is None:
        return ()
    artifacts: list[ArtifactInfo] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            continue
        stat = resolved.stat()
        artifacts.append(
            ArtifactInfo(
                path=resolved.relative_to(root).as_posix(),
                name=resolved.name,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
                preview_type=preview_type(resolved),
            )
        )
    return tuple(artifacts)


def read_artifact(workspace_root: Path, task_id: str, relative_path: str) -> ArtifactContent:
    root = task_workspace(workspace_root, task_id)
    if root is None:
        raise ArtifactPreviewError("workspace_not_found")
    try:
        resolved = Workspace(root).resolve(relative_path, must_exist=True)
    except (WorkspaceViolationError, FileNotFoundError, OSError) as error:
        raise ArtifactPreviewError("artifact_not_found") from error
    if not resolved.is_file():
        raise ArtifactPreviewError("artifact_not_found")
    kind = preview_type(resolved)
    if kind == "unsupported":
        raise ArtifactPreviewError("preview_unsupported")
    stat = resolved.stat()
    if stat.st_size > MAX_PREVIEW_BYTES:
        raise ArtifactPreviewError("preview_too_large")
    try:
        content = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ArtifactPreviewError("preview_not_utf8") from error
    return ArtifactContent(
        path=resolved.relative_to(root).as_posix(),
        name=resolved.name,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
        preview_type=kind,
        content=content,
    )
