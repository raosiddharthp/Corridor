# Corridor developer guide

This guide explains how Corridor is built, how to run and test it, how to deploy it to Google Cloud, and how to operate it. For a walkthrough of the console, see USER_GUIDE.md. For a presenter's script, see DEMO_SCRIPT.md. For the mistakes made along the way, see BUILD_LOG.md.

Corridor is a proof of concept. It is a design for settling a cross-border trade between two small businesses, built on Google's A2A and AP2 protocols. Payments are simulated.

## How it works

The rule is: A2A negotiates, AP2 settles. A buyer's agent asks a supplier's agent for a quote over A2A. Nothing is paid until five gated components agree.

| Component | Module | Job |
|---|---|---|
| Negotiation Agent | `pipeline/negotiation.py` | Requests a quote from the supplier over A2A. Treats everything the supplier sends as untrusted. |
| Mandate Integrity Gate | `pipeline/gate.py`, `pipeline/payment_gate.py` | Verifies the mandate chain and the supplier-signed checkout. Fails closed. |
| Compliance Screening Gate | `pipeline/screening.py` | Screens the parties and the payment before any rail is chosen. |
| Rail Selection Engine | `pipeline/rails.py` | Chooses a payment rail for the verified total. |
| Payment Execution Agent | `pipeline/payments.py` | Executes the payment. Idempotent on the transaction ID. |

`pipeline/orchestrator.py` runs the components in order and routes each order to a tier:

- **Tier 1:** the order is within policy and pays automatically.
- **Tier 2:** the order needs a person. The run stops at `awaiting_approval` and no payment is built.

The orchestrator routes on the total in the supplier-signed checkout, never on a total the supplier merely claims. If the claimed total or the checkout hash does not match, the run is blocked.

### Design decisions

The design page (`index.html`) records decisions CR-01 to CR-06. Two more came out of the build:

- **CR-07:** the gate recomputes every check itself and cross-checks the result against the AP2 SDK's verdict. A disagreement blocks the payment.
- **CR-08:** approving a Tier 2 order creates a fresh mandate signed by the user's key. The mandate is capped at the approved total and passes through the same gate with a new nonce. Approval never loosens the gate.

### The interpreter

The negotiation note from the supplier is free text, so Corridor treats it as hostile. `pipeline/untrusted.py` sanitises and frames the note. `pipeline/interpreter.py` turns it into a proposal (`accept` or `escalate`). A proposal can only tighten the decision (`apply()`), never loosen it, and a malformed proposal falls back to `escalate`.

Two interpreters exist. `RuleInterpreter` is the default. `GeminiInterpreter` (`pipeline/gemini.py`) is built and tested, and it is not enabled in the live deployment.

## Repository layout

| Path | Contents |
|---|---|
| `app/` | The main service: FastAPI app (`main.py`), run API (`runs.py`), wiring (`deps.py`), and the console in `static/`. |
| `supplier/` | The supplier agent: A2A agent card and endpoint (`app.py`), quote logic (`quotes.py`), entry point (`main.py`). |
| `pipeline/` | The settlement logic. No web code. |
| `guard/` | The cost-guard Cloud Function. |
| `scripts/` | `make_keys.py` (local keys), `cloud_keys.py` (Secret Manager keys), `commit_if_green.sh`. |
| `tests/` | The test suite. |
| `index.html` | The design document, with the Launch live POC button. |

Other `pipeline/` modules: `challenge.py` (single-use nonces), `checkout.py` (the signed checkout), `ledger.py` (spend limits), `mandates.py` (mandate construction), `tiering.py` (tier rules), `approvals.py` (pending approvals), `events.py` (the event log), `keys.py` (key loading), `seed.py` (the demo parties).

## Set up locally

You need Python 3.11 and git. Git is required because the AP2 SDK is installed from a pinned commit.

1. Create an environment and install the dependencies:

   ```
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```

2. Generate demo keys. The script writes `.env`, which is gitignored, and never prints a key:

   ```
   python -m scripts.make_keys
   ```

3. Run the tests:

   ```
   python -m pytest -q
   ```

## Run the services locally

Run each service in its own terminal, with `.env` loaded:

```
set -a; source .env; set +a
uvicorn supplier.main:build --factory --port 8081
```

```
set -a; source .env; set +a
uvicorn app.main:app --port 8080
```

Open http://127.0.0.1:8080 for the console.

## Configuration

| Variable | Service | Purpose |
|---|---|---|
| `CORRIDOR_KEY_USER` | app | The buyer's signing key (simulated user). |
| `CORRIDOR_KEY_AGENT` | app | The buyer agent's signing key. |
| `CORRIDOR_SUPPLIER_PUBLIC_KEY` | app | The supplier's public key, used to verify checkouts. |
| `CORRIDOR_KEY_SUPPLIER` | supplier | The supplier's private key. The app never receives it. |
| `SUPPLIER_URL` | app | Where the app reaches the supplier. |
| `SUPPLIER_PUBLIC_URL` | both | The supplier's public address, written into its agent card. |
| `INTERPRETER` | app | `rule` (default) or `gemini`. |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | app | Needed only when `INTERPRETER=gemini`. |
| `LIVE_ENABLED` | app | Set to `false` to pause runs and writes. |
| `SERVICE` | container | `supplier` runs the supplier. Anything else runs the app. |

## API

| Method and path | Purpose |
|---|---|
| `POST /runs` | Starts a run for `{"order_ref": "FP-88213"}` and streams server-sent events, ending with a `result` event. |
| `GET /runs/{id}/events?after=N` | Replays a run's events after sequence number N. |
| `POST /runs/{id}/approve` | Approves a Tier 2 run. A second call returns 404. |
| `POST /runs/{id}/reject` | Rejects a Tier 2 run. |
| `POST /demo/reset` | Clears the ledger and pending approvals. Ten-second cooldown. |
| `GET /config` | Public facts about the demo: the mandate, the tolerance, the scenarios. |
| `GET /health` | Liveness and pause state. |

The app allows four concurrent runs and 30 runs a minute. Pending approvals are single use and expire after 15 minutes. The event log redacts any field whose name suggests a secret.

## The ledger

The spend ledger enforces the standing mandate independently of the agent: four uses and a €1,400,000 budget per period. The fifth paid run is blocked. A test proves it.

## Deploy to Google Cloud

Both services run from one image. The `SERVICE` variable selects which one starts. The steps below assume project `corridor-poc-12144` and region `europe-west2`.

1. Create the keys directly in Secret Manager. Keys never reach your terminal:

   ```
   python -m scripts.cloud_keys
   ```

   The script refuses to overwrite existing secrets. To replace all four together, add `--rotate`, then deploy a new revision of each service.

2. Build the image. The tag is the commit hash:

   ```
   TAG=$(git rev-parse --short HEAD)
   gcloud builds submit --tag europe-west2-docker.pkg.dev/corridor-poc-12144/cloud-run-source-deploy/corridor:$TAG .
   ```

3. Create one service account for each service. Grant each only the secrets it needs (`roles/secretmanager.secretAccessor`): the app gets the user key, agent key and supplier public key, and the supplier gets only its own key. After creating a service account, wait and check the binding with `gcloud secrets get-iam-policy` before you deploy. New accounts take a moment to become visible.

4. Deploy the supplier, then the app. Set `SUPPLIER_URL` and `SUPPLIER_PUBLIC_URL` to the supplier's address, and map the secrets with `--set-secrets`. Use `--min-instances=0` and `--max-instances=1`. The app keeps its state in memory, so it must stay on one instance.

5. Open the app's address and run FP-88213. It should pay on Tier 1. Run FP-88214 and approve it.

## Operate

### Pause the app

Set `LIVE_ENABLED=false` on the app service. Runs and writes return 503. The page, `/config` and `/health` stay up.

### The cost guard

A budget named `corridor-cap` publishes to the topic `corridor-budget-alerts`. The function in `guard/` receives each message. When spend reaches the cap, it removes public access (`allUsers` as invoker) from the services listed in `GUARDED_SERVICES`. It ignores every other budget and every message below the cap.

To change the guarded services, redeploy the function. A comma inside a gcloud value needs another pair separator:

```
gcloud functions deploy corridor-guard --gen2 --region=europe-west2 \
  --runtime=python311 --entry-point=guard --source=guard \
  --update-env-vars='^@^GUARDED_SERVICES=corridor-app,corridor-supplier'
```

### Restore access after the guard fires

Public access returns when you add it back. Cloud Run can take a minute or more to apply IAM changes.

```
for s in corridor-app corridor-supplier; do
  gcloud run services add-iam-policy-binding $s --region=europe-west2 \
    --member=allUsers --role=roles/run.invoker --quiet
done
```

### Test the guard

Send a synthetic alert, wait, then read the structured log. The guard prints JSON, so filter on `jsonPayload.event`:

```
gcloud pubsub topics publish corridor-budget-alerts \
  --message='{"budgetDisplayName":"corridor-cap","costAmount":1.0,"budgetAmount":1.0}'
gcloud logging read 'resource.labels.service_name="corridor-guard" AND jsonPayload.event="locked"' \
  --limit=6 --format="table(timestamp,jsonPayload.service)"
```

This locks both services. Restore access afterwards.

### Clean up images

Each build adds an image. Delete old ones to stay inside the free Artifact Registry allowance.

## Known limits

- Payments are simulated. References look like `SIM-sepa_sct-xxxxxxxx`.
- The user's signing key is held by the app for the demo. A real deployment would keep it on the user's device.
- Pending approvals, the ledger and the event log are in memory on one instance. A restart or a scale to zero loses them. Persisting them in Firestore is a possible extension.
- The supplier service is public. Making it private with service-to-service ID tokens is a possible hardening.
- The Gemini interpreter is not enabled live. The model API returned a location error from the build environment.

## Troubleshoot

| Symptom | Cause and fix |
|---|---|
| Run ends `failed`: "supplier could not be reached" | The supplier is starting or its address is wrong. Check `SUPPLIER_URL` and run again. |
| Every request returns 403 | The cost guard locked the services. Restore access as shown above. |
| Deploy fails with a secret permission error | The service account lacks `secretAccessor` on that secret, or the account is new. Check the binding, then deploy again. |
| `/runs` returns 503 | `LIVE_ENABLED` is `false`, or the app is missing its keys or `SUPPLIER_URL`. |
