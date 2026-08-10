import asyncio
import os
from dataclasses import dataclass

from app.contracts.base import ContractModel
from app.workspace.paths import Workspace


class CheckCommandNotAllowedError(ValueError):
    pass


class CheckCommandInput(ContractModel):
    command: str
    arguments: tuple[str, ...]


class CheckCommandOutput(ContractModel):
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class AllowedCommand:
    executable: str
    argument_sets: tuple[tuple[str, ...], ...]


class CheckCommandTool:
    def __init__(
        self,
        workspace: Workspace,
        allowed: dict[str, AllowedCommand],
        *,
        timeout_seconds: float,
        max_output_bytes: int = 1024 * 1024,
    ) -> None:
        self._workspace = workspace
        self._allowed = allowed
        # Kept in the constructor for configuration compatibility. Commands are
        # cancelled only when their owning agent/task is cancelled.
        del timeout_seconds
        self._max_output = max_output_bytes

    def validate_request(self, request: CheckCommandInput) -> None:
        definition = self._allowed.get(request.command)
        if definition is None:
            raise CheckCommandNotAllowedError("command is not allowlisted")
        if request.arguments not in definition.argument_sets:
            raise CheckCommandNotAllowedError("command arguments are not allowlisted")

    def planning_constraints(self) -> dict[str, list[list[str]]]:
        return {
            name: [list(arguments) for arguments in definition.argument_sets]
            for name, definition in sorted(self._allowed.items())
        }

    async def run(self, request: CheckCommandInput) -> CheckCommandOutput:
        self.validate_request(request)
        definition = self._allowed[request.command]
        environment = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP")
            if key in os.environ
        }
        process = await asyncio.create_subprocess_exec(
            definition.executable,
            *request.arguments,
            cwd=self._workspace.root,
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return CheckCommandOutput(
            exit_code=process.returncode or 0,
            stdout=self._decode(stdout),
            stderr=self._decode(stderr),
        )

    def _decode(self, value: bytes) -> str:
        return value[: self._max_output].decode("utf-8", errors="replace")
