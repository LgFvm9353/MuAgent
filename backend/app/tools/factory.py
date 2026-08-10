import os
from pathlib import Path

from app.config import Settings
from app.contracts.task import RiskLevel
from app.tools.check_tool import (
    AllowedCommand,
    CheckCommandInput,
    CheckCommandOutput,
    CheckCommandTool,
)
from app.tools.file_tools import (
    FileContentOutput,
    FileListOutput,
    FileTools,
    ListFilesInput,
    PathInput,
    SearchFilesInput,
    SearchFilesOutput,
    WriteFileInput,
    WriteFileOutput,
)
from app.tools.registry import ToolDefinition, ToolRegistry
from app.workspace.paths import Workspace

DEFAULT_LOCAL_TOOL_NAMES = frozenset(
    {
        "list_workspace_files",
        "read_workspace_file",
        "search_workspace_files",
        "create_workspace_file",
        "modify_workspace_file",
        "run_allowlisted_check",
    }
)


def build_tool_registry(
    settings: Settings,
    workspace_root: Path,
    *,
    inherited: ToolRegistry | None = None,
    inherited_exclude: frozenset[str] = frozenset(),
) -> ToolRegistry:
    workspace = Workspace(workspace_root)
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
            "npm_test": AllowedCommand(
                executable="npm.cmd" if os.name == "nt" else "npm",
                argument_sets=(("test",),),
            ),
        },
        timeout_seconds=settings.tool_timeout_seconds,
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="list_workspace_files",
            description=(
                "List regular files inside the task workspace. Use for workspace discovery only."
            ),
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
            name="search_workspace_files",
            description="Search text in UTF-8 project files and return matching paths and lines.",
            input_model=SearchFilesInput,
            output_model=SearchFilesOutput,
            risk=RiskLevel.LOW,
            timeout_seconds=30,
            idempotent=True,
            max_output_bytes=1024 * 1024,
            handler=files.search_files,
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
            description=(
                "Replace an existing UTF-8 file and return a unified diff. "
                "Use contact_supervisor when the scope or intended change is unclear."
            ),
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
            description=(
                "Run one configured side-effect-free check inside the task workspace. "
                "Use only the logical commands and exact argument sets in planning_constraints."
            ),
            input_model=CheckCommandInput,
            output_model=CheckCommandOutput,
            risk=RiskLevel.LOW,
            timeout_seconds=settings.tool_timeout_seconds,
            idempotent=True,
            max_output_bytes=1024 * 1024,
            handler=checks.run,
            validate_input=checks.validate_request,
            planning_constraints={"allowed_command_arguments": checks.planning_constraints()},
        )
    )
    if inherited is not None:
        for definition in inherited.definitions():
            if (
                definition.name not in DEFAULT_LOCAL_TOOL_NAMES
                and definition.name not in inherited_exclude
            ):
                registry.register(definition)
    return registry


def ensure_storage_roots(settings: Settings) -> None:
    for root in (
        settings.workspace_root,
        settings.artifacts_root,
    ):
        Path(root).mkdir(parents=True, exist_ok=True)
