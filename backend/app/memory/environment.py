import asyncio
import hashlib
import json
import os
import tomllib
from pathlib import Path
from typing import Any

from app.memory.contracts import EnvironmentSnapshot, EnvironmentSource
from app.workspace.paths import iter_workspace_files

_ALLOWED_NAMES = frozenset(
    {
        "CLAUDE.md",
        "AGENTS.md",
        "README.md",
        "pyproject.toml",
        "package.json",
        "package-lock.json",
        "uv.lock",
        "pytest.ini",
        "vite.config.ts",
        "tsconfig.json",
    }
)
_DENIED_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".crt"})
_PARSER_VERSION = "1"


class EnvironmentMemoryService:
    def __init__(self, workspace_root: Path, *, max_file_bytes: int = 262_144) -> None:
        self._root = workspace_root.resolve()
        self._max_file_bytes = max_file_bytes

    async def snapshot(self) -> EnvironmentSnapshot:
        sources: list[EnvironmentSource] = []
        warnings: list[str] = []
        if not self._root.is_dir():
            warnings.append("workspace_not_found")
        else:
            for path in sorted(iter_workspace_files(self._root)):
                if not self._allowed(path):
                    continue
                try:
                    raw = path.read_bytes()
                    if len(raw) > self._max_file_bytes:
                        warnings.append(f"file_too_large:{path.name}")
                        continue
                    relative = path.relative_to(self._root).as_posix()
                    sources.append(
                        EnvironmentSource(
                            path=relative,
                            kind=self._kind(path),
                            sha256=hashlib.sha256(raw).hexdigest(),
                            content=self._parse(path, raw),
                        )
                    )
                except (OSError, UnicodeError, ValueError, tomllib.TOMLDecodeError):
                    warnings.append(f"file_parse_failed:{path.name}")
        branch, commit, dirty, git_warning = await self._git_state()
        if git_warning:
            warnings.append(git_warning)
        payload = {
            "parser_version": _PARSER_VERSION,
            "root": str(self._root),
            "branch": branch,
            "commit": commit,
            "dirty": dirty,
            "sources": [(item.path, item.sha256) for item in sources],
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()
        return EnvironmentSnapshot(
            workspace_root=str(self._root),
            git_branch=branch,
            git_commit=commit,
            dirty=dirty,
            sources=tuple(sources),
            warnings=tuple(warnings),
            snapshot_hash=snapshot_hash,
        )

    def _allowed(self, path: Path) -> bool:
        if not path.is_file() or path.is_symlink():
            return False
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self._root)
        except (OSError, ValueError):
            return False
        relative_parts = path.relative_to(self._root).parts
        if any(part.startswith(".env") for part in relative_parts):
            return False
        if any(part in {".git", ".venv", "node_modules", "secrets"} for part in relative_parts):
            return False
        if path.suffix.casefold() in _DENIED_SUFFIXES:
            return False
        return path.name in _ALLOWED_NAMES

    @staticmethod
    def _kind(path: Path) -> str:
        if path.suffix == ".toml":
            return "toml"
        if path.suffix == ".json":
            return "json"
        return "markdown" if path.suffix == ".md" else "text"

    @staticmethod
    def _parse(path: Path, raw: bytes) -> dict[str, Any] | str:
        text = raw.decode("utf-8")
        if path.suffix == ".toml":
            return tomllib.loads(text)
        if path.suffix == ".json":
            value = json.loads(text)
            return value if isinstance(value, dict) else {"value": value}
        return text

    async def _git_state(self) -> tuple[str | None, str | None, bool | None, str | None]:
        if not (self._root / ".git").exists():
            return None, None, None, "git_repository_not_found"
        try:
            branch = await self._git("branch", "--show-current")
            commit = await self._git("rev-parse", "HEAD")
            status = await self._git("status", "--porcelain", "--untracked-files=no")
            return branch or None, commit or None, bool(status), None
        except (TimeoutError, OSError, RuntimeError):
            return None, None, None, "git_state_unavailable"

    async def _git(self, *arguments: str) -> str:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            os.fspath(self._root),
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
        if process.returncode:
            raise RuntimeError("git command failed")
        return stdout.decode("utf-8", errors="replace").strip()
