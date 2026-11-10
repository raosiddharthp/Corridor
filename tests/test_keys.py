import pytest

import pipeline.keys as k
from pipeline.mandates import new_key


def _env(**overrides):
    env = {
        k.USER_ENV: k.export_private(new_key()),
        k.AGENT_ENV: k.export_private(new_key()),
        k.SUPPLIER_PUBLIC_ENV: k.export_public(new_key()),
    }
    env.update(overrides)
    return env


def test_loads_user_agent_and_supplier_public_keys():
    supplier = new_key()
    env = _env(**{k.SUPPLIER_PUBLIC_ENV: k.export_public(supplier)})
    ks = k.load_keys(env)
    assert ks.supplier_public.thumbprint() == supplier.thumbprint()
    assert len({ks.user.thumbprint(), ks.agent.thumbprint(), ks.supplier_public.thumbprint()}) == 3


def test_nothing_configured_fails_closed():
    with pytest.raises(k.KeyConfigError, match="not set"):
        k.load_keys({})


@pytest.mark.parametrize("name", [k.USER_ENV, k.AGENT_ENV, k.SUPPLIER_PUBLIC_ENV])
def test_each_missing_variable_fails_closed(name):
    env = _env()
    del env[name]
    with pytest.raises(k.KeyConfigError, match=name):
        k.load_keys(env)


def test_same_key_for_user_and_agent_is_rejected():
    shared = k.export_private(new_key())
    with pytest.raises(k.KeyConfigError, match="distinct"):
        k.load_keys(_env(**{k.USER_ENV: shared, k.AGENT_ENV: shared}))


def test_supplier_public_key_equal_to_the_agents_key_is_rejected():
    agent = new_key()
    env = _env(**{k.AGENT_ENV: k.export_private(agent), k.SUPPLIER_PUBLIC_ENV: k.export_public(agent)})
    with pytest.raises(k.KeyConfigError, match="distinct"):
        k.load_keys(env)


def test_public_key_is_rejected_where_a_private_key_is_required():
    env = _env(**{k.AGENT_ENV: k.export_public(new_key())})
    with pytest.raises(k.KeyConfigError, match=k.AGENT_ENV):
        k.load_keys(env)


def test_private_key_is_rejected_as_the_supplier_public_key():
    env = _env(**{k.SUPPLIER_PUBLIC_ENV: k.export_private(new_key())})
    with pytest.raises(k.KeyConfigError, match="public key only"):
        k.load_keys(env)


def test_garbage_is_rejected():
    with pytest.raises(k.KeyConfigError, match=k.USER_ENV):
        k.load_keys(_env(**{k.USER_ENV: "not json"}))


def test_supplier_signing_key_loads():
    supplier = new_key()
    loaded = k.load_supplier_signing_key({k.SUPPLIER_PRIVATE_ENV: k.export_private(supplier)})
    assert loaded.thumbprint() == supplier.thumbprint()


def test_supplier_signing_key_missing_fails_closed():
    with pytest.raises(k.KeyConfigError, match="not set"):
        k.load_supplier_signing_key({})


def test_supplier_signing_key_rejects_a_public_key():
    with pytest.raises(k.KeyConfigError, match=k.SUPPLIER_PRIVATE_ENV):
        k.load_supplier_signing_key({k.SUPPLIER_PRIVATE_ENV: k.export_public(new_key())})
