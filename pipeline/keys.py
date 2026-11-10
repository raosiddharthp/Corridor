"""Signing keys for the three roles: user, agent, supplier.

Keys arrive as private JWK JSON in environment variables. Missing or
inconsistent configuration fails closed.
"""
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

from jwcrypto.jwk import JWK

from pipeline.mandates import new_key

ROLES = ("user", "agent", "supplier")
ENV_PREFIX = "CORRIDOR_KEY_"
EPHEMERAL_FLAG = "CORRIDOR_ALLOW_EPHEMERAL_KEYS"


class KeyConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class KeySet:
    user: JWK
    agent: JWK
    supplier: JWK
    ephemeral: bool


def export_private(key: JWK) -> str:
    return key.export(private_key=True)


def _parse(role: str, raw: str) -> JWK:
    try:
        key = JWK.from_json(raw)
        if "d" not in json.loads(key.export(private_key=True)):
            raise ValueError("no private part")
    except Exception as exc:
        raise KeyConfigError(f"{role} key is not a valid private JWK") from exc
    return key


def load_keys(env: Mapping[str, str] | None = None) -> KeySet:
    env = os.environ if env is None else env
    raw = {r: env.get(ENV_PREFIX + r.upper(), "").strip() for r in ROLES}
    present = [r for r in ROLES if raw[r]]

    if not present:
        if env.get(EPHEMERAL_FLAG, "false").lower() != "true":
            raise KeyConfigError(
                "no signing keys configured and ephemeral keys are not allowed"
            )
        keys = {r: new_key() for r in ROLES}
        ephemeral = True
    elif len(present) < len(ROLES):
        missing = ", ".join(r for r in ROLES if r not in present)
        raise KeyConfigError(f"partial key configuration, missing: {missing}")
    else:
        keys = {r: _parse(r, raw[r]) for r in ROLES}
        ephemeral = False

    if len({key.thumbprint() for key in keys.values()}) != len(ROLES):
        raise KeyConfigError("signing roles must use distinct keys")
    return KeySet(**keys, ephemeral=ephemeral)
