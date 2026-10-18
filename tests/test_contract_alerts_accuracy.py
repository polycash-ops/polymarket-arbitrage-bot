"""Focused tests for contract selection, UP/DOWN alerts, graph annotations, and disabled accuracy."""
from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

# Pure helpers — no Flask required
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reservoir_consumer as rc


class ContractSelectionTests(unittest.TestCase):
    def test_start_inclusive_end_exclusive(self):
        t0 = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        c = {
            "identity": "btc-updown-15m-1",
            "start_at": t0,
            "end_at": t0 + timedelta(minutes=15),
        }
        at_start = rc.select_open_contract([c], t0)
        self.assertEqual(at_start["status"], "OPEN")
        at_end = rc.select_open_contract([c], t0 + timedelta(minutes=15))
        self.assertEqual(at_end["status"], "NO_OPEN_CONTRACT")
        just_before = rc.select_open_contract([c], t0 + timedelta(minutes=15, seconds=-1))
        self.assertEqual(just_before["status"], "OPEN")

    def test_15_minute_product_validation(self):
        t0 = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
        hour = {
            "identity": "btc-1h",
            "start_at": t0,
            "end_at": t0 + timedelta(hours=1),
            "timeframe": "1h",
        }
        r = rc.select_open_contract([hour], t0 + timedelta(minutes=5))
        self.assertIn(r["status"], ("REJECTED_PRODUCT", "NO_OPEN_CONTRACT"))

    def test_ambiguous_contracts(self):
        t0 = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
        a = {"identity": "a", "start_at": t0, "end_at": t0 + timedelta(minutes=15)}
        b = {"identity": "b", "start_at": t0, "end_at": t0 + timedelta(minutes=15)}
        r = rc.select_open_contract([a, b], t0 + timedelta(minutes=1))
        self.assertEqual(r["status"], "AMBIGUOUS")
        self.assertIsNone(r["contract"])

    def test_missing_and_malformed_timestamps(self):
        t0 = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
        bad = [
            {"identity": "x", "start_at": None, "end_at": t0 + timedelta(minutes=15)},
            {"identity": "y", "start_at": "not-a-date", "end_at": t0 + timedelta(minutes=15)},
            {"start_at": t0, "end_at": t0 + timedelta(minutes=15)},
        ]
        r = rc.select_open_contract(bad, t0)
        self.assertEqual(r["status"], "NO_OPEN_CONTRACT")

    def test_naive_contract_boundary_is_rejected(self):
        t0 = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        c = {
            "identity": "z",
            "start_at": "2026-10-17T15:00:00",
            "end_at": "2026-10-17T15:15:00Z",
        }
        r = rc.select_open_contract([c], t0 + timedelta(minutes=2))
        self.assertEqual(r["status"], "NO_OPEN_CONTRACT")

    def test_rollover_clears_prior(self):
        t0 = datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc)
        first = {"identity": "c1", "start_at": t0, "end_at": t0 + timedelta(minutes=15)}
        second = {
            "identity": "c2",
            "start_at": t0 + timedelta(minutes=15),
            "end_at": t0 + timedelta(minutes=30),
        }
        during_first = rc.select_open_contract([first, second], t0 + timedelta(minutes=10))
        self.assertEqual(during_first["contract"]["identity"], "c1")
        during_second = rc.select_open_contract([first, second], t0 + timedelta(minutes=20))
        self.assertEqual(during_second["contract"]["identity"], "c2")


class ActiveAlertTests(unittest.TestCase):
    def test_no_contract_means_no_alert(self):
        r = rc.select_active_up_down_alert(
            [{"market_slug": "x", "forecast_direction": "UP", "captured_at": datetime.now(timezone.utc)}],
            None,
            datetime.now(timezone.utc),
        )
        self.assertEqual(r["status"], "NO_ACTIVE_ALERT")
        self.assertEqual(r["message"], "No active UP/DOWN alert.")

    def test_does_not_carry_prior_contract_alert(self):
        t0 = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        records = [
            {"market_slug": "old", "forecast_direction": "UP", "issued_at": t0 + timedelta(minutes=1)},
            {"market_slug": "new", "forecast_direction": "DOWN", "issued_at": t0 + timedelta(minutes=16)},
        ]
        r = rc.select_active_up_down_alert(
            records, "new", t0 + timedelta(minutes=20),
            contract_start=t0 + timedelta(minutes=15),
            contract_end=t0 + timedelta(minutes=30),
            trust_issuance=True,
        )
        self.assertEqual(r["status"], "ACTIVE")
        self.assertEqual(r["alert"]["direction"], "DOWN")
        self.assertEqual(r["alert"]["contract_identity"], "new")

    def test_missing_issuance_excluded(self):
        t0 = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        records = [{"market_slug": "c", "forecast_direction": "UP"}]
        r = rc.select_active_up_down_alert(
            records, "c", t0 + timedelta(minutes=5),
            contract_start=t0, contract_end=t0 + timedelta(minutes=15),
        )
        self.assertEqual(r["status"], "NO_ACTIVE_ALERT")
        self.assertTrue(any(u.get("state") == "alert_issuance_unverified" for u in r.get("unverified_observations", [])))

    def test_late_alert_after_close_excluded(self):
        t0 = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        records = [{
            "market_slug": "c",
            "forecast_direction": "UP",
            "issued_at": t0 + timedelta(minutes=15),
        }]
        r = rc.select_active_up_down_alert(
            records, "c", t0 + timedelta(minutes=20),
            contract_start=t0, contract_end=t0 + timedelta(minutes=15),
        )
        self.assertEqual(r["status"], "NO_ACTIVE_ALERT")

    def test_captured_at_alone_never_active_alert(self):
        """Regression: captured_at without issued_at cannot become an active alert."""
        t0 = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        records = [{
            "market_slug": "c",
            "forecast_direction": "UP",
            "captured_at": t0 + timedelta(minutes=2),
        }]
        r = rc.select_active_up_down_alert(
            records, "c", t0 + timedelta(minutes=5),
            contract_start=t0, contract_end=t0 + timedelta(minutes=15),
        )
        self.assertEqual(r["status"], "NO_ACTIVE_ALERT")
        self.assertIsNone(r["alert"])
        self.assertEqual(r["unverified_observations"][0]["state"], "alert_issuance_unverified")

    def test_captured_at_alone_no_graph_annotation(self):
        t0 = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        records = [{
            "market_slug": "c",
            "forecast_direction": "DOWN",
            "captured_at": t0 + timedelta(minutes=3),
        }]
        r = rc.select_active_up_down_alert(
            records, "c", t0 + timedelta(minutes=5),
            contract_start=t0, contract_end=t0 + timedelta(minutes=15),
        )
        ann = rc.alerts_to_graph_annotations([r["alert"]] if r.get("alert") else [])
        self.assertEqual(ann, [])

    def test_issued_at_required_for_active(self):
        t0 = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        records = [{
            "market_slug": "c",
            "forecast_direction": "UP",
            "captured_at": t0 + timedelta(minutes=10),
            "issued_at": t0 + timedelta(minutes=2),
        }]
        with patch.dict(os.environ, {"ALERT_SEQUENCE_ORDERING_TRUSTED": "true"}):
            r = rc.select_active_up_down_alert(
                records, "c", t0 + timedelta(minutes=5),
                contract_start=t0, contract_end=t0 + timedelta(minutes=15),
                trust_issuance=True,
            )
        self.assertEqual(r["status"], "ACTIVE")
        self.assertEqual(r["alert"]["issuance_timestamp_source"], "issued_at")

    def test_equal_issuance_conflicting_direction_ambiguous_without_sequence(self):
        t0 = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        issued = t0 + timedelta(minutes=3)
        records = [
            {"market_slug": "c", "forecast_direction": "UP", "issued_at": issued, "snapshot_id": 1},
            {"market_slug": "c", "forecast_direction": "DOWN", "issued_at": issued, "snapshot_id": 2},
        ]
        r = rc.select_active_up_down_alert(
            records, "c", t0 + timedelta(minutes=5),
            contract_start=t0, contract_end=t0 + timedelta(minutes=15),
            trust_issuance=True,
        )
        self.assertEqual(r["status"], "AMBIGUOUS_ALERT")
        self.assertIsNone(r["alert"])
        self.assertEqual(r["reason"], "equal_issuance_without_authoritative_order")

    def test_equal_issuance_resolved_by_alert_sequence(self):
        t0 = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        issued = t0 + timedelta(minutes=3)
        records = [
            {"market_slug": "c", "forecast_direction": "UP", "issued_at": issued, "alert_sequence": 1},
            {"market_slug": "c", "forecast_direction": "DOWN", "issued_at": issued, "alert_sequence": 2},
        ]
        with patch.dict(os.environ, {"ALERT_SEQUENCE_ORDERING_TRUSTED": "true"}):
            r = rc.select_active_up_down_alert(
                records, "c", t0 + timedelta(minutes=5),
                contract_start=t0, contract_end=t0 + timedelta(minutes=15),
                trust_issuance=True,
            )
        self.assertEqual(r["status"], "ACTIVE")
        self.assertEqual(r["alert"]["direction"], "DOWN")

    def test_up_down_only_filter(self):
        t0 = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        records = [
            {"market_slug": "c", "forecast_direction": "HOLD", "issued_at": t0 + timedelta(minutes=1)},
            {"market_slug": "c", "forecast_direction": "NEUTRAL", "issued_at": t0 + timedelta(minutes=2)},
        ]
        r = rc.select_active_up_down_alert(
            records, "c", t0 + timedelta(minutes=5),
            contract_start=t0, contract_end=t0 + timedelta(minutes=15),
        )
        self.assertEqual(r["status"], "NO_ACTIVE_ALERT")

    def test_graph_annotations_use_issuance(self):
        alerts = [{
            "contract_identity": "c",
            "direction": "UP",
            "issued_at": "2026-10-17T15:03:00+00:00",
        }]
        ann = rc.alerts_to_graph_annotations(alerts)
        self.assertEqual(len(ann), 1)
        self.assertEqual(ann[0]["x"], "2026-10-17T15:03:00+00:00")
        self.assertEqual(ann[0]["direction"], "UP")


class RollingAccuracyTests(unittest.TestCase):
    def test_suppressed_while_unapproved(self):
        t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
        records = [{
            "market_slug": "c1",
            "forecast_direction": "UP",
            "issued_at": t - timedelta(hours=1),
            "outcome": "UP",
            "outcome_verified": True,
            "contract_end": t - timedelta(minutes=30),
            "contract_start": t - timedelta(minutes=45),
        }]
        r = rc.compute_rolling_accuracy(records, t, policy_approved=False, trust_issuance=True)
        self.assertEqual(r["status"], "UNAVAILABLE_POLICY_PENDING")
        self.assertIsNone(r["accuracy_pct"])
        self.assertEqual(r["policy"]["status"], "UNAPPROVED")

    def test_zero_scored_outcomes_message(self):
        t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
        r = rc.compute_rolling_accuracy([], t, policy_approved=True, trust_issuance=True)
        self.assertEqual(r["status"], "UNAVAILABLE_OUTCOME_PROVENANCE_PENDING")
        self.assertIsNone(r["accuracy_pct"])

    def test_denominator_correct_and_lookback(self):
        t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
        c1 = {
            "market_slug": "in-correct",
            "forecast_direction": "UP",
            "issued_at": t - timedelta(hours=2),
            "outcome": "UP",
            "outcome_verified": "true",
            "settled_at": t - timedelta(hours=1),
            "contract_start": t - timedelta(hours=2, minutes=10),
            "contract_end": t - timedelta(hours=1, minutes=55),
        }
        c2 = {
            "market_slug": "in-wrong",
            "forecast_direction": "DOWN",
            "issued_at": t - timedelta(hours=3),
            "outcome": "UP",
            "outcome_verified": True,
            "settled_at": t - timedelta(hours=2),
            "contract_start": t - timedelta(hours=3, minutes=10),
            "contract_end": t - timedelta(hours=2, minutes=55),
        }
        c3 = {
            "market_slug": "old",
            "forecast_direction": "UP",
            "issued_at": t - timedelta(hours=30),
            "outcome": "UP",
            "outcome_verified": True,
            "contract_start": t - timedelta(hours=30),
            "contract_end": t - timedelta(hours=29, minutes=45),
        }
        c4 = {
            "market_slug": "pending",
            "forecast_direction": "UP",
            "issued_at": t - timedelta(minutes=20),
            "contract_start": t - timedelta(minutes=25),
            "contract_end": t - timedelta(minutes=10),
        }
        r = rc.compute_rolling_accuracy([c1, c2, c3, c4], t, policy_approved=True, trust_issuance=True)
        self.assertEqual(r["status"], "UNAVAILABLE_OUTCOME_PROVENANCE_PENDING")
        self.assertIsNone(r["accuracy_pct"])

    def test_first_eligible_before_close_not_later(self):
        t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
        start = t - timedelta(hours=1)
        end = start + timedelta(minutes=15)
        early = {
            "market_slug": "c",
            "forecast_direction": "UP",
            "issued_at": start + timedelta(minutes=1),
            "snapshot_id": 1,
            "outcome": "UP",
            "outcome_verified": True,
            "contract_start": start,
            "contract_end": end,
            "settled_at": end + timedelta(minutes=1),
        }
        late = {
            "market_slug": "c",
            "forecast_direction": "DOWN",
            "issued_at": start + timedelta(minutes=10),
            "snapshot_id": 2,
            "outcome": "UP",
            "outcome_verified": True,
            "contract_start": start,
            "contract_end": end,
            "settled_at": end + timedelta(minutes=1),
        }
        r = rc.compute_rolling_accuracy([early, late], t, policy_approved=True, trust_issuance=True)
        self.assertEqual(r["status"], "UNAVAILABLE_OUTCOME_PROVENANCE_PENDING")
        self.assertIsNone(r["accuracy_pct"])

    def test_hold_excluded_from_scoring(self):
        t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
        start = t - timedelta(hours=1)
        end = start + timedelta(minutes=15)
        r = rc.compute_rolling_accuracy([{
            "market_slug": "c",
            "forecast_direction": "HOLD",
            "issued_at": start + timedelta(minutes=1),
            "outcome": "UP",
            "outcome_verified": True,
            "contract_start": start,
            "contract_end": end,
        }], t, policy_approved=True, trust_issuance=True)
        self.assertIsNone(r["scored_total"])


class ParseTimestampTests(unittest.TestCase):
    def test_parse_aware(self):
        self.assertIsNone(rc.parse_aware_timestamp(None))
        self.assertIsNone(rc.parse_aware_timestamp("bogus"))
        dt = rc.parse_aware_timestamp("2026-10-17T12:00:00Z")
        self.assertEqual(dt.tzinfo, timezone.utc)
        naive = rc.parse_aware_timestamp(datetime(2026, 1, 1, 0, 0))
        self.assertIsNone(naive)
        aware = rc.parse_aware_timestamp(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(aware.tzinfo, timezone.utc)


def _load_dashboard_with_flask_stub():
    """Load dashboard.py when real Flask is unavailable by installing a minimal stub."""
    try:
        import flask  # noqa: F401
        has_flask = True
    except ImportError:
        has_flask = False
        flask_mod = types.ModuleType("flask")

        class FakeResponse:
            def __init__(self, data, status=200):
                self._data = data
                self.status_code = status

            def get_json(self):
                return self._data

        def jsonify(obj):
            return FakeResponse(obj)

        class FakeClient:
            def get(self, path, **kwargs):
                # Dispatch by path to real view functions after import
                from flask import request  # will be our stub
                return FakeResponse({"error": "not wired"})

        class FakeApp:
            def __init__(self, name):
                self.name = name
                self._routes = {}

            def get(self, rule):
                def deco(fn):
                    self._routes[rule] = fn
                    return fn
                return deco

            def route(self, rule, **kwargs):
                return self.get(rule)

            def test_client(self):
                app = self

                class Client:
                    def get(self, path, **kwargs):
                        # Minimal request-query support for testing pure validation paths.
                        from urllib.parse import parse_qs, urlsplit
                        parsed = urlsplit(path)
                        FakeRequest.args = {key: values[0] for key, values in parse_qs(parsed.query).items()}
                        rule = parsed.path
                        fn = app._routes.get(rule)
                        if not fn:
                            return FakeResponse({"error": "missing"}, 404)
                        result = fn()
                        if isinstance(result, FakeResponse):
                            return result
                        if isinstance(result, tuple):
                            body, status = result[0], result[1]
                            if isinstance(body, FakeResponse):
                                body.status_code = status
                                return body
                            return FakeResponse(body, status)
                        return result
                return Client()

        class FakeRequest:
            headers = {}
            args = {}

        flask_mod.Flask = FakeApp
        flask_mod.jsonify = jsonify
        flask_mod.request = FakeRequest
        sys.modules["flask"] = flask_mod

    main_stub = types.ModuleType("main")
    main_stub.TradingBot = object
    sys.modules["main"] = main_stub
    if "dashboard" in sys.modules:
        del sys.modules["dashboard"]
    import dashboard
    return importlib.reload(dashboard), has_flask



    def test_outcome_without_verified_flag_not_scored(self):
        t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
        start = t - timedelta(hours=1)
        end = start + timedelta(minutes=15)
        r = rc.compute_rolling_accuracy([{
            "market_slug": "c",
            "forecast_direction": "UP",
            "issued_at": start + timedelta(minutes=1),
            "outcome": "UP",
            # outcome_verified missing
            "contract_start": start,
            "contract_end": end,
        }], t, policy_approved=True, trust_issuance=True)
        self.assertIsNone(r["scored_total"])
        self.assertGreaterEqual(r["pending"] + r["excluded"], 1)

    def test_captured_at_only_not_scored(self):
        t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
        start = t - timedelta(hours=1)
        end = start + timedelta(minutes=15)
        r = rc.compute_rolling_accuracy([{
            "market_slug": "c",
            "forecast_direction": "UP",
            "captured_at": start + timedelta(minutes=1),
            # no issued_at
            "outcome": "UP",
            "outcome_verified": True,
            "contract_start": start,
            "contract_end": end,
            "settled_at": end + timedelta(minutes=1),
        }], t, policy_approved=True, trust_issuance=True)
        self.assertIsNone(r["scored_total"])
        self.assertIn("no_eligible_issued_alert_before_close", r["exclusion_reasons"])

    def test_ambiguous_equal_issuance_unscorable(self):
        t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
        start = t - timedelta(hours=1)
        end = start + timedelta(minutes=15)
        issued = start + timedelta(minutes=2)
        r = rc.compute_rolling_accuracy([
            {
                "market_slug": "c",
                "forecast_direction": "UP",
                "issued_at": issued,
                "outcome": "UP",
                "outcome_verified": True,
                "contract_start": start,
                "contract_end": end,
                "settled_at": end + timedelta(minutes=1),
            },
            {
                "market_slug": "c",
                "forecast_direction": "DOWN",
                "issued_at": issued,
                "outcome": "UP",
                "outcome_verified": True,
                "contract_start": start,
                "contract_end": end,
                "settled_at": end + timedelta(minutes=1),
            },
        ], t, policy_approved=True, trust_issuance=True)
        self.assertIsNone(r["scored_total"])
        self.assertIn("ambiguous_equal_issuance", r["exclusion_reasons"])


class RolloverRequestGenerationTests(unittest.TestCase):
    def test_stale_response_ignored_by_generation(self):
        """Simulate UI generation guard: older generation must not apply."""
        state = {"generation": 0, "contract": None, "alert": None}

        def apply(generation, contract, alert):
            if generation != state["generation"]:
                return False  # stale
            state["contract"] = contract
            state["alert"] = alert
            return True

        state["generation"] += 1
        g1 = state["generation"]
        apply(g1, "c1", "UP")
        self.assertEqual(state["contract"], "c1")
        # rollover
        state["generation"] += 1
        g2 = state["generation"]
        # late g1 response
        self.assertFalse(apply(g1, "c1", "DOWN"))
        self.assertEqual(state["contract"], "c1")  # unchanged by stale? actually still c1 from before
        # wait - after rollover we should clear then apply g2
        state["contract"] = None
        state["alert"] = None
        self.assertFalse(apply(g1, "old", "UP"))
        self.assertIsNone(state["contract"])
        self.assertTrue(apply(g2, "c2", "DOWN"))
        self.assertEqual(state["contract"], "c2")
        self.assertEqual(state["alert"], "DOWN")



    def test_first_alert_uses_earliest_sequence_not_latest(self):
        """Scoring selects FIRST (earliest sequence), not latest."""
        t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
        start = t - timedelta(hours=1)
        end = start + timedelta(minutes=15)
        issued = start + timedelta(minutes=2)
        rows = [
            {
                "market_slug": "c",
                "forecast_direction": "UP",
                "issued_at": issued,
                "alert_sequence": 1,
                "outcome": "UP",
                "outcome_verified": True,
                "contract_start": start,
                "contract_end": end,
                "settled_at": end + timedelta(minutes=1),
            },
            {
                "market_slug": "c",
                "forecast_direction": "DOWN",
                "issued_at": issued,
                "alert_sequence": 9,
                "outcome": "UP",
                "outcome_verified": True,
                "contract_start": start,
                "contract_end": end,
                "settled_at": end + timedelta(minutes=1),
            },
        ]
        scored = rc.compute_rolling_accuracy(rows, t, policy_approved=True, trust_issuance=True)
        self.assertEqual(scored["status"], "UNAVAILABLE_OUTCOME_PROVENANCE_PENDING")
        self.assertIsNone(scored["accuracy_pct"])
        # Active alert prefers latest sequence
        with patch.dict(os.environ, {"ALERT_SEQUENCE_ORDERING_TRUSTED": "true"}):
            active = rc.select_active_up_down_alert(
                rows, "c", end - timedelta(seconds=1),
                contract_start=start, contract_end=end, trust_issuance=True,
            )
        self.assertEqual(active["status"], "ACTIVE")
        self.assertEqual(active["alert"]["direction"], "DOWN")

    def test_untrusted_issuance_blocks_active_and_scoring(self):
        t0 = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
        records = [{
            "market_slug": "c",
            "forecast_direction": "UP",
            "issued_at": t0 + timedelta(minutes=2),
        }]
        r = rc.select_active_up_down_alert(
            records, "c", t0 + timedelta(minutes=5),
            contract_start=t0, contract_end=t0 + timedelta(minutes=15),
            trust_issuance=False,
        )
        self.assertEqual(r["status"], "NO_ACTIVE_ALERT")
        self.assertEqual(r["unverified_observations"][0]["reason"], "issuance_semantics_not_trusted")
        start = t0
        end = t0 + timedelta(minutes=15)
        acc = rc.compute_rolling_accuracy([{
            "market_slug": "c",
            "forecast_direction": "UP",
            "issued_at": t0 + timedelta(minutes=2),
            "outcome": "UP",
            "outcome_verified": True,
            "contract_start": start,
            "contract_end": end,
            "settled_at": end + timedelta(minutes=1),
        }], end + timedelta(hours=1), policy_approved=True, trust_issuance=False)
        self.assertEqual(acc["status"], "UNAVAILABLE")
        self.assertIn("not trusted", acc["message"].lower())

    def test_false_string_verification_rejected(self):
        self.assertFalse(rc.is_explicitly_verified("false"))
        self.assertFalse(rc.is_explicitly_verified("False"))
        self.assertFalse(rc.is_explicitly_verified("0"))
        self.assertFalse(rc.is_explicitly_verified(""))
        self.assertFalse(rc.is_explicitly_verified(None))
        self.assertFalse(rc.is_explicitly_verified(False))
        self.assertTrue(rc.is_explicitly_verified(True))
        self.assertTrue(rc.is_explicitly_verified("true"))
        self.assertFalse(rc.is_explicitly_verified("YES"))
        self.assertFalse(rc.is_explicitly_verified("1"))
        self.assertFalse(rc.is_explicitly_verified(1))
        t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
        start = t - timedelta(hours=1)
        end = start + timedelta(minutes=15)
        r = rc.compute_rolling_accuracy([{
            "market_slug": "c",
            "forecast_direction": "UP",
            "issued_at": start + timedelta(minutes=1),
            "outcome": "UP",
            "outcome_verified": "false",
            "contract_start": start,
            "contract_end": end,
        }], t, policy_approved=True, trust_issuance=True)
        self.assertIsNone(r["scored_total"])

    def test_missing_boundaries_excluded_from_scoring(self):
        t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
        r = rc.compute_rolling_accuracy([{
            "market_slug": "c",
            "forecast_direction": "UP",
            "issued_at": t - timedelta(hours=1),
            "outcome": "UP",
            "outcome_verified": True,
            # no start/end
        }], t, policy_approved=True, trust_issuance=True)
        self.assertIsNone(r["scored_total"])
        self.assertEqual(r["status"], "UNAVAILABLE_OUTCOME_PROVENANCE_PENDING")




class ApiDisabledAccuracyEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d, cls.has_real_flask = _load_dashboard_with_flask_stub()

    def test_rolling_accuracy_endpoint_policy_pending_without_env(self):
        os.environ.pop("RESERVOIR_SCORING_POLICY_APPROVED", None)
        client = self.d.app.test_client()
        resp = client.get("/api/rolling-accuracy")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "UNAVAILABLE_POLICY_PENDING")
        self.assertIsNone(body["accuracy_pct"])
        self.assertFalse(body.get("policy_approved_env"))
        self.assertEqual(body["policy"]["status"], "UNAPPROVED")

    def test_active_alert_without_db_is_honest_empty(self):
        os.environ.pop("CONNECTOME_DATABASE_URL", None)
        client = self.d.app.test_client()
        resp = client.get("/api/active-alert")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "NO_ACTIVE_ALERT")
        self.assertEqual(body["message"], "No active UP/DOWN alert.")
        self.assertEqual(body["graph_annotations"], [])


if __name__ == "__main__":
    unittest.main()
