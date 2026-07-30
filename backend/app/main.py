from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.capabilities import router as capabilities_router
from app.api.confirmations import router as confirmations_router
from app.api.conversations import router as conversations_router
from app.api.tasks import router as tasks_router
from app.config import get_settings
from app.database import Database
from app.logging import configure_logging
from app.mcp.config import load_mcp_config
from app.mcp.manager import McpManager
from app.mcp.registry import register_mcp_tools
from app.mcp.sdk_connector import SdkMcpConnector
from app.orchestrator.coordinator import Coordinator
from app.orchestrator.recovery import RecoveryService
from app.skills.registry import SkillRegistry
from app.tools.factory import build_tool_registry, ensure_storage_roots

PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    ensure_storage_roots(settings)
    application.state.database = Database(settings.database_url)
    application.state.tool_registry = build_tool_registry(settings, settings.workspace_root)
    mcp_config = load_mcp_config(BACKEND_ROOT / settings.mcp_config_path)
    application.state.mcp_manager = McpManager(
        mcp_config,
        SdkMcpConnector(mcp_config.servers),
    )
    await register_mcp_tools(
        application.state.tool_registry,
        application.state.mcp_manager,
        mcp_config,
    )
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
    )
    async with application.state.database.session_factory() as session:
        recovery = RecoveryService(session)
        await recovery.recover(application.state.coordinator.schedule)
        await recovery.recover_chat(
            application.state.coordinator.schedule_chat,
            lease_owner="application-startup",
        )
    try:
        yield
    finally:
        await application.state.coordinator.close()
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
app.include_router(conversations_router)
app.include_router(confirmations_router)
app.include_router(capabilities_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
