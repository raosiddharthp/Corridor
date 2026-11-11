import base64
import json
import os

import functions_framework
from google.cloud import run_v2

PROJECT = os.environ["GCP_PROJECT"]
REGION = os.environ.get("REGION", "europe-west2")
SERVICES = os.environ.get("GUARDED_SERVICES", "corridor-app,corridor-supplier").split(",")
BUDGET_NAME = "corridor-cap"


def lock(service: str) -> None:
    """Remove public access so requests are rejected before reaching the app."""
    client = run_v2.ServicesClient()
    name = f"projects/{PROJECT}/locations/{REGION}/services/{service}"
    policy = client.get_iam_policy(request={"resource": name})
    kept = []
    for binding in policy.bindings:
        if binding.role == "roles/run.invoker" and "allUsers" in binding.members:
            binding.members.remove("allUsers")
        if binding.members:
            kept.append(binding)
    del policy.bindings[:]
    policy.bindings.extend(kept)
    client.set_iam_policy(request={"resource": name, "policy": policy})


@functions_framework.cloud_event
def guard(cloud_event):
    payload = json.loads(base64.b64decode(cloud_event.data["message"]["data"]))
    cost = float(payload.get("costAmount", 0))
    limit = float(payload.get("budgetAmount", 0))
    name = payload.get("budgetDisplayName", "")
    print(json.dumps({"event": "budget_notification", "budget": name, "cost": cost, "limit": limit}))
    if name != BUDGET_NAME or limit <= 0 or cost < limit:
        return
    for service in SERVICES:
        lock(service)
        print(json.dumps({"event": "locked", "service": service}))
