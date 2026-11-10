import pytest

from pipeline.gate import GateResult
from pipeline.screening import ScreeningResult
from pipeline.tiering import BLOCKED, TIER1, TIER2, check_price, route

AGREED = 34_000_000
OK_PRICE = check_price(AGREED, AGREED, 100)
CLEAR = ScreeningResult("compliance_screening", "clear", ())
REVIEW = ScreeningResult("compliance_screening", "review", ("close to a listed entity",))
HIT = ScreeningResult("compliance_screening", "blocked", ("matches a listed entity",))
PASSED = GateResult("mandate_integrity", True, ())
FAILED = GateResult("mandate_integrity", False, ("exceeds maximum",))


def test_tolerance_boundary_is_exact():
    at_limit = check_price(AGREED, 34_340_000, 100)
    assert at_limit.within_tolerance
    assert at_limit.drift_bps == 100
    assert not check_price(AGREED, 34_340_001, 100).within_tolerance


def test_a_lower_price_is_accepted():
    lower = check_price(AGREED, 33_000_000, 100)
    assert lower.valid and lower.within_tolerance
    assert lower.drift_bps < 0


@pytest.mark.parametrize(
    "args", [(0, 5, 100), (100, 0, 100), (100, 5, -1), (100, "5", 100)]
)
def test_invalid_price_inputs_are_not_valid(args):
    assert not check_price(*args).valid


def test_blocked_outranks_a_price_drift():
    drifted = check_price(AGREED, 35_200_000, 100)
    decision = route(drifted, HIT)
    assert decision.outcome == BLOCKED


def test_screening_review_goes_to_tier_2():
    decision = route(OK_PRICE, REVIEW, PASSED)
    assert decision.outcome == TIER2
    assert "close to a listed entity" in decision.reasons


def test_price_drift_goes_to_tier_2_without_a_mandate_result():
    decision = route(check_price(AGREED, 35_200_000, 100), CLEAR)
    assert decision.outcome == TIER2
    assert "352 bps" in decision.reasons[0]


def test_a_failed_mandate_gate_is_blocked():
    decision = route(OK_PRICE, CLEAR, FAILED)
    assert decision.outcome == BLOCKED
    assert "exceeds maximum" in decision.reasons


def test_tier_1_needs_a_verified_mandate():
    assert route(OK_PRICE, CLEAR, None).outcome == BLOCKED
    assert route(OK_PRICE, CLEAR, PASSED).outcome == TIER1


def test_unknown_screening_status_is_blocked():
    odd = ScreeningResult("compliance_screening", "maybe", ())
    assert route(OK_PRICE, odd, PASSED).outcome == BLOCKED


def test_router_error_fails_closed():
    assert route(None, CLEAR, PASSED).outcome == BLOCKED
