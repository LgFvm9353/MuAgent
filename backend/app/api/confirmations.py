from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import database_session
from app.services.confirmations import ConfirmationConflictError, ConfirmationService

router = APIRouter(prefix="/tasks", tags=["confirmations"])
Session = Annotated[AsyncSession, Depends(database_session)]


class ConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: UUID
    plan_version: int = Field(ge=1)
    call_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved: bool
    decided_by: str = Field(min_length=1, max_length=100)


class ConfirmationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    task_id: UUID
    plan_id: UUID
    call_hash: str
    approved: bool
    decided_by: str


class PendingConfirmationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    plan_id: UUID
    plan_version: int
    step_id: str
    tool_name: str
    arguments: dict[str, Any]
    impact: str
    risk: str
    call_hash: str


@router.get(
    "/{task_id}/confirmations/pending",
    response_model=tuple[PendingConfirmationResponse, ...],
)
async def list_pending_confirmations(
    task_id: UUID,
    session: Session,
) -> tuple[PendingConfirmationResponse, ...]:
    try:
        requirements = await ConfirmationService(session).pending(task_id)
    except ConfirmationConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return tuple(PendingConfirmationResponse.model_validate(item) for item in requirements)


@router.post("/{task_id}/confirmations", response_model=ConfirmationResponse)
async def decide_confirmation(
    task_id: UUID,
    request: ConfirmationRequest,
    session: Session,
    http_request: Request,
) -> ConfirmationResponse:
    try:
        confirmation = await ConfirmationService(session).decide(
            task_id=task_id,
            plan_id=request.plan_id,
            plan_version=request.plan_version,
            call_hash=request.call_hash,
            approved=request.approved,
            decided_by=request.decided_by,
        )
    except ConfirmationConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if request.approved:
        await http_request.app.state.coordinator.schedule(task_id)
    return ConfirmationResponse.model_validate(confirmation)
