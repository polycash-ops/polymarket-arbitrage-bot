import unittest

from bot.signal_oracle_postgres import OraclePostgresStore


class OraclePostgresIdentityTests(unittest.TestCase):
    def test_prediction_id_is_one_per_window_even_across_versions(self):
        start = "2026-10-18T12:00:00+00:00"
        first = OraclePostgresStore._prediction_id(start, "oracle-v1")
        changed_version = OraclePostgresStore._prediction_id(start, "oracle-v2")
        self.assertEqual(first, changed_version)
        self.assertNotEqual(first, OraclePostgresStore._prediction_id("2026-10-18T12:15:00+00:00", "oracle-v1"))

    def test_window_id_is_stable_for_restart_recovery(self):
        start = "2026-10-18T12:00:00+00:00"
        self.assertEqual(OraclePostgresStore._window_id(start), OraclePostgresStore._window_id(start))
        self.assertNotEqual(OraclePostgresStore._window_id(start),
                            OraclePostgresStore._window_id("2026-10-18T12:15:00+00:00"))


if __name__ == "__main__":
    unittest.main()
