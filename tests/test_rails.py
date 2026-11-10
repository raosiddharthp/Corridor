import pytest

import pipeline.seed as seed
from pipeline.rails import COST, SPEED, select_rail

AMOUNT = seed.FP_88213.agreed_minor


def test_cost_objective_picks_sepa_credit_transfer_for_the_order():
    choice = select_rail(AMOUNT)
    assert choice.rail.id == "sepa_sct"
    assert "lowest fee" in choice.reasons[0]


def test_every_exclusion_is_explained():
    choice = select_rail(AMOUNT)
    assert {rid for rid, _ in choice.excluded} == {"sepa_inst", "farside"}
    why = dict(choice.excluded)
    assert "limit" in why["sepa_inst"]
    assert "not allowed" in why["farside"]


def test_a_small_payment_can_use_the_instant_rail():
    assert select_rail(5_000_000).rail.id == "sepa_inst"


def test_a_pisp_rail_needs_explicit_permission():
    allowed = frozenset({"farside"})
    assert select_rail(AMOUNT, objective=SPEED).rail.id == "sepa_sct"
    assert select_rail(AMOUNT, objective=SPEED, allowed_pisps=allowed).rail.id == "farside"
    assert select_rail(AMOUNT, objective=COST, allowed_pisps=allowed).rail.id == "sepa_sct"


def test_a_deadline_filters_slow_rails():
    none = select_rail(AMOUNT, deadline_hours=12)
    assert none.rail is None
    assert any("deadline" in why for _, why in none.excluded)
    ok = select_rail(AMOUNT, deadline_hours=12, allowed_pisps=frozenset({"farside"}))
    assert ok.rail.id == "farside"


def test_ties_are_broken_deterministically():
    rails = (seed.Rail("b", "B", 100, 1), seed.Rail("a", "A", 100, 1))
    assert select_rail(1_000, rails=rails).rail.id == "a"
    assert select_rail(1_000, rails=rails[::-1]).rail.id == "a"


@pytest.mark.parametrize("bad", [0, -5, 1.5, True, "100"])
def test_invalid_amount_fails_closed(bad):
    assert select_rail(bad).rail is None


def test_unknown_objective_fails_closed():
    assert select_rail(AMOUNT, objective="cheapest-ish").rail is None


def test_empty_rail_list_fails_closed():
    assert select_rail(AMOUNT, rails=()).rail is None


def test_invalid_deadline_fails_closed():
    assert select_rail(AMOUNT, deadline_hours="12").rail is None
