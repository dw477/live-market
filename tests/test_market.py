import tempfile
import unittest
from pathlib import Path

from market import MINUTE, MarketStore


class ObservationTests(unittest.TestCase):
    def test_quote_duplicates_revisions_and_late_arrivals_survive_reopen(self):
        start = MINUTE * 10
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "market.sqlite3"
            store = MarketStore(path)
            first = store.quote(start + 10, start + 100, 100)
            newer = store.quote(start + 40, start + 200, 110)
            late = store.quote(start + 20, start + 300, 120)
            self.assertIsNone(store.quote(start + 40, start + 400, 110))
            correction = store.quote(start + 40, start + 500, 111)
            complete, = store.complete_due(start + MINUTE)
            self.assertEqual((late["high"], late["close"]), (120, 110))
            self.assertEqual(correction["close"], 111)
            self.assertEqual(complete["complete"], 1)
            store.db.close()

            store = MarketStore(path)
            try:
                replay = store.replay()
                self.assertEqual([row["id"] for row in replay],
                                 [first["id"], newer["id"], late["id"], correction["id"], complete["id"]])
                self.assertEqual([row["revision"] for row in replay], [1, 2, 3, 4, 5])
                self.assertEqual(replay[0]["complete"], 0)
                self.assertEqual(store.snapshot(), [complete])
            finally:
                store.db.close()

    def test_history_reconciles_completed_bar_and_deduplicates(self):
        store = MarketStore(":memory:")
        self.addCleanup(store.db.close)
        start = MINUTE * 10
        bar = dict(open=98, high=125, low=97, close=115, volume=42)
        store.quote(start + 40, start + 200, 110)
        partial = store.history(start, start + 500, bar, start + 300)
        self.assertEqual((partial["close"], partial["volume"]), (110, 42))
        self.assertIsNone(store.history(start, start + 550, bar, start + 510))
        final = store.history(start, start + MINUTE + 20, bar, start + MINUTE + 10)
        self.assertEqual((final["close"], final["complete"]), (115, 1))
        self.assertIsNone(store.quote(start + 30, start + MINUTE + 40, 130))
        self.assertIsNone(store.history(start, start + MINUTE + 50, bar, start + MINUTE + 40))
        revised = store.history(start, start + MINUTE + 60, dict(bar, volume=43), start + MINUTE + 50)
        self.assertEqual(revised["volume"], 43)
        self.assertEqual(len(store.replay()), 4)


if __name__ == "__main__":
    unittest.main()
