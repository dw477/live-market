import asyncio
import logging
import math
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import yfinance as yf
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from market import CHART_LIMIT, MINUTE, SYMBOL, MarketStore

ROOT = Path(__file__).resolve().parent
FRESH_MS = 90_000
log = logging.getLogger("uvicorn.error")


def now_ms():
    return time.time_ns() // 1_000_000


def fetch_history():
    return yf.Ticker(SYMBOL).history(period="1d", interval="1m", auto_adjust=False,
                                    timeout=8).tail(CHART_LIMIT)


class Feed:
    def __init__(self, store):
        self.store = store
        self.clients = set()
        self.state = "connecting"
        last_quote = store.last_quote()
        self.last_source, self.last_id = last_quote if last_quote else (None, None)
        self.paused = False
        self.generation = 0
        self.quote_task = None
        self.outage_lock = asyncio.Lock()

    def status(self):
        state = self.state
        if state == "live" and now_ms() - self.last_source > FRESH_MS:
            state = "stale"
        return dict(type="status", state=state, source_ms=self.last_source,
                    observation_id=self.last_id, simulated=self.paused)

    def publish(self, message):
        for queue in self.clients:
            if queue.full():
                # Recover slow clients with a fresh committed snapshot.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(self.snapshot())
            else:
                queue.put_nowait(message)

    def snapshot(self):
        return dict(type="snapshot", observations=self.store.snapshot(), status=self.status())

    def publish_observation(self, row):
        if row:
            self.publish(dict(type="observation", observation=row))

    async def receive_quote(self, message):
        if self.paused or message.get("id") != SYMBOL:
            return
        receipt_ms = now_ms()
        try:
            source_ms = int(message["time"])
            price = float(message["price"])
        except (KeyError, ValueError, TypeError, OverflowError):
            return
        if not 0 < source_ms <= receipt_ms + MINUTE or not math.isfinite(price) or price <= 0:
            return
        row = self.store.quote(source_ms, receipt_ms, price)
        if row and source_ms >= (self.last_source or 0):
            self.last_source, self.last_id = source_ms, row["id"]
        self.state = "live" if self.last_source is not None else "connecting"
        self.publish_observation(row)
        self.publish(self.status())

    async def quotes(self):
        generation = self.generation
        while generation == self.generation:
            try:
                self.state = "connecting"
                self.publish(self.status())
                async with yf.AsyncWebSocket(verbose=False) as ws:
                    await ws.subscribe(SYMBOL)
                    await ws.listen(self.receive_quote)
                # yfinance can consume cancellation while listening and return normally.
                if generation != self.generation:
                    return
                raise ConnectionError("Yahoo quote stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if generation != self.generation:
                    return
                log.warning("Yahoo quote stream unavailable (%s)", type(exc).__name__)
                self.state = "unavailable"
                self.publish(self.status())
                await asyncio.sleep(5)

    async def history(self):
        while True:
            if not self.paused:
                request_ms, generation = now_ms(), self.generation
                try:
                    bars = await asyncio.to_thread(fetch_history)
                except Exception as exc:
                    log.warning("Yahoo OHLCV request failed (%s)", type(exc).__name__)
                else:
                    if generation == self.generation:
                        receipt_ms = now_ms()
                        for timestamp, bar in bars.iterrows():
                            start_ms = int(timestamp.timestamp()) * 1000
                            if start_ms > receipt_ms:
                                continue
                            ohlcv = {key.lower(): float(bar[key]) for key in
                                     ("Open", "High", "Low", "Close", "Volume")}
                            if all(math.isfinite(value) for value in ohlcv.values()):
                                self.publish_observation(
                                    self.store.history(start_ms, receipt_ms, ohlcv, request_ms)
                                )
            await asyncio.sleep(15)

    async def clock(self):
        while True:
            for row in self.store.complete_due(now_ms()):
                self.publish_observation(row)
            self.publish(self.status())
            await asyncio.sleep(1)

    async def toggle_outage(self):
        async with self.outage_lock:
            self.generation += 1
            self.paused = not self.paused
            if self.paused:
                self.state = "unavailable"
                self.publish(self.status())
                await self.stop_quotes()
            else:
                self.quote_task = asyncio.create_task(self.quotes())

    async def stop_quotes(self):
        if self.quote_task:
            task, self.quote_task = self.quote_task, None
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@asynccontextmanager
async def lifespan(app):
    # Let the app surface connection failures and own reconnect timing.
    yf.config.debug.hide_exceptions = False
    store = MarketStore(os.environ.get("MARKET_DB", str(ROOT / "data" / "market.sqlite3")))
    feed = app.state.feed = Feed(store)
    feed.quote_task = asyncio.create_task(feed.quotes())
    tasks = [asyncio.create_task(feed.history()), asyncio.create_task(feed.clock())]
    try:
        yield
    finally:
        feed.generation += 1
        for task in tasks:
            task.cancel()
        await feed.stop_quotes()
        await asyncio.gather(*tasks, return_exceptions=True)
        store.db.close()


app = FastAPI(lifespan=lifespan)
app.mount("/web", StaticFiles(directory=ROOT / "web"), name="web")


@app.get("/")
async def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/replay")
async def replay():
    return app.state.feed.store.replay()


@app.websocket("/ws")
async def stream(socket: WebSocket):
    # Only the local page can use the socket's demo control.
    origin = socket.headers.get("origin")
    if origin and origin != "http://" + socket.headers.get("host", ""):
        await socket.close(code=1008)
        return
    await socket.accept()
    feed = app.state.feed
    queue = asyncio.Queue(maxsize=256)
    feed.clients.add(queue)
    queue.put_nowait(feed.snapshot())

    async def send():
        while True:
            await socket.send_json(await queue.get())

    async def receive():
        while True:
            if await socket.receive_text() == "toggle-outage":
                await feed.toggle_outage()

    tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            with suppress(WebSocketDisconnect):
                task.result()
    finally:
        feed.clients.discard(queue)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
