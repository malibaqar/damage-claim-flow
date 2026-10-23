"""Run:  python -m unittest -v"""
import unittest
from datetime import datetime, timedelta

import claim_flow as cf

NOW = datetime(2026, 10, 19, 8, 40)


def make(**kw) -> cf.Claim:
    base = dict(booking_id="1", car="Tesla", operator="Ali", renter="Sara",
                damage="scrape", reported_at=NOW, hold_amount=500.0,
                hold_expires_at=NOW + timedelta(days=5))
    base.update(kw)
    return cf.Claim(**base)


class SortAndTriage(unittest.TestCase):
    def test_turo_trip_is_handed_back(self):
        self.assertIs(cf.step0_sort(make(source="turo")), cf.Route.TURO_HANDOFF)

    def test_injury_stops_the_standard_flow(self):
        c = make(injury_or_police=True)
        self.assertIs(cf.step0_sort(c), cf.Route.SAFETY)
        self.assertIs(cf.triage(c, NOW), cf.Tier.T4)

    def test_non_damage_is_tier_zero(self):
        self.assertIs(cf.triage(make(is_damage=False), NOW), cf.Tier.T0)

    def test_undriveable_is_tier_three(self):
        self.assertIs(cf.triage(make(drivable=False), NOW), cf.Tier.T3)

    def test_over_deposit_is_tier_two(self):
        self.assertIs(cf.triage(make(estimate=900.0), NOW), cf.Tier.T2)

    def test_small_drivable_is_tier_one(self):
        self.assertIs(cf.triage(make(estimate=100.0), NOW), cf.Tier.T1)


class Clocks(unittest.TestCase):
    def test_decide_one_day_before_hold_lapses(self):
        c = make()
        self.assertEqual(cf.check_clocks(c, NOW)["decision_by"],
                         c.hold_expires_at - timedelta(days=1))

    def test_released_hold_has_no_decision_date_and_uses_post_hold_path(self):
        c = make(hold_released=True)
        self.assertEqual(cf.check_clocks(c, NOW)["hold"], "released")
        sources = [s for s, _ in cf.funding_options(c, NOW)]
        self.assertNotIn(cf.Funding.DEPOSIT_HOLD, sources)
        self.assertIn(cf.Funding.DIRECT_RECOVERY, sources)

    def test_next_booking_inside_a_week_forces_a_same_day_decision(self):
        c = make(next_booking_start=NOW + timedelta(days=2))
        self.assertIn("decide today", cf.check_clocks(c, NOW)["next_booking"])


class Evidence(unittest.TestCase):
    def test_classes(self):
        self.assertIs(cf.classify_evidence(make()), cf.Evidence.CLEAR)
        self.assertIs(cf.classify_evidence(make(pickup_photos=False)), cf.Evidence.NONE)
        self.assertIs(cf.classify_evidence(make(damage_in_pickup_photos=None)),
                      cf.Evidence.UNCLEAR)
        self.assertIs(cf.classify_evidence(make(damage_in_pickup_photos=True)),
                      cf.Evidence.PRE_EXISTING)


class Gates(unittest.TestCase):
    def ready(self) -> cf.Claim:
        c = make(estimate=400.0)
        c.renter_notified_at = NOW
        c.approvals.add("capture")
        return c

    def test_happy_path_captures(self):
        c = self.ready()
        cf.capture_deposit(c, 400.0, NOW)
        self.assertEqual(c.amount_captured, 400.0)

    def test_blocked_without_operator_approval(self):
        c = self.ready()
        c.approvals.clear()
        with self.assertRaises(cf.GateError):
            cf.capture_deposit(c, 400.0, NOW)

    def test_blocked_before_renter_is_notified(self):
        c = self.ready()
        c.renter_notified_at = None
        with self.assertRaises(cf.GateError):
            cf.capture_deposit(c, 400.0, NOW)

    def test_blocked_when_hold_already_released(self):
        c = self.ready()
        c.hold_released = True
        with self.assertRaises(cf.GateError):
            cf.capture_deposit(c, 400.0, NOW)

    def test_blocked_when_evidence_is_not_clear(self):
        c = self.ready()
        c.damage_in_pickup_photos = None
        with self.assertRaises(cf.GateError):
            cf.capture_deposit(c, 400.0, NOW)

    def test_blocked_when_amount_exceeds_hold(self):
        c = self.ready()
        with self.assertRaises(cf.GateError):
            cf.capture_deposit(c, 600.0, NOW)

    def test_excess_is_refunded_when_bill_is_lower(self):
        c = self.ready()
        cf.capture_deposit(c, 400.0, NOW)
        self.assertEqual(cf.refund_excess(c, 350.0, NOW), 50.0)
        self.assertEqual(c.amount_captured, 350.0)


class Cadence(unittest.TestCase):
    def test_notice_then_second_contact_then_decide_on_evidence(self):
        c = make()
        self.assertIn("Message B", cf.next_renter_action(c, NOW))
        c.renter_notified_at = NOW
        self.assertIn("wait", cf.next_renter_action(c, NOW + timedelta(hours=5)))
        self.assertIn("Message C", cf.next_renter_action(c, NOW + timedelta(hours=26)))
        self.assertIn("proceed on the evidence",
                      cf.next_renter_action(c, NOW + timedelta(hours=49)))


class Closing(unittest.TestCase):
    def test_only_the_operator_can_close(self):
        c = make()
        self.assertEqual(cf.try_close(c, False, NOW), "open")
        self.assertEqual(cf.try_close(c, True, NOW), "closed")

    def test_ledger_reports_the_gap(self):
        ledger = cf.build_ledger(make(), 900.0, {cf.Funding.DEPOSIT_HOLD: 500.0})
        self.assertEqual(ledger["gap"], 400.0)


if __name__ == "__main__":
    unittest.main()
