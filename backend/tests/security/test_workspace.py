from pathlib import Path

import pytest

from app.workspace.paths import Workspace, WorkspaceViolationError


def test_workspace_rejects_parent_traversal(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    with pytest.raises(WorkspaceViolationError):
        workspace.resolve("../secret", must_exist=False)


def test_workspace_rejects_absolute_path(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    with pytest.raises(WorkspaceViolationError):
        workspace.resolve(str((tmp_path / "absolute").resolve()), must_exist=False)


def test_workspace_accepts_contained_path(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    assert workspace.resolve("nested/file.txt", must_exist=False).is_relative_to(tmp_path)
