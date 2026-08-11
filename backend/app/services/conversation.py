import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.runtime import AgentInvocation
from app.models import Task

ConversationSink = Callable[[AgentInvocation], Awaitable[None]]


class LocalConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    task_id: UUID | None = None
    conversation_id: UUID
    turn_id: UUID | None = None
    agent_run_id: UUID | None = None
    routing_decision_id: UUID | None = None
    reply_to_message_id: int | None = None
    agent_id: str
    role: str
    message_type: str
    phase: str
    summary: str
    content: dict[str, Any]
    mentions: list[str] = Field(default_factory=list)
    routing_metadata: dict[str, Any] = Field(default_factory=dict)
    source_id: str
    created_at: datetime


class JsonConversationStore:
    """Per-conversation local JSON transcript store.

    Runtime state such as conversations, turns, tasks, and agent runs remains
    relational.  User/agent transcript messages are persisted only here.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._cache: dict[UUID, list[LocalConversationMessage]] = {}
        self._flush_tasks: dict[UUID, asyncio.Task[None]] = {}

    def _lock(self, conversation_id: UUID) -> asyncio.Lock:
        return self._locks.setdefault(conversation_id, asyncio.Lock())

    def _path(self, conversation_id: UUID) -> Path:
        return self._root / f"{conversation_id}.json"

    def _read(self, conversation_id: UUID) -> list[LocalConversationMessage]:
        path = self._path(conversation_id)
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        messages = raw.get("messages", []) if isinstance(raw, dict) else []
        return [LocalConversationMessage.model_validate(item) for item in messages]

    def _write(
        self, conversation_id: UUID, messages: list[LocalConversationMessage]
    ) -> None:
        path = self._path(conversation_id)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        payload = {
            "version": 1,
            "conversation_id": str(conversation_id),
            "messages": [item.model_dump(mode="json") for item in messages],
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    async def _messages(self, conversation_id: UUID) -> list[LocalConversationMessage]:
        cached = self._cache.get(conversation_id)
        if cached is None:
            cached = await asyncio.to_thread(self._read, conversation_id)
            self._cache[conversation_id] = cached
        return cached

    async def _flush(self, conversation_id: UUID) -> None:
        # Keep the event loop free while the JSON snapshot is written.
        await asyncio.sleep(0)
        while True:
            async with self._lock(conversation_id):
                messages = list(await self._messages(conversation_id))
                await asyncio.to_thread(self._write, conversation_id, messages)
                if messages == self._cache.get(conversation_id, []):
                    self._flush_tasks.pop(conversation_id, None)
                    return

    def _schedule_flush(self, conversation_id: UUID) -> None:
        task = self._flush_tasks.get(conversation_id)
        if task is None or task.done():
            self._flush_tasks[conversation_id] = asyncio.create_task(
                self._flush(conversation_id),
                name=f"conversation-json-flush:{conversation_id}",
            )

    async def flush(self) -> None:
        tasks = tuple(self._flush_tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def list_messages(
        self,
        conversation_id: UUID,
        *,
        after: int = 0,
        limit: int = 500,
        exclude_types: frozenset[str] = frozenset(),
    ) -> list[LocalConversationMessage]:
        async with self._lock(conversation_id):
            messages = list(await self._messages(conversation_id))
        return [
            item
            for item in messages
            if item.id > after and item.message_type not in exclude_types
        ][:limit]

    async def task_messages(
        self,
        conversation_id: UUID,
        task_id: UUID,
        *,
        after: int = 0,
        limit: int = 200,
    ) -> list[LocalConversationMessage]:
        messages = await self.list_messages(conversation_id, after=after, limit=100_000)
        return [item for item in messages if item.task_id == task_id][:limit]

    async def relevant_history(
        self,
        conversation_id: UUID,
        *,
        before_id: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        messages = await self.list_messages(conversation_id, limit=100_000)
        selected = [
            item
            for item in messages
            if (before_id is None or item.id < before_id)
            and item.message_type in {"user_message", "agent_message", "parallel_result"}
        ]
        selected.sort(key=lambda item: item.id, reverse=True)
        return build_relevant_history(selected[:24])

    async def relevant_history_before_turn(
        self, conversation_id: UUID, current_turn_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        messages = await self.list_messages(conversation_id, limit=100_000)
        current_ids = [
            item.id
            for item in messages
            if item.turn_id == current_turn_id and item.message_type == "user_message"
        ]
        if not current_ids:
            return ()
        return await self.relevant_history(conversation_id, before_id=min(current_ids))

    async def append(
        self,
        conversation_id: UUID,
        *,
        agent_id: str,
        role: str,
        message_type: str,
        phase: str,
        summary: str,
        content: dict[str, Any],
        source_id: str,
        task_id: UUID | None = None,
        turn_id: UUID | None = None,
        agent_run_id: UUID | None = None,
        routing_decision_id: UUID | None = None,
        mentions: list[str] | None = None,
        routing_metadata: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        async with self._lock(conversation_id):
            messages = await self._messages(conversation_id)
            existing = next((item for item in messages if item.source_id == source_id), None)
            if existing is not None:
                return {"id": existing.id, "source_id": existing.source_id}
            message = LocalConversationMessage(
                id=max((item.id for item in messages), default=0) + 1,
                conversation_id=conversation_id,
                task_id=task_id,
                turn_id=turn_id,
                agent_run_id=agent_run_id,
                routing_decision_id=routing_decision_id,
                reply_to_message_id=reply_to_message_id,
                agent_id=agent_id,
                role=role,
                message_type=message_type,
                phase=phase,
                summary=summary[:1000],
                content=content,
                source_id=source_id,
                mentions=mentions or [],
                routing_metadata=routing_metadata or {},
                created_at=datetime.now(UTC),
            )
            messages.append(message)
            self._schedule_flush(conversation_id)
            return {"id": message.id, "source_id": message.source_id}

    async def find_by_source(
        self, conversation_id: UUID, source_id: str
    ) -> dict[str, Any] | None:
        messages = await self.list_messages(conversation_id, limit=100_000)
        row = next((item for item in messages if item.source_id == source_id), None)
        return {"id": row.id, "source_id": row.source_id} if row is not None else None


class ConversationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        store: JsonConversationStore,
    ) -> None:
        self._sessions = sessions
        self._store = store

    async def relevant_history(
        self, conversation_id: UUID, current_turn_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        return await self._store.relevant_history_before_turn(conversation_id, current_turn_id)

    def sink(self, task_id: UUID) -> ConversationSink:
        async def publish(invocation: AgentInvocation) -> None:
            summary, content = format_agent_message(
                invocation.agent_id, invocation.output, invocation.phase
            )
            async with self._sessions() as session:
                task = await session.get(Task, task_id)
                if task is None:
                    return
                conversation_id = task.conversation_id
            await self._store.append(
                conversation_id,
                task_id=task_id,
                agent_id=invocation.agent_id,
                role="agent",
                message_type=invocation.message_type,
                phase=invocation.phase,
                summary=summary,
                content=content,
                source_id=invocation.source_id,
            )

        return publish


def format_agent_message(
    agent_id: str, output: dict[str, Any], phase: str = "discussion"
) -> tuple[str, dict[str, Any]]:
    explicit = output.get("summary")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip(), output
    if agent_id == "reviewer" and phase == "verification":
        return f"Reviewer verification verdict: {output.get('verdict', 'unknown')}.", output
    return f"{agent_id} completed a response.", output


def build_relevant_history(
    newest_first: list[LocalConversationMessage],
) -> tuple[dict[str, Any], ...]:
    selected: list[dict[str, Any]] = []
    total = 0
    for message in newest_first:
        if message.message_type not in {"user_message", "agent_message", "parallel_result"}:
            continue
        text = message.content.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        text = text.strip()[:8000]
        if total + len(text) > 24000:
            text = text[: 24000 - total]
        if not text:
            break
        selected.append(
            {
                "message_id": message.id,
                "role": message.role,
                "agent_id": message.agent_id,
                "text": text,
            }
        )
        total += len(text)
        if len(selected) >= 12 or total >= 24000:
            break
    selected.reverse()
    return tuple(selected)
