import pytest

from app.agents.evaluation import average, ratio


def test_eval_metrics_handle_empty_sets_deterministically() -> None:
    assert ratio(0, 0) == 0
    assert average(()) == 0


def test_eval_metrics_reject_invalid_counts() -> None:
    with pytest.raises(ValueError):
        ratio(2, 1)
