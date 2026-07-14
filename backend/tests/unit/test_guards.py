from app.contracts.task import BudgetLimits
from app.guards import BudgetGuard, BudgetUsage, GuardDecision


def test_budget_guard_allows_within_limits() -> None:
    assert BudgetGuard().evaluate(BudgetLimits(), BudgetUsage(), cancel_requested=False) is GuardDecision.ALLOW


def test_budget_guard_prioritizes_cancellation() -> None:
    usage = BudgetUsage(tokens=999_999_999)
    assert BudgetGuard().evaluate(BudgetLimits(), usage, cancel_requested=True) is GuardDecision.CANCELLED


def test_budget_guard_stops_after_no_new_information() -> None:
    usage = BudgetUsage(consecutive_no_information_rounds=2)
    assert BudgetGuard().evaluate(BudgetLimits(), usage, cancel_requested=False) is GuardDecision.NEEDS_REVIEW
