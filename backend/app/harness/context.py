from typing import Any

from app.contracts.task import TaskContract


class ContextBuilder:
    def analyst(self, task: TaskContract) -> dict[str, Any]:
        return {
            "goal": task.goal,
            "inputs": task.inputs,
            "constraints": task.constraints,
            "allowed_tools": sorted(task.allowed_tools),
            "denied_tools": sorted(task.denied_tools),
        }

    def planner(
        self,
        task: TaskContract,
        analysis: dict[str, Any],
        tool_catalog: tuple[dict[str, Any], ...],
        workspace_files: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        return {
            "task": task.model_dump(mode="json"),
            "analysis": analysis,
            "tool_catalog": tool_catalog,
            "workspace": {
                "empty": not workspace_files,
                "files": sorted(workspace_files),
            },
        }

    def replanner(
        self,
        task: TaskContract,
        prior_plan: dict[str, Any],
        verification: dict[str, Any],
        evidence: tuple[dict[str, Any], ...],
        tool_catalog: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        return {
            "task": task.model_dump(mode="json"),
            "prior_plan": prior_plan,
            "verification_failure": verification,
            "evidence": evidence,
            "tool_catalog": tool_catalog,
            "instruction": "Change only steps required to address verified failures.",
        }

    def verifier(
        self,
        task: TaskContract,
        plan: dict[str, Any],
        execution: tuple[dict[str, Any], ...],
        evidence: tuple[dict[str, Any], ...],
        artifacts: tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]:
        return {
            "acceptance_criteria": [
                item.model_dump(mode="json") for item in task.acceptance_criteria
            ],
            "approved_plan": plan,
            "execution_records": execution,
            "evidence": evidence,
            "final_artifacts": artifacts,
        }
