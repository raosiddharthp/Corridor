"""Generate local development keys into .env. Never prints a key."""
import sys
from pathlib import Path

from pipeline import keys
from pipeline import mandates as m

ENV = Path(".env")
LOCAL_URL = "http://127.0.0.1:8081"


def generate() -> dict:
    user, agent, supplier = m.new_key(), m.new_key(), m.new_key()
    return {
        keys.USER_ENV: keys.export_private(user),
        keys.AGENT_ENV: keys.export_private(agent),
        keys.SUPPLIER_PRIVATE_ENV: keys.export_private(supplier),
        keys.SUPPLIER_PUBLIC_ENV: keys.export_public(supplier),
        "SUPPLIER_URL": LOCAL_URL,
        "SUPPLIER_PUBLIC_URL": LOCAL_URL,
    }


def main() -> int:
    existing = ENV.read_text() if ENV.exists() else ""
    if keys.USER_ENV in existing:
        print("keys already present in .env; nothing changed")
        return 0
    values = generate()
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    body = "".join(f"{name}='{value}'\n" for name, value in values.items())
    ENV.write_text(existing + prefix + body)
    print("wrote to .env:", ", ".join(values))
    return 0


if __name__ == "__main__":
    sys.exit(main())
