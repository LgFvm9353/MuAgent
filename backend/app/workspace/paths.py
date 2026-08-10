import os
from collections.abc import Iterator
from pathlib import Path


class WorkspaceViolationError(ValueError):
    pass


IGNORED_SCAN_DIRECTORIES = frozenset(
    {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}
)


def iter_workspace_files(
    root: Path,
    *,
    ignored_directories: frozenset[str] = IGNORED_SCAN_DIRECTORIES,
) -> Iterator[Path]:
    """Yield regular files without descending into dependency/generated trees."""
    resolved_root = root.resolve(strict=True)
    for current, directories, filenames in os.walk(
        resolved_root, topdown=True, followlinks=False
    ):
        current_path = Path(current)
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in ignored_directories
            and not (current_path / directory).is_symlink()
        )
        for filename in filenames:
            path = current_path / filename
            if not path.is_symlink() and path.is_file():
                yield path


class Workspace:
    def __init__(
        self,
        root: Path,
        *,
        max_files: int = 1_000,
        max_file_bytes: int = 5 * 1024 * 1024,
        max_total_bytes: int = 100 * 1024 * 1024,
    ) -> None:
        self.root = root.resolve(strict=True)
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes

    def resolve(self, relative_path: str, *, must_exist: bool) -> Path:
        candidate = Path(relative_path)
        invalid_path = (
            candidate.is_absolute()
            or bool(candidate.anchor)
            or ".." in candidate.parts
            or not candidate.parts
        )
        if invalid_path:
            raise WorkspaceViolationError("path must be relative and cannot traverse parents")
        raw = self.root / candidate
        if not raw.is_relative_to(self.root):
            raise WorkspaceViolationError("path escapes the workspace")
        self._reject_symlink_chain(raw if must_exist else raw.parent)
        resolved = raw.resolve(strict=must_exist)
        if not resolved.is_relative_to(self.root):
            raise WorkspaceViolationError("path escapes the workspace")
        return resolved

    def validate_capacity(self, incoming_bytes: int, *, replacing: Path | None = None) -> None:
        if incoming_bytes > self.max_file_bytes:
            raise WorkspaceViolationError("file size limit exceeded")
        files = list(iter_workspace_files(self.root))
        replacing_exists = replacing is not None and replacing.is_file()
        if len(files) + (0 if replacing_exists else 1) > self.max_files:
            raise WorkspaceViolationError("file count limit exceeded")
        replaced_size = (
            replacing.stat().st_size if replacing_exists and replacing is not None else 0
        )
        total = sum(path.stat().st_size for path in files) - replaced_size
        if total + incoming_bytes > self.max_total_bytes:
            raise WorkspaceViolationError("workspace size limit exceeded")

    def _reject_symlink_chain(self, path: Path) -> None:
        current = path
        while current != self.root:
            if current.is_symlink():
                raise WorkspaceViolationError("symbolic links are not allowed")
            current = current.parent
