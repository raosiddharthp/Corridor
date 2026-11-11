"""Create fresh demo keys directly in Secret Manager. Never prints or stores a key."""
import subprocess
import sys

from pipeline import keys
from scripts import make_keys

REGION = "europe-west2"
SECRETS = {
    keys.USER_ENV: "corridor-key-user",
    keys.AGENT_ENV: "corridor-key-agent",
    keys.SUPPLIER_PRIVATE_ENV: "corridor-key-supplier",
    keys.SUPPLIER_PUBLIC_ENV: "corridor-supplier-public-key",
}


def _exists(name, run) -> bool:
    result = run(["gcloud", "secrets", "describe", name], capture_output=True, text=True)
    return result.returncode == 0


def push(values: dict, *, run=subprocess.run) -> list:
    stored = []
    for env_name, secret in SECRETS.items():
        if _exists(secret, run):
            command = ["gcloud", "secrets", "versions", "add", secret, "--data-file=-"]
        else:
            command = [
                "gcloud", "secrets", "create", secret, "--data-file=-",
                "--replication-policy=user-managed", f"--locations={REGION}",
            ]
        result = run(command, input=values[env_name], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"could not store {secret}")
        stored.append(secret)
    return stored


def main(argv=None, *, run=subprocess.run) -> int:
    args = sys.argv[1:] if argv is None else argv
    existing = [name for name in SECRETS.values() if _exists(name, run)]
    if existing and "--rotate" not in args:
        print(
            "secrets already exist:", ", ".join(existing),
            "- nothing changed (use --rotate to replace all four together)",
        )
        return 0
    stored = push(make_keys.generate(), run=run)
    print("stored in Secret Manager:", ", ".join(stored))
    return 0


if __name__ == "__main__":
    sys.exit(main())
