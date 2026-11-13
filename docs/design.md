# Data flow and storage

FastAPI subscribes to Yahoo Finance for BTC-USD quotes using yfinance and refreshes up to 60 one-minute OHLCV bars via the history endpoint. Quote timestamps determine the minute bucket. Quotes update price, while Yahoo's OHLCV history supplies minute volume. Rolling quote volume fields are unsuitable for that histogram. A minute can show a missing volume bar while its history observation is pending. A provider-reported zero is stored as zero.

A single local FastAPI worker writes normalized observations to SQLite and publishes committed rows over `/ws`. Vue renders the latest revisions in Lightweight Charts. The WebSocket sends an initial snapshot, individual observations, and feed status. The local outage control pauses the upstream subscription and history ingestion while the dashboard and database remain available. A real connection failure triggers a retry. Source freshness is measured separately from connection state.

## SQLite schema

The append-only `observations` table assigns each revision an integer `id`. The unique candle revision key is `(symbol, start_ms, revision)`. Rows contain OHLC, nullable volume, a completion flag, and an origin of `quote`, `history`, or `clock`. All time columns are UTC epoch milliseconds. `source_ms` is the Yahoo quote timestamp or the history bar's interval start. Clock revisions preserve the latest underlying source timestamp. `receipt_ms` records when the app receives the observation or emits the completion revision. Quote price and first and last quote timestamps support duplicate detection and source-time ordering. The `authoritative` flag identifies a candle reconciled against a history request started after its minute ended.

- Repeat quotes with the same symbol, timestamp, and price are ignored. Unchanged history snapshots are ignored.
- Changed quotes or history produce a new revision. A late quote can extend the high or low and move the open if it predates the first quote, while a newer close stays intact. Different prices sharing one source timestamp are processed in receipt order. Once completed history is available, it supersedes quote-derived values for that minute. Later history corrections still create revisions.
- At rollover the app writes a completion revision. A completed candle can still be corrected. `GET /api/replay` returns the most recent 120 revisions in insertion order, which preserves processing order even when source timestamps arrive out of order.

Yahoo can delay quotes or revise history. Until reconciliation, a candle built from received quotes may miss prices that occurred before subscription or during an outage. The chart shows 60 minutes at most, and replay is bounded to 120 observations. The database retains earlier observations.
