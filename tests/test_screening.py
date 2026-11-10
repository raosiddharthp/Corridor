import pytest

import pipeline.seed as seed
from pipeline.screening import screen

LISTED = seed.SANCTIONS_SAMPLE


def test_seed_parties_are_clear():
    result = screen([seed.BUYER.name, seed.SUPPLIER.name], LISTED)
    assert result.status == "clear"
    assert result.passed
    assert result.reasons == ()


def test_exact_listed_name_is_blocked():
    result = screen(["Zelmarin Trading FZE"], LISTED)
    assert result.status == "blocked"
    assert not result.passed


def test_variants_of_a_listed_name_are_still_blocked():
    for variant in ["ZELMARIN TRADING", "zelmarin  trading, ltd.", "Zelmarín Trading FZE"]:
        assert screen([variant], LISTED).status == "blocked", variant


def test_near_match_goes_to_review():
    result = screen(["Zelmarin Tradings"], LISTED)
    assert result.status == "review"
    assert not result.passed


def test_blocked_outranks_review():
    result = screen(["Zelmarin Trading FZE", "Kesling Marine Holdings"], LISTED)
    assert result.status == "blocked"
    assert len(result.reasons) == 2


def test_empty_sanctions_list_fails_closed():
    assert screen([seed.SUPPLIER.name], []).status == "blocked"


@pytest.mark.parametrize("bad", ["", "   ", "GmbH", None])
def test_unscreenable_name_fails_closed(bad):
    assert screen([seed.SUPPLIER.name, bad], LISTED).status == "blocked"


def test_no_parties_fails_closed():
    assert screen([], LISTED).status == "blocked"
