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

    def domain_expert(
        self, task: TaskContract, tool_catalog: tuple[dict[str, Any], ...]
    ) -> dict[str, Any]:
        return {
            "goal": task.goal,
            "constraints": task.constraints,
            "acceptance_criteria": [
                item.model_dump(mode="json") for item in task.acceptance_criteria
            ],
            "tool_catalog": tool_catalog,
        }

    def critic(self, task: TaskContract, proposals: tuple[dict[str, Any], ...]) -> dict[str, Any]:
        return {"constraints": task.constraints, "proposals": proposals}

    def judge(
        self, proposals: tuple[dict[str, Any], ...], critiques: tuple[dict[str, Any], ...]
    ) -> dict[str, Any]:
        return {"proposals": proposals, "critiques": critiques}

    def planner(
        self, decision: dict[str, Any], tool_catalog: tuple[dict[str, Any], ...]
    ) -> dict[str, Any]:
        return {"approved_decision": decision, "tool_catalog": tool_catalog}

    def replanner(
        self,
        decision: dict[str, Any],
        prior_plan: dict[str, Any],
        verification: dict[str, Any],
        evidence: tuple[dict[str, Any], ...],
        tool_catalog: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        return {
            "approved_decision": decision,
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
    ) -> dict[str, Any]:
        return {
            "acceptance_criteria": [
                item.model_dump(mode="json") for item in task.acceptance_criteria
            ],
            "approved_plan": plan,
            "execution_records": execution,
            "evidence": evidence,
        }
