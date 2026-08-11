"""Small, recoverable Git worktree lifecycle used by child agents.

Worktrees are deliberately best-effort: a non-Git workspace keeps the current
behaviour, while a Git workspace gets an isolated detached checkout and a
patch-style handoff returned to the parent.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

_GIT_EXECUTABLE = shutil.which("git") or "git"


@dataclass(frozen=True, slots=True)
class WorktreeHandoff:
    source_root: Path
    path: Path
    branch: str
    patch: str
    changed_files: tuple[str, ...]
    isolated: bool


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - executable and arguments are fixed Git operations
        [_GIT_EXECUTABLE, "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def prepare_worktree(
    source_root: Path, artifacts_root: Path, agent_id: str
) -> WorktreeHandoff | None:
    """Create an isolated detached checkout, or return ``None`` if unavailable."""
    source_root = source_root.resolve()
    try:
        repository = Path(_git(source_root, "rev-parse", "--show-toplevel")).resolve()
        head = _git(repository, "rev-parse", "HEAD")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    base = (artifacts_root.resolve() / "worktrees")
    base.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex[:12]
    path = base / f"{agent_id}-{token}"
    branch = f"codex/agent/{agent_id}/{token}"
    try:
        _git(repository, "worktree", "add", "-b", branch, str(path), head)
    except (OSError, subprocess.SubprocessError):
        return None
    return WorktreeHandoff(repository, path, branch, "", (), True)


def collect_handoff(worktree: WorktreeHandoff) -> WorktreeHandoff:
    if not worktree.isolated:
        return worktree
    try:
        changed = _git(worktree.path, "status", "--porcelain")
        patch = subprocess.run(  # noqa: S603 - executable and arguments are fixed Git operations
            [_GIT_EXECUTABLE, "-C", str(worktree.path), "diff", "--binary"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        files = tuple(
            line[3:].strip()
            for line in changed.splitlines()
            if len(line) >= 4 and line[3:].strip()
        )
    except (OSError, subprocess.SubprocessError):
        return worktree
    return WorktreeHandoff(
        worktree.source_root,
        worktree.path,
        worktree.branch,
        patch,
        files,
        True,
    )


def cleanup_worktree(worktree: WorktreeHandoff | None) -> None:
    if worktree is None or not worktree.isolated:
        return
    try:
        _git(worktree.source_root, "worktree", "remove", "--force", str(worktree.path))
    except (OSError, subprocess.SubprocessError):
        # Cleanup is recoverable; leave the path for an operator to inspect.
        return
