from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.confirmations import router as confirmations_router
from app.api.tasks import router as tasks_router
from app.config import get_settings
from app.database import Database
from app.logging import configure_logging
from app.orchestrator.coordinator import Coordinator
from app.orchestrator.recovery import RecoveryService
from app.tools.factory import ensure_storage_roots


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    ensure_storage_roots(settings)
    application.state.database = Database(settings.database_url)
    application.state.coordinator = Coordinator(
        settings,
        application.state.database.session_factory,
        Path(__file__).resolve().parents[1] / "prompts",
    )
    async with application.state.database.session_factory() as session:
        await RecoveryService(session).recover(application.state.coordinator.schedule)
    try:
        yield
    finally:
        await application.state.coordinator.close()
        await application.state.database.dispose()


app = FastAPI(title="Harness Agent System", version="0.1.0", lifespan=lifespan)
app.include_router(tasks_router)
app.include_router(confirmations_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
