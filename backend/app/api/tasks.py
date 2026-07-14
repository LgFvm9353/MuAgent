from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import database_session
from app.contracts.task import TaskContract
from app.repositories import TaskNotFoundError
from app.services.tasks import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])
Session = Annotated[AsyncSession, Depends(database_session)]


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    trace_id: UUID
    state: str
    version: int
    cancel_requested: bool


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(contract: TaskContract, session: Session, request: Request) -> TaskResponse:
    task = await TaskService(session).create(contract)
    await request.app.state.coordinator.schedule(task.id)
    return TaskResponse.model_validate(task)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, session: Session) -> TaskResponse:
    try:
        task = await TaskService(session).get(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="task not found") from error
    return TaskResponse.model_validate(task)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: UUID, session: Session, request: Request) -> TaskResponse:
    try:
        task = await TaskService(session).cancel(task_id)
    except TaskNotFoundError as error:
        raise HTTPException(status_code=404, detail="task not found") from error
    await request.app.state.coordinator.cancel(task_id)
    return TaskResponse.model_validate(task)
