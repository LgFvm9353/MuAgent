import pytest

from app.orchestrator.state_machine import InvalidStateTransition, TaskState, validate_transition


def test_happy_path() -> None:
    path = (
        TaskState.PENDING,
        TaskState.ANALYZING,
        TaskState.DECIDING,
        TaskState.PLANNING,
        TaskState.POLICY_CHECK,
        TaskState.EXECUTING,
        TaskState.VERIFYING,
        TaskState.SUCCEEDED,
    )
    for current, target in zip(path, path[1:]):
        validate_transition(current, target)


def test_terminal_state_is_final() -> None:
    with pytest.raises(InvalidStateTransition):
        validate_transition(TaskState.SUCCEEDED, TaskState.ANALYZING)


def test_skipping_workflow_is_rejected() -> None:
    with pytest.raises(InvalidStateTransition):
        validate_transition(TaskState.PENDING, TaskState.SUCCEEDED)
