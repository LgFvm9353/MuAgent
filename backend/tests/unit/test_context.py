from uuid import uuid4

from app.contracts.task import AcceptanceCriterion, TaskContract
from app.harness.context import AgentContextBuilder, ContextBuilder
from app.memory.contracts import MemoryContextBundle


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
        failure_policy="stop",
    )


def test_analyst_context_excludes_acceptance_evidence_and_history() -> None:
    context = ContextBuilder().analyst(task())
    assert set(context) == {"goal", "inputs", "constraints", "allowed_tools", "denied_tools"}


def test_verifier_context_excludes_executor_claims() -> None:
    context = ContextBuilder().verifier(task(), {"steps": []}, (), ({"sha256": "a" * 64},))
    assert set(context) == {
        "acceptance_criteria",
        "approved_plan",
        "execution_records",
        "evidence",
        "final_artifacts",
    }


def test_agent_context_keeps_memory_layers_separate() -> None:
    context = AgentContextBuilder().chat(
        agent_id="architect",
        user_text="fix it",
        memory=MemoryContextBundle.empty(),
    )

    assert context["hard_memory"] == []
    assert context["environment"] is None
    assert context["episodic_memories"] == []
