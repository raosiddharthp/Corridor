import pipeline.seed as seed


def _tolerance_limit(agreed):
    return agreed * (10_000 + seed.PRICE_TOLERANCE_BPS) // 10_000


def test_fp_88213_is_in_policy():
    s = seed.FP_88213
    assert s.quoted_minor <= _tolerance_limit(s.agreed_minor)
    assert s.quoted_minor <= seed.MANDATE_CAP_MINOR
    assert s.expected_tier == 1


def test_fp_88214_breaches_tolerance_and_cap():
    s = seed.FP_88214
    assert s.quoted_minor > _tolerance_limit(s.agreed_minor)
    assert s.quoted_minor > seed.MANDATE_CAP_MINOR
    assert s.expected_tier == 2


def test_tolerance_is_tighter_than_the_mandate_cap():
    assert _tolerance_limit(seed.FP_88213.agreed_minor) < seed.MANDATE_CAP_MINOR


def test_budget_covers_every_permitted_use():
    assert seed.MANDATE_MAX_USES * seed.FP_88213.agreed_minor <= seed.MANDATE_BUDGET_MINOR


def test_supplier_is_allowlisted_and_not_sanctioned():
    assert seed.SUPPLIER.id in seed.ALLOWED_PAYEES
    assert seed.SUPPLIER.name not in seed.SANCTIONS_SAMPLE


def test_rail_ids_are_unique():
    ids = [r.id for r in seed.RAILS]
    assert len(ids) == len(set(ids))


def test_rails_have_a_real_choice_for_the_order():
    amount = seed.FP_88213.agreed_minor
    capable = [r.id for r in seed.RAILS if r.max_minor is None or r.max_minor >= amount]
    assert "sepa_inst" not in capable
    assert len(capable) >= 2
