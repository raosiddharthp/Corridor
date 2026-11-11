# Build log

Mistakes, dead ends and variations from building Corridor, in the order they happened. Each entry: what happened, the cause, the fix, and what to do differently.

## Setup and cost safety

### Almost repointed another project's gcloud config
- **What happened:** the plan used `gcloud config set project`, which would have changed the active configuration used by another portfolio project.
- **Fix:** a separate named `corridor` configuration.
- **Lesson:** with a shared machine and shared billing account, isolate configurations first.

### A placeholder ID pasted literally
- **What happened:** `XXXX` was pasted as the project ID and the commands cascaded into failures.
- **Fix:** generate the ID in the shell (`corridor-poc-$RANDOM`) so nothing needs editing.

### Budgets API refused the call
- **Cause:** the call needed a quota project, and the shared application-default credentials point at another project.
- **Fix:** enable the Budgets API in this project and pass `--billing-project`. The shared credentials were deliberately left alone.

### Budget parsed as 50 nanos
- **What happened:** the SGD 0.50 cap was read as `nanos=50`.
- **Fix:** write it as `0.500000000SGD`, and exclude credits so the cap counts real spend.
- **Lesson:** read the budget back after creating it.

### The spend guard failed twice
- **First failure:** the guard's service account lacked permission to change the service's IAM policy.
- **Second failure:** after switching the trigger to a dedicated service account, that account lacked `run.invoker` on the guard service, so events were rejected with 403 and retried.
- **Fix:** two IAM bindings.
- **Lesson:** an event-driven function has two identities to permission: the caller and the callee.

### Log search found nothing
- **Cause:** structured JSON logs land in `jsonPayload`, so plain-text search misses them.
- **Fix:** query `jsonPayload.event="locked"`.

## Working habits

### Pasted scripts that ran twice
- **What happened:** a repeated heredoc appended duplicate tests.
- **Fix:** scripts now check before changing anything (match count or "already added"), and commits only follow a green run.

### Tests ran fine under one command and not another
- **What happened:** bare `pytest` could not import the SDK, while `python -m pytest` could.
- **Status:** worked around with `python -m pytest`. Root cause not investigated.

## AP2 mandates

### Enum values would not serialise
- **What happened:** signing a recurrence constraint failed because the frequency enum was not JSON serialisable.
- **Fix:** a small subclass that stores enum values as strings.
- **Cost:** harmless serializer warnings in test output.

### A recurrence needs a budget
- **What happened:** the SDK refused a recurrence constraint without a budget constraint.
- **Fix:** the mandate builder requires both together.

### The budget "did nothing"
- **Symptom:** no violation at any spend up to 200,000,000 against a 140,000,000 budget.
- **First guesses (wrong):** period logic, then interference from the enum workaround.
- **Cause:** the SDK reads `Budget.max` in major units (euros) and converts to cents itself, while the amount constraint uses cents. A cents value was passed, so the effective budget was 100 times too large.
- **Fix:** pass `cents / 100`, and pin it with an exact-boundary test.
- **Lesson:** read the evaluator source before theorising. The SDK's mixed units are also a reason the gate keeps its own exact-integer check, because the SDK converts with `int(max * 100)` and float rounding can lose a cent.

### A boundary test used the wrong constant and was committed red
- **What happened:** the test used the per-payment cap where the actual payment amount belonged, and the commit went out before the run was checked.
- **Fix:** corrected forward in a second commit rather than rewriting history.

### A public key was accepted as a private one
- **What happened:** exporting a public-only JWK with the private flag did not raise, so the key loader accepted it.
- **Caught by:** a negative test.
- **Fix:** an explicit check for the private component.
- **Lesson:** assert the property yourself instead of inferring it from how a library behaves.

## Mandate Integrity Gate

### Why the gate re-checks what the SDK already checks
- **Finding:** the SDK's verify step only checks signatures and the chain. Constraints are evaluated separately, the spend history has to be supplied by the caller, `Budget.max` is in euros while everything else is in cents, and the budget conversion truncates, so a float like 19.99 can lose a cent.
- **Decision:** the gate re-derives payee, cap, budget and recurrence itself in exact integers. If the SDK says ok and the gate disagrees, the payment is rejected and the disagreement is logged.
- **Lesson:** a protocol's reference verifier is not a substitute for your own checks.

### Testing the independent check needed the SDK silenced
- **What happened:** the SDK catches the same violations first, so the gate's own check could never fail in a normal test.
- **Fix:** tests replace the SDK verdict with "ok" to prove the gate's own check catches the violation on its own.

### The SDK reads the supplier's checkout without verifying who signed it
- **Finding:** the checkout chain only decodes the payload of the supplier's signed order. Nothing in it verifies the signature, and the SDK never computes the checkout hash, it only compares one.
- **Decision:** the gate verifies the supplier's signature against a key it already trusts, and recomputes the hash itself (base64url of SHA-256 over the signed JWT string).
- **Lesson:** "verify" in a library can mean "parse and check constraints". Read what it actually checks.

## Working habits (continued)

### Test counts as a signal
- **What happened:** predicted pass counts were wrong twice (parametrised cases each count as a test, and one count was simply miscounted). Once, the count did not move at all after a step because the new files had not been written.
- **Lesson:** compare against the previous count, not a prediction. A count that stays put after adding tests is the cheapest sign that nothing was applied.

## Keys and services

### One process held every private key
- **What happened:** the first key loader required the user, agent and supplier private keys in one environment, so the main service would have held the supplier's signing key.
- **Cause:** the keys were modelled as a list of three roles instead of as trust domains.
- **Fix:** the main service holds the user and agent private keys and only the supplier's public key. The supplier service holds only its own private key. A private key in the public slot is rejected, and the ephemeral-key mode was removed because it could not work across two services.
- **Lesson:** key roles map to services, not to a list.

## A2A

### A2A 1.x wants a Task before any status event
- **Symptom:** every client call failed with "Agent should enqueue Task before TaskStatusUpdateEvent event", while the Agent Card route worked.
- **Cause:** the executor was written from the older pattern where the first status update creates the task. In a2a-sdk 1.x the executor must enqueue a Task first.
- **Fix:** enqueue a submitted Task before the first status update.
- **Lesson:** when an SDK's major version is newer than what you know, run the server and the client end to end before building on top of it.

### Committed red, again
- **What happened:** the supplier tests were committed with five failures because the "only if green" rule depended on someone reading the output.
- **Fix:** a small script (`scripts/commit_if_green.sh`) now runs the suite and refuses to commit on failure.

## Prompt injection

### A safety test measured the wrong thing
- **Symptom:** a test expecting one closing delimiter in the model prompt found two.
- **Cause:** the instruction text names both delimiters, so one closing tag is always there before the note. The note was escaped correctly; the assertion was wrong.
- **Fix:** compare against the prompt for a harmless note, so the test asserts that a hostile note adds no extra delimiter.
- **Lesson:** assert the property you care about ("the attacker adds nothing"), not a literal count that depends on unrelated text.
