from pathlib import Path

from app.config import Settings
from app.contracts.task import RiskLevel
from app.tools.check_tool import AllowedCommand, CheckCommandInput, CheckCommandOutput, CheckCommandTool
from app.tools.file_tools import (
    FileContentOutput,
    FileListOutput,
    FileTools,
    ListFilesInput,
    PathInput,
    WriteFileInput,
    WriteFileOutput,
)
from app.tools.registry import ToolDefinition, ToolRegistry
from app.workspace.paths import Workspace


def build_tool_registry(settings: Settings, task_id: str) -> ToolRegistry:
    root = settings.workspace_root / task_id
    root.mkdir(parents=True, exist_ok=True)
    workspace = Workspace(root)
    files = FileTools(workspace)
    checks = CheckCommandTool(
        workspace,
        allowed={
            "python_compile": AllowedCommand(
                executable="python",
                argument_sets=(("-m", "compileall", "-q", "."),),
            ),
            "pytest": AllowedCommand(
                executable="pytest",
                argument_sets=(("-q",),),
            ),
        },
        timeout_seconds=settings.tool_timeout_seconds,
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="list_workspace_files",
            description="List regular files inside the task workspace. Use for workspace discovery only.",
            input_model=ListFilesInput,
            output_model=FileListOutput,
            risk=RiskLevel.LOW,
            timeout_seconds=30,
            idempotent=True,
            max_output_bytes=1024 * 1024,
            handler=files.list_files,
        )
    )
    registry.register(
        ToolDefinition(
            name="read_workspace_file",
            description="Read one UTF-8 regular file inside the task workspace.",
            input_model=PathInput,
            output_model=FileContentOutput,
            risk=RiskLevel.LOW,
            timeout_seconds=30,
            idempotent=True,
            max_output_bytes=1024 * 1024,
            handler=files.read_file,
        )
    )
    registry.register(
        ToolDefinition(
            name="create_workspace_file",
            description="Create a new UTF-8 file without overwriting an existing file.",
            input_model=WriteFileInput,
            output_model=WriteFileOutput,
            risk=RiskLevel.MEDIUM,
            timeout_seconds=30,
            idempotent=False,
            max_output_bytes=1024 * 1024,
            handler=files.create_file,
        )
    )
    registry.register(
        ToolDefinition(
            name="modify_workspace_file",
            description="Replace an existing UTF-8 file and return a unified diff. Requires confirmation as a high-risk overwrite.",
            input_model=WriteFileInput,
            output_model=WriteFileOutput,
            risk=RiskLevel.HIGH,
            timeout_seconds=30,
            idempotent=False,
            max_output_bytes=1024 * 1024,
            handler=files.modify_file,
        )
    )
    registry.register(
        ToolDefinition(
            name="run_allowlisted_check",
            description="Run a configured side-effect-free check command inside the task workspace.",
            input_model=CheckCommandInput,
            output_model=CheckCommandOutput,
            risk=RiskLevel.LOW,
            timeout_seconds=settings.tool_timeout_seconds,
            idempotent=True,
            max_output_bytes=1024 * 1024,
            handler=checks.run,
        )
    )
    return registry


def ensure_storage_roots(settings: Settings) -> None:
    for root in (settings.workspace_root, settings.artifacts_root):
        Path(root).mkdir(parents=True, exist_ok=True)
