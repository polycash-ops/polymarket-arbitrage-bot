import unittest
from datetime import datetime, timedelta, timezone
from canonical_resolver import select_canonical_open_contract

UTC = timezone.utc
START = datetime(2026, 10, 17, 21, 15, tzinfo=UTC)
END = START + timedelta(minutes=15)
NOW = START + timedelta(minutes=8)
SLUG = "cpc-btc-updown-15m-2026-10-17-2115z"


def row(**overrides):
    x = {
        "market_slug": SLUG, "market_id": "1517399", "timeframe": "15m",
        "title": "BTC Up or Down 15m", "active": True,
        "window_start": START, "window_end": END,
        "metadata": {"marketType": "ASSET_PRICE_MARKET_TYPE_UP_DOWN",
                     "assetPriceTerms": {"asset": {"symbol": "BTC"}, "horizon": "15m",
                                          "windowStart": START.isoformat(), "windowEnd": END.isoformat()},
                     "endDate": "2026-10-17T22:00:00Z"},
    }
    x.update(overrides)
    return x


class CanonicalResolverTests(unittest.TestCase):
    def test_fresh_prices_do_not_require_observations(self):
        self.assertEqual(select_canonical_open_contract([row()], NOW)["status"], "OPEN")

    def test_previous_contract_observation_is_not_a_resolver_input(self):
        previous = row(window_start=START-timedelta(minutes=15), window_end=START,
                       metadata={"marketType":"ASSET_PRICE_MARKET_TYPE_UP_DOWN",
                                 "assetPriceTerms":{"asset":{"symbol":"BTC"},"horizon":"15m",
                                                  "windowStart":(START-timedelta(minutes=15)).isoformat(),"windowEnd":START.isoformat()}})
        result = select_canonical_open_contract([previous], NOW)
        self.assertEqual(result["status"], "NO_OPEN_CONTRACT")

    def test_enddate_can_differ_from_window_end(self):
        result = select_canonical_open_contract([row()], NOW)
        self.assertEqual(result["status"], "OPEN")
        self.assertEqual(result["contract"]["end_at"], END.isoformat())

    def test_missing_and_naive_boundaries_rejected(self):
        for change in ({"window_start": None}, {"window_end": "2026-10-17T21:30:00"}):
            with self.subTest(change=change):
                self.assertEqual(select_canonical_open_contract([row(**change)], NOW)["status"], "NO_OPEN_CONTRACT")

    def test_invalid_duration_rejected(self):
        bad_end = START + timedelta(hours=1)
        bad_meta = {"marketType":"ASSET_PRICE_MARKET_TYPE_UP_DOWN",
                    "assetPriceTerms":{"asset":{"symbol":"BTC"},"horizon":"15m",
                                         "windowStart":START.isoformat(),"windowEnd":bad_end.isoformat()}}
        self.assertEqual(select_canonical_open_contract([row(window_end=bad_end, metadata=bad_meta)], NOW)["status"], "NO_OPEN_CONTRACT")

    def test_genuine_metadata_boundary_conflict_rejected(self):
        meta = row()["metadata"]
        meta["assetPriceTerms"]["windowEnd"] = (END + timedelta(minutes=15)).isoformat()
        self.assertEqual(select_canonical_open_contract([row(metadata=meta)], NOW)["status"], "NO_OPEN_CONTRACT")

    def test_duplicate_representation_of_same_identity_and_window_is_accepted(self):
        item = row()
        result = select_canonical_open_contract([item, dict(item)], NOW)
        self.assertEqual(result["status"], "OPEN")
        self.assertEqual(result["contract"]["identity"], SLUG)

    def test_conflicting_duplicate_identity_fails_closed(self):
        item = row()
        conflict = dict(item)
        conflict["window_end"] = END + timedelta(minutes=15)
        conflict["metadata"] = dict(item["metadata"])
        conflict["metadata"]["assetPriceTerms"] = dict(item["metadata"]["assetPriceTerms"])
        conflict["metadata"]["assetPriceTerms"]["windowEnd"] = conflict["window_end"].isoformat()
        result = select_canonical_open_contract([item, conflict], NOW)
        self.assertEqual(result["status"], "NO_OPEN_CONTRACT")
        self.assertEqual(result["reason"], "conflicting_records_for_same_identity")

    def test_duplicate_identity_with_conflicting_product_metadata_fails_closed(self):
        item = row()
        conflict = row(metadata={"marketType": "ASSET_PRICE_MARKET_TYPE_UP_DOWN",
                                 "assetPriceTerms": {"asset": {"symbol": "ETH"}, "horizon": "15m",
                                                      "windowStart": START.isoformat(), "windowEnd": END.isoformat()}})
        result = select_canonical_open_contract([item, conflict], NOW)
        self.assertEqual(result["reason"], "conflicting_records_for_same_identity")

    def test_conflicting_target_candidate_blocks_selection_of_an_overlapping_row(self):
        conflict = row(market_slug="conflicting", market_id="1517400")
        conflict["metadata"] = dict(conflict["metadata"])
        conflict["metadata"]["assetPriceTerms"] = dict(conflict["metadata"]["assetPriceTerms"])
        conflict["metadata"]["assetPriceTerms"]["windowEnd"] = (END + timedelta(minutes=15)).isoformat()
        result = select_canonical_open_contract([row(), conflict], NOW)
        self.assertEqual(result["status"], "NO_OPEN_CONTRACT")
        self.assertEqual(result["reason"], "invalid_or_conflicting_canonical_candidate")
        self.assertEqual(result["detail"], "conflicting_window_end")

    def test_multiple_eligible_canonical_identities_are_ambiguous(self):
        other = row(market_slug="another-btc-15m", market_id="1517400")
        result = select_canonical_open_contract([row(), other], NOW)
        self.assertEqual(result["reason"], "ambiguous_canonical_contracts")

    def test_product_identity_must_be_explicit(self):
        meta = row()["metadata"]
        meta["assetPriceTerms"]["asset"]["symbol"] = "ETH"
        self.assertEqual(select_canonical_open_contract([row(metadata=meta)], NOW)["status"], "NO_OPEN_CONTRACT")

    def test_rollover_uses_half_open_window(self):
        self.assertEqual(select_canonical_open_contract([row()], END)["status"], "NO_OPEN_CONTRACT")
        next_start, next_end = END, END + timedelta(minutes=15)
        nxt = row(market_slug="next", market_id="1517400", window_start=next_start, window_end=next_end,
                  metadata={"marketType":"ASSET_PRICE_MARKET_TYPE_UP_DOWN",
                            "assetPriceTerms":{"asset":{"symbol":"BTC"},"horizon":"15m",
                                                 "windowStart":next_start.isoformat(),"windowEnd":next_end.isoformat()}})
        self.assertEqual(select_canonical_open_contract([row(), nxt], END)["contract"]["identity"], "next")

    def test_accuracy_is_not_part_of_resolver_and_remains_unavailable(self):
        # Resolver only supplies contract identity; scoring policy is still unapproved.
        result = select_canonical_open_contract([row()], NOW)
        self.assertNotIn("accuracy", result)


if __name__ == "__main__":
    unittest.main()
