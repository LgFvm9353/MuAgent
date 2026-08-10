from typing import Any

from app.tools.contracts import ToolContext, ToolInvocation
from app.tools.registry import UnknownToolError
from app.tools.runtime import ToolRuntime, ToolRuntimeError


class ModelToolRuntimeAdapter:
    def __init__(self, runtime: ToolRuntime, context: ToolContext) -> None:
        self._runtime = runtime
        self._context = context
        self._calls = 0

    @property
    def calls(self) -> int:
        """Number of model-issued tool calls handled by this adapter."""
        return self._calls

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._calls += 1
        try:
            result = await self._runtime.invoke(
                ToolInvocation(
                    tool_name=name,
                    arguments=arguments,
                    context=self._context,
                )
            )
        except (ToolRuntimeError, UnknownToolError) as error:
            code = error.code if isinstance(error, ToolRuntimeError) else "tool_unknown"
            return {"error": {"code": code}}
        return result.output.model_dump(mode="json")
