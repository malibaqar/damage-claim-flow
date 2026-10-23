"""
Run:  python demo.py
Walks the document's Monday-morning scenario through the flow, step by step.
Dates are fixed so the output is the same every time.
"""
from datetime import datetime, timedelta

import claim_flow as cf


def stamp(t: datetime) -> str:
    return t.strftime("%a %H:%M")


def heading(text: str) -> None:
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


def main() -> None:
    now = datetime(2026, 10, 19, 8, 40)  # a Monday, 8:40 a.m.

    claim = cf.Claim(
        booking_id="1001", car="Tesla Model 3", operator="Ali", renter="Sara",
        damage="scrape on the rear passenger door and a cracked bumper corner",
        reported_at=now,
        hold_amount=500.0,
        hold_expires_at=now + timedelta(days=5),            # ASSUMPTION: confirm real hold length
        next_booking_start=now + timedelta(days=2),         # booked again Wednesday
        pickup_photos=True, return_photos=True, damage_in_pickup_photos=False,
        drivable=True, needs_shop=True,
    )

    heading("STEP 0  Sort")
    route = cf.step0_sort(claim)
    print(f"  Route: {route.value}")
    print(f"  Tier : {cf.triage(claim, now).name} ({cf.triage(claim, now).value})")

    heading("STEP 1  Intake and acknowledgement (Message A)")
    clocks = cf.check_clocks(claim, now)
    hold_line = (f"your hold ends {stamp(claim.hold_expires_at)}, so we decide by "
                 f"{stamp(clocks['decision_by'])};")
    cf.send("operator", cf.render(
        "A", operator=claim.operator, booking=claim.booking_id, car=claim.car,
        hold_line=hold_line, photo_by=stamp(now + timedelta(hours=4)),
        renter_by=stamp(now + timedelta(days=1)), renter=claim.renter,
        update_by=stamp(now + timedelta(hours=24))), claim, now)

    heading("STEP 2  Protect the two clocks")
    print(f"  Hold status        : {clocks['hold']}")
    print(f"  Decide by          : {stamp(clocks['decision_by'])}")
    print(f"  Next booking action: {clocks['next_booking']}")
    cf.send("next renter", cf.render(
        "G", name="Omar", car=claim.car, dates="Wed to Fri",
        offer="a similar car at the same price, other dates, or a full refund today"),
        claim, now)

    heading("STEP 3  Evidence")
    print(f"  Evidence class: {cf.classify_evidence(claim).value}")

    heading("STEP 4  Tell the renter first (Message B), after operator approval")
    print(f"  Next action: {cf.next_renter_action(claim, now)}")
    cf.approve(claim, "renter-notice", now)
    claim.renter_notified_at = now + timedelta(hours=3)
    cf.send("renter", cf.render(
        "B", renter=claim.renter, business="Ali's Rentals", car=claim.car,
        damage=claim.damage, reply_by=stamp(claim.renter_notified_at + timedelta(hours=48)),
        operator=claim.operator), claim, claim.renter_notified_at)

    heading("STEP 4b  The renter is silent: the cadence takes over")
    for hours in (6, 26, 50):
        t = claim.renter_notified_at + timedelta(hours=hours)
        print(f"  +{hours:>2}h: {cf.next_renter_action(claim, t)}")
    now = claim.renter_notified_at + timedelta(hours=50)

    heading("STEP 5  Who pays")
    claim.estimate = 420.0
    for source, watch in cf.funding_options(claim, now):
        print(f"  - {source.value}: {watch}")

    heading("STEP 5b  The gates (what the code refuses to do)")
    probe = cf.Claim(**{**claim.__dict__, "approvals": set(), "log": []})
    for label, setup in (
        ("charge without operator approval", lambda p: None),
        ("charge before the renter is notified",
         lambda p: (p.approvals.add("capture"), setattr(p, "renter_notified_at", None))),
    ):
        setup(probe)
        try:
            cf.capture_deposit(probe, 420.0, now)
        except cf.GateError as err:
            print(f"  BLOCKED ({label}): {err}")

    heading("STEP 6 and 7  Decide, then move the money (after approval)")
    cf.approve(claim, "capture", now)
    cf.capture_deposit(claim, 420.0, now)
    print(f"  Captured so far: ${claim.amount_captured:,.2f}")
    final_cost = 400.0  # the final repair bill came in lower
    refunded = cf.refund_excess(claim, final_cost, now)
    print(f"  Refunded to renter: ${refunded:,.2f}")

    heading("STEP 8  Close with a ledger (Message E)")
    ledger = cf.build_ledger(claim, final_cost, {cf.Funding.DEPOSIT_HOLD: claim.amount_captured})
    cf.send("operator", cf.render(
        "E", booking=claim.booking_id, cost=f"{ledger['final_cost']:,.2f}",
        recovered=f"{ledger['total_recovered']:,.2f}", gap=f"{ledger['gap']:,.2f}",
        gap_line="Nothing is outstanding."), claim, now)
    print(f"\n  Operator answers 'not yet': {cf.try_close(claim, False, now)}")
    print(f"  Operator answers 'yes'    : {cf.try_close(claim, True, now)}")

    heading("AUDIT LOG")
    for line in claim.log:
        print(f"  {line}")


if __name__ == "__main__":
    main()
