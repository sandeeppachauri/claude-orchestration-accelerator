import pytest

from orchestration_accelerator.trimming import should_trim, validate_strategy


def test_validate_strategy_accepts_known():
    validate_strategy("turn_count")
    validate_strategy("token_budget")
    validate_strategy("none")


def test_validate_strategy_rejects_unknown():
    with pytest.raises(ValueError):
        validate_strategy("not_a_real_strategy")


def test_none_strategy_never_rotates():
    for turn_index in range(0, 50, 5):
        decision = should_trim("none", turn_index)
        assert decision.should_rotate is False


def test_turn_count_strategy_rotates_at_threshold():
    decision = should_trim("turn_count", 20, {"max_turns": 20})
    assert decision.should_rotate is True
    assert decision.summary


def test_turn_count_strategy_does_not_rotate_before_threshold():
    decision = should_trim("turn_count", 5, {"max_turns": 20})
    assert decision.should_rotate is False


def test_turn_count_strategy_does_not_rotate_on_turn_zero():
    decision = should_trim("turn_count", 0, {"max_turns": 20})
    assert decision.should_rotate is False


def test_token_budget_strategy_rotates_past_threshold():
    decision = should_trim(
        "token_budget", 3, {"max_tokens": 1000}, current_tokens=1500
    )
    assert decision.should_rotate is True
    assert decision.summary


def test_token_budget_strategy_does_not_rotate_under_threshold():
    decision = should_trim(
        "token_budget", 3, {"max_tokens": 1000}, current_tokens=500
    )
    assert decision.should_rotate is False
