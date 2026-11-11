# Corridor user guide

This guide shows you how to use the Corridor console. You run two example orders, approve one that needs a person, and see how the system protects itself.

Corridor is a design for settling a cross-border trade between two small businesses. The console is a working proof of concept. No money moves: every payment is simulated.

## What you are looking at

A buyer, Halvorsen & Cole, orders goods from a supplier, BrunnerTeknik GmbH. The buyer's software agent asks the supplier's agent for a quote. If the quote is what was agreed, the payment goes through on its own. If it isn't, the agent stops and asks a person.

You play the role of the buyer's finance approver.

## The console

The page has four areas:

- **Orders** lists the two example orders. Select one to run.
- **Standing mandate** shows the buyer's pre-agreed limits: the most one payment can be, the total budget, and how many payments are allowed in the period.
- **Demo** holds the controls for showing off the safety features, including **Reset demo state** and the hostile-supplier option.
- The timeline fills in as a run progresses, and a result card appears at the end.

## Run an order that pays automatically

1. Under **Orders**, select FP-88213.
2. Select **Run**.
3. Watch the timeline. Each line is a step the system took: the supplier's offer arrived, the mandate was checked, the parties were screened, a payment rail was chosen, and the payment was made.
4. Read the result card. The status is `paid`, the tier is Tier 1, and a reference starting `SIM-` shows the simulated payment.

Tier 1 means the order was within policy, so no person was needed.

## Run an order that needs approval

1. Select **Reset demo state** if you have already made several payments.
2. Select FP-88214, then select **Run**.
3. The run stops, and a card titled **Human approval needed** appears. It explains why: the supplier's price is 352 basis points above the agreed price, and the tolerance is 100.
4. Choose one of two actions:
   - Select **Approve and pay** to pay the higher price. The system signs a new, single-use authorisation for exactly that amount and pays.
   - Select **Reject** to stop. Nothing is paid.

An approval can be used once. If you select **Approve and pay** again for the same run, the system refuses. An approval also expires after 15 minutes.

## Try a hostile supplier

1. Select **Reset demo state**.
2. Turn on the hostile-supplier option under **Demo**.
3. Select FP-88213, then select **Run**.

The supplier's message now contains an instruction aimed at the buyer's agent. The system treats the message as untrusted text. It can make the system more cautious, but it can't make the system pay more or skip a check. The amount paid is always the one in the supplier's signed checkout.

## Reach the budget limit

1. Select **Reset demo state**.
2. Run FP-88213 four times. Each run pays.
3. Run it a fifth time. The run is blocked.

The standing mandate allows four payments in a period. A separate ledger counts them, so the limit holds even if the agent behaves badly.

## Read a result

| Field | What it tells you |
|---|---|
| Tier | Tier 1 paid automatically. Tier 2 needed a person. Blocked failed a check. |
| Status | `paid`, `awaiting_approval`, `rejected`, `blocked` or `failed`. |
| Reasons | Why the run stopped, in plain words. Empty when the order paid. |
| Rail | The payment route the system chose, such as SEPA credit transfer. |
| Reference | The simulated payment reference. |

A `failed` run means something went wrong outside the payment checks, for example the supplier did not answer. Nothing was paid.

## Terms

**A2A:** the open protocol the two agents use to talk and negotiate.

**AP2:** the open protocol that turns an agreed purchase into a signed, checkable payment authorisation.

**Mandate:** the buyer's signed permission for an agent to pay, with limits on amount, budget and number of uses.

**Mandate Integrity Gate:** the check that every payment must pass. It fails closed: if anything is in doubt, nothing is paid.

**Tier 1, Tier 2:** automatic payment, and payment that waits for a person.

## What this demo does not do

- It does not move real money. Every payment is simulated.
- It holds the approver's signing key itself, to keep the demo simple. A real system would keep that key with the approver.
- It keeps its state in memory. If the service restarts, a waiting approval can be lost. Run the order again.
- It uses a rule-based reader for the supplier's message. The Gemini-based reader is built but not switched on.

## If something goes wrong

**The first run is slow or fails with "supplier could not be reached".** The services are waking up. Wait ten seconds and run again.

**A banner says the demo is paused.** The owner has switched runs off. The page stays visible, and nothing can be run.

**The page doesn't load, or every request fails.** The automatic cost guard may have locked the services because the monthly budget was reached. The owner can restore access.
