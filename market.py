import sqlite3
from pathlib import Path

SYMBOL = "BTC-USD"
MINUTE = 60_000
CHART_LIMIT = 60
REPLAY_LIMIT = 120


class MarketStore:
    def __init__(self, path):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                start_ms INTEGER NOT NULL,
                source_ms INTEGER NOT NULL,
                receipt_ms INTEGER NOT NULL,
                revision INTEGER NOT NULL,
                complete INTEGER NOT NULL,
                origin TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL,
                first_tick_ms INTEGER,
                last_tick_ms INTEGER,
                tick_price REAL,
                authoritative INTEGER NOT NULL,
                UNIQUE(symbol, start_ms, revision)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS unique_quote
                ON observations(symbol, source_ms, tick_price)
                WHERE origin = 'quote';
        """)

    def latest(self, start_ms):
        row = self.db.execute("""
            SELECT * FROM observations WHERE symbol = ? AND start_ms = ?
            ORDER BY revision DESC LIMIT 1
        """, (SYMBOL, start_ms)).fetchone()
        return dict(row) if row else None

    def append(self, candle, origin, source_ms, receipt_ms, tick_price=None):
        candle = dict(candle)
        candle.update(origin=origin, source_ms=source_ms, receipt_ms=receipt_ms,
                      tick_price=tick_price, revision=candle.get("revision", 0) + 1)
        candle.pop("id", None)
        # The column names come exclusively from the fixed schema and internal fields.
        columns = ", ".join(candle)
        placeholders = ", ".join("?" for _ in candle)
        with self.db:
            cursor = self.db.execute(
                f"INSERT INTO observations ({columns}) VALUES ({placeholders})", tuple(candle.values())
            )
        candle["id"] = cursor.lastrowid
        return candle

    def new_candle(self, start_ms, price):
        return dict(symbol=SYMBOL, start_ms=start_ms, open=price, high=price, low=price,
                    close=price, volume=None, complete=0, first_tick_ms=None,
                    last_tick_ms=None, authoritative=0)

    def quote(self, source_ms, receipt_ms, price):
        start_ms = source_ms // MINUTE * MINUTE
        candle = self.latest(start_ms) or self.new_candle(start_ms, price)
        if candle["authoritative"] or self.db.execute("""
            SELECT 1 FROM observations WHERE symbol = ? AND source_ms = ?
            AND tick_price = ? AND origin = 'quote'
        """, (SYMBOL, source_ms, price)).fetchone():
            return None

        first, last = candle["first_tick_ms"], candle["last_tick_ms"]
        # History can seed the open before the first observed quote.
        if not candle.get("id") or (first is not None and source_ms <= first):
            candle["open"] = price
        candle["high"] = max(candle["high"], price)
        candle["low"] = min(candle["low"], price)
        if last is None or source_ms >= last:
            candle["close"] = price
        candle["first_tick_ms"] = source_ms if first is None else min(first, source_ms)
        candle["last_tick_ms"] = source_ms if last is None else max(last, source_ms)
        candle["complete"] = int(receipt_ms >= start_ms + MINUTE)
        return self.append(candle, "quote", source_ms, receipt_ms, price)

    def history(self, start_ms, receipt_ms, ohlcv, request_ms):
        old = self.latest(start_ms)
        candle = dict(old) if old else self.new_candle(start_ms, ohlcv["open"])
        # A request made during the minute may return a partial bar after rollover.
        ended_before_request = request_ms >= start_ms + MINUTE
        if not ended_before_request and candle["authoritative"]:
            return None
        if ended_before_request or candle["first_tick_ms"] is None:
            candle.update(ohlcv)
        else:
            candle["volume"] = ohlcv["volume"]
        candle["complete"] = int(receipt_ms >= start_ms + MINUTE)
        candle["authoritative"] = int(ended_before_request)
        fields = ("open", "high", "low", "close", "volume", "complete", "authoritative")
        if old and all(candle[key] == old[key] for key in fields):
            return None
        return self.append(candle, "history", start_ms, receipt_ms)

    def complete_due(self, now_ms):
        for candle in self.snapshot():
            if not candle["complete"] and now_ms >= candle["start_ms"] + MINUTE:
                candle["complete"] = 1
                yield self.append(candle, "clock", candle["source_ms"], now_ms)

    def snapshot(self):
        rows = self.db.execute("""
            SELECT o.* FROM observations o JOIN (
                SELECT start_ms, MAX(revision) AS revision FROM observations
                WHERE symbol = ? GROUP BY start_ms ORDER BY start_ms DESC LIMIT ?
            ) latest USING (start_ms, revision)
            WHERE o.symbol = ? ORDER BY o.start_ms
        """, (SYMBOL, CHART_LIMIT, SYMBOL))
        return [dict(row) for row in rows]

    def replay(self):
        rows = self.db.execute("""
            SELECT * FROM (
                SELECT * FROM observations WHERE symbol = ? ORDER BY id DESC LIMIT ?
            ) ORDER BY id
        """, (SYMBOL, REPLAY_LIMIT))
        return [dict(row) for row in rows]

    def last_quote(self):
        return self.db.execute("""
            SELECT source_ms, id FROM observations WHERE symbol = ? AND origin = 'quote'
            ORDER BY source_ms DESC, id DESC LIMIT 1
        """, (SYMBOL,)).fetchone()
