"""Signing keys, split by trust domain.

Main service: the user's (simulated device) key, the agent's key, and the
supplier's PUBLIC key. Supplier service: only the supplier's private key.
Missing or inconsistent configuration fails closed.
"""
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

from jwcrypto.jwk import JWK

USER_ENV = "CORRIDOR_KEY_USER"
AGENT_ENV = "CORRIDOR_KEY_AGENT"
SUPPLIER_PRIVATE_ENV = "CORRIDOR_KEY_SUPPLIER"
SUPPLIER_PUBLIC_ENV = "CORRIDOR_SUPPLIER_PUBLIC_KEY"


class KeyConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class KeySet:
    user: JWK
    agent: JWK
    supplier_public: JWK


def export_private(key: JWK) -> str:
    return key.export(private_key=True)


def export_public(key: JWK) -> str:
    return key.export_public()


def _read(env: Mapping[str, str], name: str) -> str:
    raw = env.get(name, "").strip()
    if not raw:
        raise KeyConfigError(f"{name} is not set")
    return raw


def _private(env: Mapping[str, str], name: str) -> JWK:
    raw = _read(env, name)
    try:
        key = JWK.from_json(raw)
        if "d" not in json.loads(key.export(private_key=True)):
            raise ValueError("no private part")
    except Exception as exc:
        raise KeyConfigError(f"{name} is not a valid private JWK") from exc
    return key


def _public_only(env: Mapping[str, str], name: str) -> JWK:
    raw = _read(env, name)
    try:
        if "d" in json.loads(raw):
            raise KeyConfigError(f"{name} must be a public key only")
        return JWK.from_json(raw)
    except KeyConfigError:
        raise
    except Exception as exc:
        raise KeyConfigError(f"{name} is not a valid public JWK") from exc


def load_keys(env: Mapping[str, str] | None = None) -> KeySet:
    """Keys for the main service."""
    env = os.environ if env is None else env
    keys = KeySet(
        user=_private(env, USER_ENV),
        agent=_private(env, AGENT_ENV),
        supplier_public=_public_only(env, SUPPLIER_PUBLIC_ENV),
    )
    thumbprints = {keys.user.thumbprint(), keys.agent.thumbprint(), keys.supplier_public.thumbprint()}
    if len(thumbprints) != 3:
        raise KeyConfigError("signing roles must use distinct keys")
    return keys


def load_supplier_signing_key(env: Mapping[str, str] | None = None) -> JWK:
    """Key for the supplier service. The main service never holds this."""
    env = os.environ if env is None else env
    return _private(env, SUPPLIER_PRIVATE_ENV)
