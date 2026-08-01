import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.runtime import StructuredGateway
from app.config import Settings
from app.contracts.context import ConversationContextDigest
from app.harness.model_capabilities import ModelCapability, ModelCapabilityRegistry
from app.harness.structured_tools import structured_output_system
from app.harness.token_budget import ConservativeTokenCounter, ContextBudget, calculate_budget
from app.logging import logger
from app.models import (
    Conversation,
    ConversationContextSummary,
    ConversationMessage,
    Task,
)

_COMPRESSION_SYSTEM = (
    "You compress conversation history into a grounded structured checkpoint. "
    "Never invent facts or source message IDs."
)
_COMPRESSION_INSTRUCTION = (
    "Create a loss-minimizing conversation checkpoint. Preserve facts, user constraints, "
    "decisions, open work, tool outcomes, failures, files, participants, and continuity. "
    "Every source_message_id must come from the supplied source_message_ids."
)


@dataclass(frozen=True, slots=True)
class PreparedContext:
    context: dict[str, Any]
    budget: ContextBudget
    compression_triggered: bool
    compression_succeeded: bool
    summary_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CompressionInput:
    previous_summary: dict[str, Any] | None
    messages: tuple[dict[str, Any], ...]
    source_message_ids: frozenset[int]


class ContextCompressionService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        gateway: StructuredGateway,
        settings: Settings,
    ) -> None:
        self._sessions = sessions
        self._gateway = gateway
        self._settings = settings
        self._counter = ConservativeTokenCounter()
        self._capabilities = ModelCapabilityRegistry(
            unknown_context_window=settings.context_unknown_model_window,
            unknown_max_output_tokens=settings.context_unknown_model_max_output_tokens,
            context_window_overrides=_parse_model_limits(settings.context_model_windows),
            max_output_overrides=_parse_model_limits(settings.context_model_max_output_tokens),
        )

    async def prepare(
        self,
        *,
        conversation_id: UUID,
        model: str,
        system: str,
        context: dict[str, Any],
        output_model: type[Any],
        tools: tuple[dict[str, Any], ...] = (),
        max_tokens: int = 16_000,
    ) -> PreparedContext:
        raw_context = await self._with_persisted_history(conversation_id, context)
        budget = self._budget(model, system, raw_context, output_model, tools, max_tokens)
        if budget.utilization < self._settings.context_compression_threshold:
            return PreparedContext(raw_context, budget, False, False)
        try:
            fixed_request_tokens = max(
                0,
                budget.estimated_input_tokens - self._counter.count_json(raw_context),
            )
            compressed, summary_id = await self._compress(
                conversation_id=conversation_id,
                context=raw_context,
                target_input_tokens=max(
                    0,
                    int(
                        budget.maximum_input_tokens
                        * self._settings.context_compression_target
                    )
                    - fixed_request_tokens,
                ),
            )
            compressed_budget = self._budget(
                model, system, compressed, output_model, tools, max_tokens
            )
            if compressed_budget.utilization > self._settings.context_compression_target:
                raise ValueError("compression_target_not_reached")
            return PreparedContext(compressed, compressed_budget, True, True, summary_id)
        except Exception as error:
            await self._record_failure(conversation_id, raw_context, type(error).__name__)
            logger().warning(
                "context_compression_failed",
                conversation_id=str(conversation_id),
                model=model,
                error_type=type(error).__name__,
                estimated_input_tokens=budget.estimated_input_tokens,
                context_window=budget.context_window,
            )
            return PreparedContext(raw_context, budget, True, False)

    async def _with_persisted_history(
        self, conversation_id: UUID, context: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sessions() as session:
            rows = await self._messages(session, conversation_id)
            summary = await self._current_summary(session, conversation_id)
        return self._assemble(context, rows, summary)

    @staticmethod
    def _assemble(
        context: dict[str, Any],
        rows: list[ConversationMessage],
        summary: ConversationContextSummary | None,
    ) -> dict[str, Any]:
        result = dict(context)
        start_after = summary.source_message_end_id if summary else 0
        key_ids = set(summary.key_message_ids) if summary else set()
        result["context_summary"] = summary.summary if summary else None
        result["relevant_history"] = tuple(
            _message_context(item)
            for item in rows
            if item.id > start_after or item.id in key_ids
        )
        return result

    def _budget(
        self,
        model: str,
        system: str,
        context: dict[str, Any],
        output_model: type[Any],
        tools: tuple[dict[str, Any], ...],
        max_tokens: int,
    ) -> ContextBudget:
        capability = self._capabilities.resolve(model)
        actual_system = structured_output_system(system, output_model)
        estimated = self._counter.count_text(actual_system) + self._counter.count_json(context)
        if tools:
            estimated += self._counter.count_json(tools)
        return calculate_budget(
            capability,
            estimated,
            requested_output_tokens=max_tokens,
            safety_margin_ratio=self._settings.context_safety_margin_ratio,
        )

    async def _compress(
        self,
        *,
        conversation_id: UUID,
        context: dict[str, Any],
        target_input_tokens: int,
    ) -> tuple[dict[str, Any], UUID]:
        model = self._settings.context_compression_model
        if not model:
            raise RuntimeError("context_compression_model_not_configured")
        history = list(context.get("relevant_history") or ())
        compressible, retained = self._select_compression_range(
            context, history, target_input_tokens
        )
        if not compressible:
            raise RuntimeError("insufficient_compressible_history")
        source_ids = _source_ids(compressible)
        if not source_ids:
            raise ValueError("compressible_history_has_no_message_ids")
        previous_summary = context.get("context_summary")
        previous_ids = (
            _digest_source_ids(previous_summary)
            if isinstance(previous_summary, dict)
            else frozenset()
        )
        compression_capability = self._capabilities.resolve(
            model,
            context_window_override=self._settings.context_compression_model_context_window,
            max_output_tokens_override=(
                self._settings.context_compression_model_max_output_tokens
            ),
        )
        digest = await self._compress_within_model_window(
            CompressionInput(
                previous_summary=previous_summary,
                messages=tuple(compressible),
                source_message_ids=source_ids | previous_ids,
            ),
            model,
            compression_capability,
        )
        summary_json = digest.model_dump(mode="json")
        source_tokens = self._counter.count_json(
            {"previous_summary": context.get("context_summary"), "messages": compressible}
        )
        summary_tokens = self._counter.count_json(summary_json)
        if summary_tokens >= source_tokens:
            raise ValueError("summary_did_not_reduce_context")
        first_id, last_id = min(source_ids), max(source_ids)
        checkpoint_id, winning_summary = await self._commit_checkpoint(
            conversation_id=conversation_id,
            expected_previous=context.get("context_summary"),
            digest=digest,
            first_id=first_id,
            last_id=last_id,
            compressed_count=len(compressible),
            source_tokens=source_tokens,
            summary_tokens=summary_tokens,
            compression_model=model,
        )
        if winning_summary is not None:
            async with self._sessions() as session:
                rows = await self._messages(session, conversation_id)
            return self._assemble(context, rows, winning_summary), winning_summary.id
        compressed = dict(context)
        compressed["context_summary"] = summary_json
        compressed["relevant_history"] = tuple(retained)
        return compressed, checkpoint_id

    def _select_compression_range(
        self,
        context: dict[str, Any],
        history: list[dict[str, Any]],
        target_input_tokens: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        minimum_recent = min(self._settings.context_recent_messages, len(history))
        previous = context.get("context_summary")
        protected_ids = (
            set(
                ConversationContextDigest.model_validate(previous).critical_message_ids()
            )
            if isinstance(previous, dict)
            else set()
        )
        source_message = context.get("source_message")
        if isinstance(source_message, dict) and isinstance(
            source_message.get("message_id"), int
        ):
            protected_ids.add(source_message["message_id"])
        recent_ids = {
            item["message_id"]
            for item in history[-minimum_recent:]
            if isinstance(item.get("message_id"), int)
        }
        protected_ids.update(recent_ids)
        fixed = dict(context)
        fixed["context_summary"] = None
        fixed["relevant_history"] = ()
        fixed_tokens = self._counter.count_json(fixed)
        summary_reserve = self._settings.context_compression_model_max_output_tokens or 8_192
        retained_budget = max(0, target_input_tokens - fixed_tokens - summary_reserve)
        retained = [
            item for item in history if item.get("message_id") in protected_ids
        ]
        compressible = [
            item for item in history if item.get("message_id") not in protected_ids
        ]
        # If protected anchors alone exceed the target, they are intentionally retained;
        # the caller will reject the checkpoint and use the original context.
        if self._counter.count_json(retained) > retained_budget:
            return compressible, retained
        return compressible, retained

    async def _compress_within_model_window(
        self,
        source: CompressionInput,
        model: str,
        capability: ModelCapability,
    ) -> ConversationContextDigest:
        max_output = min(
            self._settings.context_compression_model_max_output_tokens or 8_192,
            capability.max_output_tokens,
        )
        system_tokens = self._counter.count_text(
            structured_output_system(_COMPRESSION_SYSTEM, ConversationContextDigest)
        )
        safety = max(
            1_024,
            int(capability.context_window * self._settings.context_safety_margin_ratio),
        )
        payload_budget = capability.context_window - max_output - safety - system_tokens
        if payload_budget <= 0:
            raise ValueError("compression_model_has_no_input_budget")
        chunks = self._chunk_messages(source.messages, payload_budget, source.previous_summary)
        digests = [
            await self._summarize(
                model,
                previous_summary=source.previous_summary if index == 0 else None,
                messages=chunk,
                summaries=(),
                allowed_ids=(
                    _source_ids(chunk)
                    | (
                        _digest_source_ids(source.previous_summary)
                        if index == 0 and source.previous_summary is not None
                        else frozenset()
                    )
                ),
                max_output=max_output,
            )
            for index, chunk in enumerate(chunks)
        ]
        while len(digests) > 1:
            batches = self._chunk_digests(digests, payload_budget)
            digests = [
                await self._summarize(
                    model,
                    previous_summary=None,
                    messages=(),
                    summaries=tuple(item.model_dump(mode="json") for item in batch),
                    allowed_ids=frozenset().union(
                        *(item.referenced_message_ids() for item in batch)
                    ),
                    max_output=max_output,
                )
                for batch in batches
            ]
        digest = digests[0]
        if not digest.referenced_message_ids().issubset(source.source_message_ids):
            raise ValueError("summary_source_message_out_of_range")
        return digest

    def _chunk_messages(
        self,
        messages: tuple[dict[str, Any], ...],
        budget: int,
        previous_summary: dict[str, Any] | None,
    ) -> list[tuple[dict[str, Any], ...]]:
        chunks: list[tuple[dict[str, Any], ...]] = []
        current: list[dict[str, Any]] = []
        for message in messages:
            candidate = [*current, message]
            payload = self._compression_payload(
                previous_summary if not chunks else None, candidate, ()
            )
            if current and self._counter.count_json(payload) > budget:
                chunks.append(tuple(current))
                current = [message]
                payload = self._compression_payload(None, current, ())
            if self._counter.count_json(payload) > budget:
                raise ValueError("single_message_exceeds_compression_model_window")
            current.append(message) if current[-1:] != [message] else None
        if current:
            chunks.append(tuple(current))
        return chunks

    def _chunk_digests(
        self, digests: list[ConversationContextDigest], budget: int
    ) -> list[list[ConversationContextDigest]]:
        batches: list[list[ConversationContextDigest]] = []
        current: list[ConversationContextDigest] = []
        for digest in digests:
            candidate = [*current, digest]
            payload = self._compression_payload(
                None, (), tuple(item.model_dump(mode="json") for item in candidate)
            )
            if current and self._counter.count_json(payload) > budget:
                batches.append(current)
                current = [digest]
                payload = self._compression_payload(
                    None, (), (digest.model_dump(mode="json"),)
                )
            if self._counter.count_json(payload) > budget:
                raise ValueError("single_summary_exceeds_compression_model_window")
            if current[-1:] != [digest]:
                current.append(digest)
        if current:
            batches.append(current)
        if len(batches) == len(digests):
            raise ValueError("compression_summaries_cannot_be_merged")
        return batches

    async def _summarize(
        self,
        model: str,
        *,
        previous_summary: dict[str, Any] | None,
        messages: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        summaries: tuple[dict[str, Any], ...],
        allowed_ids: frozenset[int],
        max_output: int,
    ) -> ConversationContextDigest:
        payload = self._compression_payload(previous_summary, messages, summaries)
        result = await self._gateway.structured(
            model=model,
            system=_COMPRESSION_SYSTEM,
            user_content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            output_model=ConversationContextDigest,
            max_tokens=max_output,
        )
        digest = ConversationContextDigest.model_validate(result.parsed_output)
        if not digest.referenced_message_ids().issubset(allowed_ids):
            raise ValueError("summary_source_message_out_of_range")
        return digest

    @staticmethod
    def _compression_payload(
        previous_summary: dict[str, Any] | None,
        messages: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        summaries: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        return {
            "previous_summary": previous_summary,
            "messages": messages,
            "partial_summaries": summaries,
            "source_message_ids": sorted(
                _source_ids(messages)
                | (
                    _digest_source_ids(previous_summary)
                    if previous_summary is not None
                    else frozenset()
                )
                | frozenset(
                    message_id
                    for summary in summaries
                    for message_id in _digest_source_ids(summary)
                )
            ),
            "instruction": _COMPRESSION_INSTRUCTION,
        }

    async def _commit_checkpoint(
        self,
        *,
        conversation_id: UUID,
        expected_previous: dict[str, Any] | None,
        digest: ConversationContextDigest,
        first_id: int,
        last_id: int,
        compressed_count: int,
        source_tokens: int,
        summary_tokens: int,
        compression_model: str,
    ) -> tuple[UUID, ConversationContextSummary | None]:
        async with self._sessions() as session:
            conversation = await session.scalar(
                select(Conversation)
                .where(Conversation.id == conversation_id)
                .with_for_update()
            )
            if conversation is None:
                raise LookupError(str(conversation_id))
            parent = await self._current_summary(session, conversation_id)
            if (parent.summary if parent else None) != expected_previous:
                if parent is None:
                    raise RuntimeError("context_summary_changed")
                return parent.id, parent
            checkpoint = ConversationContextSummary(
                conversation_id=conversation_id,
                parent_summary_id=parent.id if parent else None,
                level=0,
                status="completed",
                source_message_start_id=parent.source_message_start_id if parent else first_id,
                source_message_end_id=last_id,
                covered_message_count=(parent.covered_message_count if parent else 0)
                + compressed_count,
                summary=digest.model_dump(mode="json"),
                key_message_ids=list(digest.critical_message_ids()),
                source_token_count=source_tokens,
                summary_token_count=summary_tokens,
                compression_model=compression_model,
                tokenizer=self._counter.name,
                schema_version="1",
                completed_at=datetime.now(UTC),
            )
            if parent:
                parent.status = "superseded"
            session.add(checkpoint)
            await session.commit()
            return checkpoint.id, None

    async def _record_failure(
        self, conversation_id: UUID, context: dict[str, Any], failure_code: str
    ) -> None:
        history = list(context.get("relevant_history") or ())
        ids = _source_ids(history)
        if not ids:
            return
        try:
            async with self._sessions() as session:
                parent = await self._current_summary(session, conversation_id)
                session.add(
                    ConversationContextSummary(
                        conversation_id=conversation_id,
                        parent_summary_id=parent.id if parent else None,
                        level=0,
                        status="failed",
                        source_message_start_id=min(ids),
                        source_message_end_id=max(ids),
                        covered_message_count=len(history),
                        summary={},
                        key_message_ids=[],
                        source_token_count=self._counter.count_json(history),
                        summary_token_count=0,
                        compression_model=(
                            self._settings.context_compression_model or "unconfigured"
                        ),
                        tokenizer=self._counter.name,
                        schema_version="1",
                        failure_code=failure_code[:100],
                        completed_at=datetime.now(UTC),
                    )
                )
                await session.commit()
        except Exception:
            logger().warning(
                "context_compression_failure_record_failed",
                conversation_id=str(conversation_id),
            )

    @staticmethod
    async def _messages(
        session: AsyncSession, conversation_id: UUID
    ) -> list[ConversationMessage]:
        return list(
            await session.scalars(
                select(ConversationMessage)
                .outerjoin(Task, Task.id == ConversationMessage.task_id)
                .where(
                    or_(
                        ConversationMessage.conversation_id == conversation_id,
                        Task.conversation_id == conversation_id,
                    )
                )
                .order_by(ConversationMessage.id)
            )
        )

    @staticmethod
    async def _current_summary(
        session: AsyncSession, conversation_id: UUID
    ) -> ConversationContextSummary | None:
        result: ConversationContextSummary | None = await session.scalar(
            select(ConversationContextSummary)
            .where(
                ConversationContextSummary.conversation_id == conversation_id,
                ConversationContextSummary.status == "completed",
            )
            .order_by(ConversationContextSummary.created_at.desc())
            .limit(1)
        )
        return result


def _parse_model_limits(value: str) -> dict[str, int]:
    limits: dict[str, int] = {}
    for entry in value.split(","):
        if not entry.strip():
            continue
        name, separator, raw_limit = entry.partition("=")
        if not separator or not name.strip():
            raise ValueError("invalid model limit override")
        limit = int(raw_limit.strip())
        if limit <= 0:
            raise ValueError("model limit override must be positive")
        limits[name.strip()] = limit
    return limits


def _source_ids(messages: Any) -> frozenset[int]:
    return frozenset(
        item["message_id"]
        for item in messages
        if isinstance(item, dict) and isinstance(item.get("message_id"), int)
    )


def _digest_source_ids(summary: dict[str, Any]) -> frozenset[int]:
    return ConversationContextDigest.model_validate(summary).referenced_message_ids()


def _message_context(message: ConversationMessage) -> dict[str, Any]:
    return {
        "message_id": message.id,
        "role": message.role,
        "agent_id": message.agent_id,
        "message_type": message.message_type,
        "phase": message.phase,
        "summary": message.summary,
        "content": message.content,
        "reply_to_message_id": message.reply_to_message_id,
    }
