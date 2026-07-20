from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.confirmations import router as confirmations_router
from app.api.conversations import router as conversations_router
from app.api.tasks import router as tasks_router
from app.config import get_settings
from app.database import Database
from app.logging import configure_logging
from app.orchestrator.coordinator import Coordinator
from app.orchestrator.recovery import RecoveryService
from app.tools.factory import ensure_storage_roots

PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    ensure_storage_roots(settings)
    application.state.database = Database(settings.database_url)
    application.state.coordinator = Coordinator(
        settings,
        application.state.database.session_factory,
        PROMPTS_ROOT,
    )
    async with application.state.database.session_factory() as session:
        await RecoveryService(session).recover(application.state.coordinator.schedule)
    try:
        yield
    finally:
        await application.state.coordinator.close()
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


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
