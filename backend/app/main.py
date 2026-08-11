from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.capabilities import router as capabilities_router
from app.api.conversations import router as conversations_router
from app.api.memories import router as memories_router
from app.api.projects import router as projects_router
from app.api.supervisor import router as supervisor_router
from app.api.tasks import router as tasks_router
from app.config import get_settings
from app.database import Database
from app.logging import configure_logging
from app.mcp.config import load_mcp_config
from app.mcp.manager import McpManager
from app.mcp.sdk_connector import SdkMcpConnector
from app.memory.service import MemoryService
from app.orchestrator.coordinator import Coordinator
from app.orchestrator.recovery import RecoveryService
from app.services.conversation import JsonConversationStore
from app.skills.registry import SkillRegistry
from app.tools.factory import build_tool_registry, ensure_storage_roots
from app.tools.providers import McpToolProvider
from app.tools.subagent import (
    AttachLoop,
    ContextMode,
    SubagentRunManager,
    SupervisorInbox,
    register_subagent_tool,
    register_supervisor_tool,
)

PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    ensure_storage_roots(settings)
    application.state.settings = settings
    application.state.database = Database(settings.database_url)
    application.state.conversation_store = JsonConversationStore(
        settings.conversation_history_root
    )
    application.state.memory_service = MemoryService(settings, BACKEND_ROOT.parent)
    application.state.tool_registry = build_tool_registry(settings, settings.workspace_root)

    async def run_subagent(
        agent: str,
        task: str,
        context: ContextMode,
        attach_loop: AttachLoop,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await application.state.coordinator.run_subagent(
                agent, task, context, attach_loop
            ),
        )

    application.state.supervisor_inbox = SupervisorInbox()
    application.state.subagent_manager = SubagentRunManager(
        run_subagent,
        supervisor_inbox=application.state.supervisor_inbox,
        artifact_root=settings.artifacts_root / "subagents",
    )
    register_subagent_tool(
        application.state.tool_registry,
        application.state.subagent_manager,
    )
    register_supervisor_tool(
        application.state.tool_registry,
        application.state.supervisor_inbox,
    )
    mcp_config = load_mcp_config(BACKEND_ROOT / settings.mcp_config_path)
    application.state.mcp_manager = McpManager(
        mcp_config,
        SdkMcpConnector(mcp_config.servers),
    )
    application.state.mcp_tool_provider = McpToolProvider(
        application.state.tool_registry,
        application.state.mcp_manager,
        mcp_config,
    )
    await application.state.mcp_tool_provider.discover()
    application.state.skill_registry = SkillRegistry.load(
        BACKEND_ROOT / settings.skills_root,
        application.state.tool_registry,
    )
    application.state.coordinator = Coordinator(
        settings,
        application.state.database.session_factory,
        PROMPTS_ROOT,
        application.state.tool_registry,
        application.state.skill_registry,
        application.state.conversation_store,
    )
    async with application.state.database.session_factory() as session:
        recovery = RecoveryService(session)
        await recovery.recover(application.state.coordinator.schedule)
    try:
        yield
    finally:
        await application.state.subagent_manager.close()
        await application.state.coordinator.close()
        await application.state.conversation_store.flush()
        await application.state.mcp_manager.close(
            timeout_seconds=settings.mcp_close_timeout_seconds
        )
        await application.state.database.dispose()


settings = get_settings()
app = FastAPI(title="Harness Agent System", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(tasks_router)
app.include_router(supervisor_router)
app.include_router(conversations_router)
app.include_router(capabilities_router)
app.include_router(memories_router)
app.include_router(projects_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
