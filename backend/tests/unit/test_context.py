from uuid import uuid4

from app.contracts.task import AcceptanceCriterion, TaskContract
from app.harness.context import ContextBuilder


def task() -> TaskContract:
    return TaskContract(
        task_id=uuid4(),
        goal="create report",
        inputs={"source": "safe"},
        constraints=("no network",),
        acceptance_criteria=(
            AcceptanceCriterion(description="report exists", verification_method="read file"),
        ),
        allowed_tools=frozenset({"read_workspace_file"}),
        workspace_relative="task",
        failure_policy="stop",
    )


def test_analyst_context_excludes_acceptance_evidence_and_history() -> None:
    context = ContextBuilder().analyst(task())
    assert set(context) == {"goal", "inputs", "constraints", "allowed_tools", "denied_tools"}


def test_verifier_context_excludes_executor_claims() -> None:
    context = ContextBuilder().verifier(task(), {"steps": []}, (), ({"sha256": "a" * 64},))
    assert set(context) == {"acceptance_criteria", "approved_plan", "execution_records", "evidence"}
