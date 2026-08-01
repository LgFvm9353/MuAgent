from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.orchestrator.state_machine import TaskState


class Base(DeclarativeBase):
    @declared_attr.directive
    def __table_args__(cls) -> Any:
        return {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        index=True,
    )


class ConversationContextSummary(Base, TimestampMixin):
    __tablename__ = "conversation_context_summaries"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    parent_summary_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_context_summaries.id", ondelete="SET NULL")
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_message_start_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_message_end_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    covered_message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    key_message_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    source_token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    summary_token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    compression_model: Mapped[str] = mapped_column(String(100), nullable=False)
    tokenizer: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    failure_code: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("ix_context_summary_current", "conversation_id", "status", "created_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class ConversationTurn(Base, TimestampMixin):
    __tablename__ = "conversation_turns"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    idempotency_key: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="routing")
    collaboration_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="parallel"
    )
    collaboration_phase: Mapped[str] = mapped_column(
        String(32), nullable=False, default="routing"
    )
    synthesize: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lead_agent_id: Mapped[str | None] = mapped_column(String(100))
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(100))
    requires_execution: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("conversation_id", "idempotency_key"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class RoutingDecision(Base, TimestampMixin):
    __tablename__ = "routing_decisions"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    turn_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation_turns.id", ondelete="CASCADE"), unique=True, index=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    selected_agents: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    mentions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class ParallelInvocationRequest(Base, TimestampMixin):
    __tablename__ = "parallel_invocation_requests"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation_turns.id", ondelete="CASCADE"), index=True
    )
    source_message_id: Mapped[int] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="CASCADE")
    )
    initiator_agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    callback_agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    targets: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    question: Mapped[str] = mapped_column(String(4000), nullable=False)
    context: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    idempotency_key: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    aggregated_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("conversation_id", "idempotency_key"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class ParallelInvocationResponse(Base, TimestampMixin):
    __tablename__ = "parallel_invocation_responses"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("parallel_invocation_requests.id", ondelete="CASCADE"), index=True
    )
    target_agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    content: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_type: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("request_id", "target_agent_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class AgentInvocationQueueEntry(Base, TimestampMixin):
    __tablename__ = "agent_invocation_queue"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation_turns.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), index=True
    )
    source_agent_id: Mapped[str | None] = mapped_column(String(100))
    target_agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="SET NULL")
    )
    parallel_request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("parallel_invocation_requests.id", ondelete="SET NULL"), index=True
    )
    parallel_response_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("parallel_invocation_responses.id", ondelete="SET NULL"), unique=True, index=True
    )
    intent: Mapped[str] = mapped_column(String(32), nullable=False)
    objective: Mapped[str] = mapped_column(String(4000), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_type: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (
        Index(
            "ix_invocation_queue_claim",
            "conversation_id",
            "target_agent_id",
            "status",
            "available_at",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    originating_invocation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), unique=True, index=True
    )
    trace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(32), default=TaskState.PENDING, index=True)
    contract: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class TaskEvent(Base, TimestampMixin):
    __tablename__ = "task_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str | None] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_turns.id", ondelete="CASCADE"), index=True
    )
    invocation_queue_entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_invocation_queue.id", ondelete="SET NULL"), unique=True, index=True
    )
    intent: Mapped[str | None] = mapped_column(String(32))
    phase: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str | None] = mapped_column(String(32))
    skill_id: Mapped[str | None] = mapped_column(String(64))
    skill_version: Mapped[str | None] = mapped_column(String(32))
    skill_hash: Mapped[str | None] = mapped_column(String(64))
    tool_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resume_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_type: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationMessage(Base, TimestampMixin):
    __tablename__ = "conversation_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_turns.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    routing_decision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("routing_decisions.id", ondelete="SET NULL"), index=True
    )
    reply_to_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="SET NULL")
    )
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="agent")
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    phase: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    mentions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    routing_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    __table_args__ = (
        UniqueConstraint("task_id", "source_id"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )


class Proposal(Base, TimestampMixin):
    __tablename__ = "proposals"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    agent_run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ExecutionPlanRecord(Base, TimestampMixin):
    __tablename__ = "execution_plans"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True, native_uuid=False), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        UniqueConstraint("task_id", "version"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class ExecutionStepRecord(Base, TimestampMixin):
    __tablename__ = "execution_steps"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="CASCADE"), index=True
    )
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        UniqueConstraint("plan_id", "step_key"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class ToolCall(Base, TimestampMixin):
    __tablename__ = "tool_calls"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[UUID | None] = mapped_column(ForeignKey("execution_steps.id"), index=True)
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_turns.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    server_id: Mapped[str | None] = mapped_column(String(100))
    risk: Mapped[str] = mapped_column(String(32), nullable=False, default="low")
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    arguments_hash: Mapped[str | None] = mapped_column(String(64))
    schema_hash: Mapped[str | None] = mapped_column(String(64))
    output_hash: Mapped[str | None] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    timeout_seconds: Mapped[float | None] = mapped_column(Float)
    side_effect_state: Mapped[str | None] = mapped_column(String(32))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_type: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Confirmation(Base, TimestampMixin):
    __tablename__ = "confirmations"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_turns.id", ondelete="CASCADE"), index=True
    )
    tool_call_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="CASCADE"), index=True
    )
    call_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="decided")
    approved: Mapped[bool | None] = mapped_column(Boolean)
    decided_by: Mapped[str | None] = mapped_column(String(100))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("task_id", "plan_id", "call_hash"),
        UniqueConstraint("tool_call_id", "call_hash"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class EvidenceRecordModel(Base, TimestampMixin):
    __tablename__ = "evidence_records"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[UUID | None] = mapped_column(ForeignKey("execution_steps.id"), index=True)
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_turns.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    tool_call_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))


class VerificationReportModel(Base, TimestampMixin):
    __tablename__ = "verification_reports"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("execution_plans.id"))
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AuditEvent(Base, TimestampMixin):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_turns.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    tool_call_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="SET NULL"), index=True
    )
    trace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True, native_uuid=False), index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class UsageRecord(Base, TimestampMixin):
    __tablename__ = "usage_records"
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    agent_run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    request_id: Mapped[str | None] = mapped_column(String(100), index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cache_creation_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)


Index("ix_tasks_state_updated", Task.state, Task.updated_at)
