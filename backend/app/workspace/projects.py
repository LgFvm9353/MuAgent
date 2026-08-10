from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import PROJECT_ROOT_PATH_MAX_LENGTH, Project


class ProjectPathError(ValueError):
    """The requested project directory is not a safe accessible workspace."""


def allowed_project_roots(settings: Settings) -> tuple[Path, ...]:
    return tuple(
        Path(item.strip()).expanduser().resolve()
        for item in settings.workspace_allowed_roots.split(",")
        if item.strip()
    )


def normalize_project_path(settings: Settings, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not candidate.exists() or not candidate.is_dir():
        raise ProjectPathError("project path must be an existing directory")
    if len(str(candidate)) > PROJECT_ROOT_PATH_MAX_LENGTH:
        raise ProjectPathError("project path is too long")
    allowed_roots = allowed_project_roots(settings)
    # A local editor with no explicit allowlist can open any existing directory.
    # Deployments can opt into a restricted set through WORKSPACE_ALLOWED_ROOTS.
    if not allowed_roots or any(
        candidate == root or candidate.is_relative_to(root) for root in allowed_roots
    ):
        return candidate
    raise ProjectPathError("project path is outside the configured workspace allowlist")


class ProjectService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def create(self, path: str, name: str | None = None) -> Project:
        normalized = normalize_project_path(self._settings, path)
        existing = await self._session.scalar(
            select(Project).where(Project.root_path == str(normalized))
        )
        if existing is not None:
            return existing
        project = Project(
            id=uuid4(),
            name=(name or normalized.name or str(normalized)).strip(),
            root_path=str(normalized),
            access_mode="edit",
        )
        self._session.add(project)
        await self._session.commit()
        await self._session.refresh(project)
        return project

    async def get(self, project_id: UUID) -> Project:
        project = await self._session.get(Project, project_id)
        if project is None:
            raise ProjectPathError("project not found")
        # A project may be removed or moved after registration.
        normalize_project_path(self._settings, project.root_path)
        return project

    async def list(self) -> list[Project]:
        return list(
            await self._session.scalars(select(Project).order_by(Project.updated_at.desc()))
        )
