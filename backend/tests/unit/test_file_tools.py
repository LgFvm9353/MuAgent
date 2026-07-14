from pathlib import Path

import pytest

from app.tools.file_tools import FileTools, PathInput, WriteFileInput
from app.workspace.paths import Workspace


@pytest.mark.asyncio
async def test_create_does_not_overwrite(tmp_path: Path) -> None:
    tools = FileTools(Workspace(tmp_path))
    await tools.create_file(WriteFileInput(path="note.txt", content="first"))
    with pytest.raises(FileExistsError):
        await tools.create_file(WriteFileInput(path="note.txt", content="second"))


@pytest.mark.asyncio
async def test_modify_returns_hash_and_diff(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("before\n", encoding="utf-8")
    tools = FileTools(Workspace(tmp_path))
    result = await tools.modify_file(WriteFileInput(path="note.txt", content="after\n"))
    assert len(result.sha256) == 64
    assert "-before" in result.diff
    assert "+after" in result.diff
    assert (await tools.read_file(PathInput(path="note.txt"))).content == "after\n"
