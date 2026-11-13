# Project instructions

- Use Python 3.10 or newer. Run the checks from the repository root with `python -m unittest discover -s tests -v` in the project's virtual environment.
- Keep Yahoo quote ingestion, OHLCV history, SQLite writes, and WebSocket delivery traceable. Commit observations before publishing them and keep provider time distinct from receipt time.
- Keep replay clearly labeled and usable with a saved database. Preserve prior revisions when reconciling data and keep local database files out of Git.
- Update the README and design notes when startup, schema, or behavior changes. Record tool and model use in [AI-USE.md](AI-USE.md).
