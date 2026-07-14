import asyncio
import os
from dataclasses import dataclass

from pydantic import Field

from app.contracts.base import ContractModel
from app.workspace.paths import Workspace


class CheckCommandInput(ContractModel):
    command: str
    arguments: tuple[str, ...] = ()


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
        self._timeout = timeout_seconds
        self._max_output = max_output_bytes

    async def run(self, request: CheckCommandInput) -> CheckCommandOutput:
        definition = self._allowed.get(request.command)
        if definition is None:
            raise ValueError("command is not allowlisted")
        if request.arguments not in definition.argument_sets:
            raise ValueError("command arguments are not allowlisted")
        environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if key in os.environ}
        process = await asyncio.create_subprocess_exec(
            definition.executable,
            *request.arguments,
            cwd=self._workspace.root,
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout)
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            return CheckCommandOutput(
                exit_code=process.returncode or -1,
                stdout=self._decode(stdout),
                stderr=self._decode(stderr),
                timed_out=True,
            )
        return CheckCommandOutput(
            exit_code=process.returncode or 0,
            stdout=self._decode(stdout),
            stderr=self._decode(stderr),
        )

    def _decode(self, value: bytes) -> str:
        return value[: self._max_output].decode("utf-8", errors="replace")
