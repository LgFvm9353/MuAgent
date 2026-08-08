from enum import StrEnum


class TaskState(StrEnum):
    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    POLICY_CHECK = "POLICY_CHECK"
    # Kept for reading legacy task rows. New tasks use the supervisor
    # decision-request flow instead of the old tool-confirmation gate.
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    REPLANNING = "REPLANNING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


TERMINAL_STATES = frozenset(
    {
        TaskState.SUCCEEDED,
        TaskState.FAILED,
        TaskState.CANCELLED,
        TaskState.REJECTED,
        TaskState.BUDGET_EXCEEDED,
    }
)

_ALLOWED: dict[TaskState, frozenset[TaskState]] = {
    TaskState.PENDING: frozenset(
        {
            TaskState.ANALYZING,
            TaskState.CANCELLED,
            TaskState.REJECTED,
            TaskState.FAILED,
            TaskState.BUDGET_EXCEEDED,
        }
    ),
    TaskState.ANALYZING: frozenset(
        {
            TaskState.PLANNING,
            TaskState.NEEDS_REVIEW,
            TaskState.FAILED,
            TaskState.CANCELLED,
            TaskState.BUDGET_EXCEEDED,
        }
    ),
    TaskState.PLANNING: frozenset(
        {
            TaskState.POLICY_CHECK,
            TaskState.NEEDS_REVIEW,
            TaskState.FAILED,
            TaskState.CANCELLED,
            TaskState.BUDGET_EXCEEDED,
        }
    ),
    TaskState.POLICY_CHECK: frozenset(
        {
            TaskState.EXECUTING,
            TaskState.REJECTED,
            TaskState.FAILED,
            TaskState.CANCELLED,
            TaskState.BUDGET_EXCEEDED,
        }
    ),
    TaskState.WAITING_CONFIRMATION: frozenset(
        {TaskState.EXECUTING, TaskState.REJECTED, TaskState.CANCELLED, TaskState.BUDGET_EXCEEDED}
    ),
    TaskState.EXECUTING: frozenset(
        {
            TaskState.VERIFYING,
            TaskState.NEEDS_REVIEW,
            TaskState.FAILED,
            TaskState.CANCELLED,
            TaskState.BUDGET_EXCEEDED,
        }
    ),
    TaskState.VERIFYING: frozenset(
        {
            TaskState.SUCCEEDED,
            TaskState.REPLANNING,
            TaskState.NEEDS_REVIEW,
            TaskState.FAILED,
            TaskState.CANCELLED,
            TaskState.BUDGET_EXCEEDED,
        }
    ),
    TaskState.REPLANNING: frozenset(
        {
            TaskState.POLICY_CHECK,
            TaskState.NEEDS_REVIEW,
            TaskState.FAILED,
            TaskState.CANCELLED,
            TaskState.BUDGET_EXCEEDED,
        }
    ),
    TaskState.NEEDS_REVIEW: frozenset(
        {
            TaskState.ANALYZING,
            TaskState.PLANNING,
            TaskState.POLICY_CHECK,
            TaskState.REJECTED,
            TaskState.CANCELLED,
            TaskState.FAILED,
        }
    ),
}


class InvalidStateTransition(ValueError):
    pass


def validate_transition(current: TaskState, target: TaskState) -> None:
    if current in TERMINAL_STATES or target not in _ALLOWED[current]:
        raise InvalidStateTransition(f"invalid transition {current} -> {target}")
