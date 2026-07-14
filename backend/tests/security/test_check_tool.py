from pathlib import Path

import pytest

from app.tools.check_tool import AllowedCommand, CheckCommandInput, CheckCommandTool
from app.workspace.paths import Workspace


@pytest.mark.asyncio
async def test_check_tool_rejects_appended_arguments(tmp_path: Path) -> None:
    tool = CheckCommandTool(
        Workspace(tmp_path),
        allowed={
            "pytest": AllowedCommand(
                executable="pytest",
                argument_sets=(("-q",),),
            )
        },
        timeout_seconds=1,
    )
    with pytest.raises(ValueError, match="arguments"):
        await tool.run(CheckCommandInput(command="pytest", arguments=("-q", "--collect-only")))


@pytest.mark.asyncio
async def test_check_tool_rejects_unknown_command(tmp_path: Path) -> None:
    tool = CheckCommandTool(Workspace(tmp_path), allowed={}, timeout_seconds=1)
    with pytest.raises(ValueError, match="allowlisted"):
        await tool.run(CheckCommandInput(command="curl", arguments=("https://example.com",)))
