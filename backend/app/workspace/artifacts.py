from pathlib import Path
from typing import Any

_MAX_FILE_BYTES = 64 * 1024
_MAX_TOTAL_BYTES = 256 * 1024
_TEXT_SUFFIXES = frozenset(
    {
        ".css",
        ".html",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".mjs",
        ".py",
        ".ts",
        ".tsx",
        ".txt",
        ".vue",
        ".xml",
        ".yaml",
        ".yml",
    }
)


def collect_text_artifacts(workspace_root: Path) -> tuple[dict[str, Any], ...]:
    root = workspace_root.resolve(strict=True)
    artifacts: list[dict[str, Any]] = []
    total_bytes = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            continue
        size = resolved.stat().st_size
        relative_path = resolved.relative_to(root).as_posix()
        if size > _MAX_FILE_BYTES:
            artifacts.append(
                {
                    "path": relative_path,
                    "size_bytes": size,
                    "content": None,
                    "omitted_reason": "file exceeds verifier content limit",
                }
            )
            continue
        if total_bytes + size > _MAX_TOTAL_BYTES:
            artifacts.append(
                {
                    "path": relative_path,
                    "size_bytes": size,
                    "content": None,
                    "omitted_reason": "artifact bundle exceeds verifier content limit",
                }
            )
            continue
        try:
            content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            artifacts.append(
                {
                    "path": relative_path,
                    "size_bytes": size,
                    "content": None,
                    "omitted_reason": "file is not valid UTF-8 text",
                }
            )
            continue
        artifacts.append({"path": relative_path, "size_bytes": size, "content": content})
        total_bytes += size

    return tuple(artifacts)
