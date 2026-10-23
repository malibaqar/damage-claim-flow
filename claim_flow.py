"""
Damage-claim flow prototype for a direct car-rental operator (1Now-style).

What this is: the rules from the assignment document, written as code, so they
can be run, tested and shown working. Standard library only, Python 3.9+.

What this is NOT: a connection to 1Now. There is no 1Now API here. Every place
that would touch the outside world (send a message, capture a deposit) is a
small stub marked  # STUB  that you would replace with the real integration.

Key rules the code enforces:
  1. Sort first: Turo trips and safety cases leave the normal flow.
  2. Two clocks: the deposit hold and the next booking.
  3. Same evidence standard both ways: no charge on suspicion.
  4. The renter is told, with evidence, before any money moves.
  5. No money moves without the operator's approval.
  6. A claim closes only when the operator says they are whole.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from string import Template
from typing import Dict, List, Optional, Tuple


# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------
class Route(Enum):
    CONTINUE = "continue"
    TURO_HANDOFF = "hand back to Turo's process"
    SAFETY = "safety path (stop the standard flow)"


class Tier(Enum):
    T0 = "not damage (tolls, cleaning, fuel, late return)"
    T1 = "cosmetic, drivable, within the deposit"
    T2 = "needs a shop, or over the deposit"
    T3 = "undriveable, or the next booking is at risk"
    T4 = "injury, police, theft, total loss, safety defect"


class Evidence(Enum):
    CLEAR = "clear"                  # in return photos, not in pickup photos
    UNCLEAR = "unclear"              # photos cannot settle it
    NONE = "no evidence"             # photos missing
    PRE_EXISTING = "pre-existing"    # already visible in pickup photos


class Funding(Enum):
    DEPOSIT_HOLD = "deposit hold"
    DAMAGE_COVER = "damage cover bought at checkout"
    RENTER_INSURANCE = "renter's own insurance"
    OPERATOR_POLICY = "operator's own policy"
    DIRECT_RECOVERY = "direct recovery from the renter"


class GateError(Exception):
    """Raised when a rule forbids an action (for example, charging too early)."""


# --------------------------------------------------------------------------
# The claim record
# --------------------------------------------------------------------------
@dataclass
class Claim:
    booking_id: str
    car: str
    operator: str
    renter: str
    damage: str
    reported_at: datetime
    source: str = "direct"                 # "direct" or "turo"
    is_damage: bool = True                 # False for tolls, cleaning, fuel, late
    injury_or_police: bool = False
    drivable: bool = True
    needs_shop: bool = False
    hold_amount: float = 0.0
    hold_expires_at: Optional[datetime] = None   # ASSUMPTION: confirm real hold length
    hold_released: bool = False
    next_booking_start: Optional[datetime] = None
    pickup_photos: bool = True
    return_photos: bool = True
    damage_in_pickup_photos: Optional[bool] = False  # None = cannot tell
    damage_cover_bought: bool = False
    renter_policy_verified: bool = False
    estimate: Optional[float] = None
    renter_notified_at: Optional[datetime] = None
    renter_replied: bool = False
    amount_captured: float = 0.0
    approvals: set = field(default_factory=set)      # what the operator approved
    log: List[str] = field(default_factory=list)

    def note(self, now: datetime, text: str) -> None:
        self.log.append(f"{now:%a %d %b %H:%M}  {text}")


# --------------------------------------------------------------------------
# Step 0: sort, then triage
# --------------------------------------------------------------------------
def step0_sort(c: Claim) -> Route:
    """Whose booking is it, and is anyone hurt?"""
    if c.source != "direct":
        return Route.TURO_HANDOFF
    if c.injury_or_police:
        return Route.SAFETY
    return Route.CONTINUE


def next_booking_at_risk(c: Claim, now: datetime) -> bool:
    if c.next_booking_start is None:
        return False
    soon = (c.next_booking_start - now) <= timedelta(days=7)
    return soon and (not c.drivable or c.needs_shop)


def triage(c: Claim, now: datetime) -> Tier:
    if c.injury_or_police:
        return Tier.T4
    if not c.is_damage:
        return Tier.T0
    if not c.drivable or next_booking_at_risk(c, now):
        return Tier.T3
    if c.needs_shop or (c.estimate is not None and c.estimate > c.hold_amount):
        return Tier.T2
    return Tier.T1


# --------------------------------------------------------------------------
# Step 2: the two clocks
# --------------------------------------------------------------------------
def hold_status(c: Claim, now: datetime) -> str:
    if c.hold_released:
        return "released"
    if c.hold_expires_at is None:
        return "none"
    return "expired" if now >= c.hold_expires_at else "live"


def check_clocks(c: Claim, now: datetime) -> Dict[str, object]:
    status = hold_status(c, now)
    decision_by = None
    if status == "live":
        decision_by = c.hold_expires_at - timedelta(days=1)  # decide a day early
    booking_action = None
    if c.next_booking_start is not None:
        days = (c.next_booking_start - now).total_seconds() / 86400
        if 0 <= days <= 7:
            booking_action = "decide today: keep it, swap the car, or warn the next renter"
    return {"hold": status, "decision_by": decision_by, "next_booking": booking_action}


# --------------------------------------------------------------------------
# Step 3: evidence (same standard in both directions)
# --------------------------------------------------------------------------
def classify_evidence(c: Claim) -> Evidence:
    if not (c.pickup_photos and c.return_photos):
        return Evidence.NONE
    if c.damage_in_pickup_photos is None:
        return Evidence.UNCLEAR
    if c.damage_in_pickup_photos:
        return Evidence.PRE_EXISTING
    return Evidence.CLEAR


# --------------------------------------------------------------------------
# Step 4: renter contact cadence (24h and 48h, then decide on the evidence)
# --------------------------------------------------------------------------
def next_renter_action(c: Claim, now: datetime) -> str:
    if c.renter_notified_at is None:
        return "send Message B once the operator approves the wording"
    if c.renter_replied:
        return "review the renter's response; send Message F if it is a dispute"
    hours = (now - c.renter_notified_at).total_seconds() / 3600
    if hours < 24:
        return "wait; second contact is due at 24 hours"
    if hours < 48:
        return "send Message C on a different channel"
    return "deadline reached: proceed on the evidence and tell the renter"


# --------------------------------------------------------------------------
# Step 5: who pays (ordered, each with the thing to watch)
# --------------------------------------------------------------------------
def funding_options(c: Claim, now: datetime) -> List[Tuple[Funding, str]]:
    options: List[Tuple[Funding, str]] = []
    live = hold_status(c, now) == "live"
    within_hold = c.estimate is None or c.estimate <= c.hold_amount
    if live and within_hold and classify_evidence(c) is Evidence.CLEAR:
        options.append((Funding.DEPOSIT_HOLD, "capture before it lapses; renter notified first"))
    if c.damage_cover_bought:
        options.append((Funding.DAMAGE_COVER, "read exclusions and the filing window first"))
    if c.renter_policy_verified:
        options.append((Funding.RENTER_INSURANCE,
                        "verified means a policy exists, not that it pays this claim"))
    options.append((Funding.OPERATOR_POLICY, "deductible and premium impact are the operator's call"))
    if not live or not within_hold:
        options.append((Funding.DIRECT_RECOVERY,
                        "only as the signed agreement allows; senior check before any charge"))
    return options


# --------------------------------------------------------------------------
# Gates: the rules that stop a wrong charge
# --------------------------------------------------------------------------
def approve(c: Claim, action: str, now: datetime) -> None:
    c.approvals.add(action)
    c.note(now, f"operator approved: {action}")


def capture_deposit(c: Claim, amount: float, now: datetime) -> None:
    """STUB for the real payment call. Enforces every rule first."""
    if "capture" not in c.approvals:
        raise GateError("no money moves without the operator's approval")
    if c.renter_notified_at is None:
        raise GateError("the renter must be notified, with evidence, before any charge")
    if hold_status(c, now) != "live":
        raise GateError(f"deposit hold is {hold_status(c, now)}: use the post-hold path")
    if amount > c.hold_amount:
        raise GateError("amount is over the hold: needs another funding source")
    if classify_evidence(c) is not Evidence.CLEAR:
        raise GateError("no charge on suspicion: evidence is not clear")
    c.amount_captured += amount
    c.note(now, f"captured ${amount:,.2f} from the deposit hold")


def refund_excess(c: Claim, final_cost: float, now: datetime) -> float:
    """If more was taken than the final repair bill, the difference goes back."""
    excess = max(0.0, c.amount_captured - final_cost)
    if excess:
        c.amount_captured -= excess
        c.note(now, f"refunded ${excess:,.2f} to the renter (bill was lower)")
    return excess


# --------------------------------------------------------------------------
# Step 8: close with a ledger; only the operator can close
# --------------------------------------------------------------------------
def build_ledger(c: Claim, final_cost: float,
                 recovered: Dict[Funding, float]) -> Dict[str, object]:
    total = sum(recovered.values())
    return {"final_cost": final_cost, "recovered": recovered,
            "total_recovered": total, "gap": max(0.0, final_cost - total)}


def try_close(c: Claim, operator_says_whole: bool, now: datetime) -> str:
    if operator_says_whole:
        c.note(now, "CLOSED: operator confirmed they are whole")
        return "closed"
    c.note(now, "STAYS OPEN: operator is not whole; owner and next date required")
    return "open"


# --------------------------------------------------------------------------
# Messages A to G (templates). Names match the document.
# --------------------------------------------------------------------------
TEMPLATES: Dict[str, Template] = {
    "A": Template(
        "Hi $operator, I'm sorry. Finding damage after a trip is a bad start to the week, "
        "and I've got this. I've opened a claim for booking #$booking ($car). Next: "
        "(1) today I'm checking your deposit hold and your next booking; $hold_line "
        "(2) by $photo_by I'll compare pickup and return photos; (3) by $renter_by, with "
        "your OK, we contact $renter. Two things I need now: is the car safe to drive, and "
        "is anything booked in the next 7 days? I'll update you by $update_by even if "
        "there's no news."),
    "B": Template(
        "Hi $renter, thanks again for renting with $business. When $car came back we found "
        "damage: $damage. Photos from pickup and return are attached. We'd like to understand "
        "what happened. Please reply by $reply_by with your account, any photos, and any "
        "insurance you'd like involved. If you believe this was there at pickup, tell us "
        "where and we'll look again. Nothing will be charged before you've had the chance "
        "to respond. $operator"),
    "C": Template(
        "Hi $renter, following up on my earlier message. We'd rather sort this directly "
        "with you. Please reply by $reply_by; even a short answer helps. If we don't hear "
        "back, we'll continue based on the photos and the agreement, and you'll receive a "
        "copy of the decision."),
    "D": Template(
        "Quick update on booking #$booking: $status. Your hold ends $hold_end, so our "
        "decision date is $decision_by. Next step: $next_step. Nothing needed from you today "
        "unless you've heard from them."),
    "E": Template(
        "Your claim for booking #$booking is ready to close. Repair cost: $$${cost}. "
        "Recovered: $$${recovered}. Gap: $$${gap}. $gap_line Does this leave you whole? "
        "Reply YES, or tell me what's missing and I'll keep it open with a next step and a date."),
    "G": Template(
        "Hi $name, I'm sorry to tell you before your trip: $car won't be available on $dates. "
        "Here's what I can do: $offer. We'd like to keep your booking, but your plans come "
        "first, so tell me what works and I'll make it happen."),
}


def render(kind: str, **fields: object) -> str:
    return TEMPLATES[kind].substitute(**fields)


def send(to: str, text: str, c: Claim, now: datetime) -> None:
    """STUB: replace with the real SMS / email / in-app message call."""
    c.note(now, f"message sent to {to}")
    print(f"\n  >> to {to}:\n     {text}")
