# Corridor demo script

A five-minute walkthrough of the live proof of concept. Corridor is a fictional cross-border trade-settlement design: Halvorsen & Cole (buyer) pays BrunnerTeknik GmbH (supplier). Payments are simulated.

## Before you start

1. Open the live console from the Launch live POC button on the design page. The first request after idle takes a few seconds while both services start, so open the page a minute early.
2. Select **Reset demo state** so every run starts from a clean mandate.
3. Read the **Standing mandate** panel aloud: a cap of €345,000 per payment, a €1,400,000 budget, four uses, quarterly.

## Scene 1: the agreed order pays itself (Tier 1)

1. Under **Orders**, select FP-88213 (€340,000) and select **Run**.
2. Walk the timeline: the supplier's signed offer arrives, the Mandate Integrity Gate checks the mandate, the Compliance Screening Gate clears it, the rail engine picks SEPA credit transfer, and payment executes with a `SIM-sepa_sct-…` reference.
3. Point out: the order was within policy, so no human was involved.

Message: A2A negotiates, AP2 settles. The agent never moves money on its own say-so; every payment passes a gate that fails closed.

## Scene 2: price drift needs a human (Tier 2)

1. Select FP-88214 and **Run**.
2. The quote is 352 basis points above the agreed price against a tolerance of 100, so the run stops at **Human approval needed**. No payment has been built.
3. Select **Approve and pay**. A fresh mandate is signed for exactly the approved total, passes the same gate with a new nonce, and the payment executes.
4. Select **Approve and pay** again, or call approve a second time: it is refused. An approval is single use and expires after 15 minutes.

Message: approval does not loosen the gate. It produces a new, capped mandate that is checked like any other.

## Scene 3: a hostile supplier

1. Select **Reset demo state**, then FP-88213, turn on the hostile-supplier option under **Demo**, and select **Run**.
2. The supplier's note now contains an instruction aimed at the agent. The note is treated as untrusted data: it is sanitised, framed, and any proposal from the interpreter can only tighten the decision, never loosen it.
3. Show that the outcome is still decided by the signed checkout total, not by the note.

## Scene 4: the budget is real

1. Select **Reset demo state**.
2. Run FP-88213 four times. All four pay.
3. Run it a fifth time. It is blocked: the quarterly budget allows four uses, and the ledger enforces it independently of the agent.

## Close with the safety design

- Cost guard: a budget alert triggers a function that removes public access from both services. It was tested by sending a synthetic alert (see BUILD_LOG.md).
- Pause switch: setting `LIVE_ENABLED=false` stops runs and writes while the page and `/health` stay up.
- Limits stated honestly: payments are simulated, the user's signing key is held by the app for the demo, and state is in memory on a single instance, so a restart can lose a pending approval. The interpreter is rule-based; the Gemini interpreter is built and tested but not enabled live.

## If something looks wrong

- A run fails with "supplier could not be reached": wait ten seconds and run again; the supplier was starting.
- Everything returns 403: the cost guard has locked the services. Restore access with the IAM command in DEVELOPERS.md.
