import pytest

import pipeline.keys as keys_mod
from pipeline.mandates import new_key


def _env(**roles):
    return {keys_mod.ENV_PREFIX + r.upper(): v for r, v in roles.items()}


def _full():
    return _env(**{r: keys_mod.export_private(new_key()) for r in keys_mod.ROLES})


def test_loads_three_distinct_keys():
    ks = keys_mod.load_keys(_full())
    assert not ks.ephemeral
    thumbs = {ks.user.thumbprint(), ks.agent.thumbprint(), ks.supplier.thumbprint()}
    assert len(thumbs) == 3


def test_nothing_configured_fails_closed():
    with pytest.raises(keys_mod.KeyConfigError, match="not allowed"):
        keys_mod.load_keys({})


def test_ephemeral_keys_only_when_flagged():
    ks = keys_mod.load_keys({keys_mod.EPHEMERAL_FLAG: "true"})
    assert ks.ephemeral
    assert len({ks.user.thumbprint(), ks.agent.thumbprint(), ks.supplier.thumbprint()}) == 3


def test_partial_configuration_fails_closed():
    env = _env(user=keys_mod.export_private(new_key()))
    with pytest.raises(keys_mod.KeyConfigError, match="missing"):
        keys_mod.load_keys(env)


def test_same_key_for_two_roles_is_rejected():
    shared = keys_mod.export_private(new_key())
    env = _env(user=shared, agent=shared, supplier=keys_mod.export_private(new_key()))
    with pytest.raises(keys_mod.KeyConfigError, match="distinct"):
        keys_mod.load_keys(env)


def test_public_key_is_rejected_as_private():
    env = _full()
    env[keys_mod.ENV_PREFIX + "AGENT"] = new_key().export_public()
    with pytest.raises(keys_mod.KeyConfigError, match="agent"):
        keys_mod.load_keys(env)


def test_garbage_is_rejected():
    env = _full()
    env[keys_mod.ENV_PREFIX + "SUPPLIER"] = "not json"
    with pytest.raises(keys_mod.KeyConfigError, match="supplier"):
        keys_mod.load_keys(env)
