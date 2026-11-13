# Assignment 4.1 — Live Market Workstation

## Completed

The local Vue and FastAPI dashboard displays one-minute BTC-USD candles and volume from Yahoo Finance. It shows the source timestamp, age, feed state, and SQLite observation ID. A simulated upstream outage leaves the dashboard available. Saved observations can be replayed in receipt order.

## Design and verification

SQLite commits each observation before it is sent to the browser over WebSocket. Revisions preserve earlier values, and source timestamps determine how late quotes affect the candle. The first source probe found rolling volume fields in the quote stream. The implementation uses Yahoo's one-minute OHLCV history for the volume bars, with quote prices updating the open candle between requests.

The SQLite checks passed for duplicates, revisions, out-of-order quotes, candle completion, and replay after reopening the database. In Chrome, a live quote advanced the displayed observation ID and matched a committed SQLite row received about 2.9 seconds after its Yahoo timestamp. After a server restart, the browser replayed 87 stored observations during a simulated outage and returned to live quotes when the feed resumed.

## Limitations

The dashboard covers one instrument and one interval. Yahoo quote and volume timing can vary. Minute volume can arrive after price changes, and the provider can revise completed candles. Replay plays the latest 120 observations at a fixed pace.

- [Startup and database initialization](README.md)
- [Data flow and SQLite schema](docs/design.md)
- [Verification evidence and revised approach](docs/evidence.md)
- [Project instructions](AGENTS.md)

## Submission links

- GitHub repository URL — 
- Exact submission commit — 
- [30–60 second demonstration video](recording1.mp4)
