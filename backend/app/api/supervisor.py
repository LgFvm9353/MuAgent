from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.tools.subagent import SupervisorRequest

router = APIRouter(prefix="/subagents/supervisor", tags=["supervisor"])


class SupervisorRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: str
    run_id: str | None
    agent: str
    reason: str
    message: str
    options: tuple[str, ...]
    conversation_id: str | None
    turn_id: str | None
    status: str
    reply: str | None
    created_at: str
    replied_at: str | None

    @classmethod
    def from_request(cls, item: SupervisorRequest) -> "SupervisorRequestResponse":
        return cls(
            request_id=item.request_id,
            run_id=item.run_id,
            agent=item.agent,
            reason=item.reason,
            message=item.message,
            options=item.options,
            conversation_id=item.conversation_id,
            turn_id=item.turn_id,
            status=item.status,
            reply=item.reply,
            created_at=item.created_at.isoformat(),
            replied_at=item.replied_at.isoformat() if item.replied_at else None,
        )


class SupervisorReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=20_000)


@router.get("/pending", response_model=tuple[SupervisorRequestResponse, ...])
async def pending_supervisor_requests(request: Request, conversation_id: str | None = None):
    inbox = request.app.state.supervisor_inbox
    items = await inbox.pending(conversation_id)
    return tuple(SupervisorRequestResponse.from_request(item) for item in items)


@router.post("/{request_id}/reply", response_model=SupervisorRequestResponse)
async def reply_to_supervisor_request(
    request_id: str,
    payload: SupervisorReplyRequest,
    request: Request,
) -> SupervisorRequestResponse:
    try:
        item = await request.app.state.supervisor_inbox.reply(request_id, payload.message)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="supervisor request not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return SupervisorRequestResponse.from_request(item)
