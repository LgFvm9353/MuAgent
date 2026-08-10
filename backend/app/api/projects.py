import asyncio
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import database_session
from app.config import get_settings
from app.contracts.base import ContractModel
from app.tools.file_tools import FileTools, ListFilesInput, PathInput
from app.workspace.paths import Workspace, WorkspaceViolationError, iter_workspace_files
from app.workspace.projects import ProjectPathError, ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])
Session = Annotated[AsyncSession, Depends(database_session)]


class ProjectCreate(ContractModel):
    path: str = Field(min_length=1, max_length=1_024)
    name: str | None = Field(default=None, min_length=1, max_length=255)


class ProjectResponse(ContractModel):
    id: UUID
    name: str
    root_path: str
    access_mode: str


class ProjectFileResponse(ContractModel):
    path: str
    size: int
    sha256: str
    content: str


class SearchMatch(ContractModel):
    path: str
    line: int
    text: str


def _choose_project_directory() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as error:
        raise ProjectPathError("native project picker is unavailable") from error
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(title="打开项目文件夹", mustexist=True)
    finally:
        root.destroy()
    return selected or None


def _response(project: object) -> ProjectResponse:
    return ProjectResponse.model_validate(project, from_attributes=True)


async def _project_root(project_id: UUID, session: AsyncSession) -> Path:
    try:
        project = await ProjectService(session, get_settings()).get(project_id)
    except ProjectPathError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Path(project.root_path)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, session: Session) -> ProjectResponse:
    try:
        project = await ProjectService(session, get_settings()).create(payload.path, payload.name)
    except ProjectPathError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _response(project)


@router.post("/open-dialog", response_model=ProjectResponse | None)
async def open_project_dialog(session: Session) -> ProjectResponse | None:
    try:
        selected = await asyncio.to_thread(_choose_project_directory)
        if not selected:
            return None
        project = await ProjectService(session, get_settings()).create(selected)
    except ProjectPathError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _response(project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(session: Session) -> list[ProjectResponse]:
    return [_response(item) for item in await ProjectService(session, get_settings()).list()]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: UUID, session: Session) -> ProjectResponse:
    try:
        project = await ProjectService(session, get_settings()).get(project_id)
    except ProjectPathError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _response(project)


@router.get("/{project_id}/files", response_model=tuple[str, ...])
async def list_project_files(
    project_id: UUID,
    session: Session,
    path: Annotated[str, Query(min_length=1, max_length=1_000)] = ".",
) -> tuple[str, ...]:
    root = await _project_root(project_id, session)
    try:
        result = await FileTools(Workspace(root)).list_files(ListFilesInput(path=path))
    except (ValueError, WorkspaceViolationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return result.files


@router.get("/{project_id}/files/content", response_model=ProjectFileResponse)
async def read_project_file(
    project_id: UUID,
    session: Session,
    path: Annotated[str, Query(min_length=1, max_length=1_000)],
) -> ProjectFileResponse:
    root = await _project_root(project_id, session)
    try:
        result = await FileTools(Workspace(root)).read_file(PathInput(path=path))
    except (ValueError, WorkspaceViolationError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return ProjectFileResponse(**result.model_dump())


@router.get("/{project_id}/search", response_model=tuple[SearchMatch, ...])
async def search_project(
    project_id: UUID,
    session: Session,
    query: Annotated[str, Query(min_length=1, max_length=500)],
    path: Annotated[str, Query(min_length=1, max_length=1_000)] = ".",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> tuple[SearchMatch, ...]:
    root = await _project_root(project_id, session)
    workspace = Workspace(root)
    try:
        base = root if path == "." else workspace.resolve(path, must_exist=True)
    except (ValueError, WorkspaceViolationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not base.is_dir():
        raise HTTPException(status_code=422, detail="search path must be a directory")

    def scan() -> tuple[SearchMatch, ...]:
        matches: list[SearchMatch] = []
        for candidate in iter_workspace_files(base):
            if len(matches) >= limit:
                break
            try:
                text = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                if query.casefold() in line.casefold():
                    matches.append(
                        SearchMatch(
                            path=candidate.relative_to(root).as_posix(),
                            line=line_number,
                            text=line[:1_000],
                        )
                    )
                    if len(matches) >= limit:
                        break
        return tuple(matches)

    return await asyncio.to_thread(scan)
