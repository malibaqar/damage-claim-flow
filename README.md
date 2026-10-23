# Damage-Claim Flow Prototype

A small Python prototype of a post-trip damage-claim flow for a direct car-rental operator. It turns the rules from a written flow document into code that can be run and tested.

> **Status:** prototype for illustration. It is not connected to any real system, and it is not affiliated with or endorsed by 1Now, Turo or any other company. Sending messages and capturing deposits are stubs (marked `# STUB` in the code).

## The problem

An operator who rents cars directly (not through a marketplace) gets a car back with damage. The renter isn't answering, the deposit is only a temporary card hold, and the same car is booked again in two days. The operator is alone, with several clocks running at once.

This prototype models the loop from the first report to a claim the operator confirms has left them whole.

## What it does

| Step | Rule in code |
|---|---|
| 0. Sort | Turo trips are handed back; injury or police cases leave the standard flow |
| Triage | Tiers T0 to T4 (not damage, cosmetic, needs a shop, undriveable, safety) |
| 2. Two clocks | Decide one day before the deposit hold lapses; flag a next booking inside 7 days |
| 3. Evidence | Clear, unclear, no evidence, or already visible at pickup |
| 4. Renter contact | Notice, second contact at 24 hours, proceed on evidence at 48 hours |
| 5. Who pays | Ordered funding sources, each with what to watch for |
| Gates | No charge without operator approval, before the renter is notified, after the hold is gone, over the hold amount, or on unclear evidence |
| 7. Money | Any excess over the final repair bill is refunded |
| 8. Close | A ledger is built; only the operator can close the claim |
| Messages | Templates A to G (operator, renter, next renter, closing summary) |

## Run it

Standard library only. Written for Python 3.9+, tested on Python 3.12.

```bash
python demo.py              # walks one example claim through every step
python -m unittest -v       # runs the 20 tests
```

## Files

- `claim_flow.py`: the rules, gates, message templates and ledger
- `demo.py`: a fixed-date walkthrough of an example claim
- `test_claim_flow.py`: unit tests for the rules that matter most

## Assumptions to verify before real use

- **Hold length.** The demo assumes a 5-day deposit hold. Real hold length depends on the payment setup.
- **Rental agreement.** Whether a charge is allowed after the hold is released, and the claim window, depend on the signed agreement.
- **Damage cover.** What a renter-purchased damage cover includes and excludes varies by provider.
- **Thresholds.** Triage uses the deposit amount and a 7-day booking window as starting points.

## Connecting real systems

Replace the stubs in `claim_flow.py`:

- `send(...)`: the real SMS, email or in-app message call
- `capture_deposit(...)`: the real payment call (keep the gate checks in front of it)
