from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    task_understanding_accuracy: float
    proposal_diversity: float
    risk_discovery_rate: float
    judge_selection_accuracy: float
    hallucinated_tool_rate: float
    executable_plan_rate: float
    verifier_error_rate: float
    average_tokens: float
    average_cost_usd: float
    average_latency_ms: float


def ratio(numerator: int, denominator: int) -> float:
    if denominator < 0 or numerator < 0:
        raise ValueError("evaluation counts cannot be negative")
    if denominator == 0:
        return 0.0
    if numerator > denominator:
        raise ValueError("numerator cannot exceed denominator")
    return numerator / denominator


def average(values: tuple[float, ...]) -> float:
    return sum(values) / len(values) if values else 0.0
