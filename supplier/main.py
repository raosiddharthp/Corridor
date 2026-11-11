"""Supplier service entrypoint. Run with: uvicorn supplier.main:build --factory"""
import os

from pipeline.keys import load_supplier_signing_key
from supplier.app import create_app


def build(env=None):
    env = os.environ if env is None else env
    base_url = env.get("SUPPLIER_PUBLIC_URL", "")
    if not base_url:
        raise RuntimeError("SUPPLIER_PUBLIC_URL is not set")
    return create_app(load_supplier_signing_key(env), base_url)
