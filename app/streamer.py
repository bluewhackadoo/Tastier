"""DXLink quote relay.

One upstream DXLink connection per server; latest Quote/Greeks per symbol
are cached and pushed to all connected browser websockets. The browser
never talks to DXLink directly and never sees an API token.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import time
from typing import Any

from tastytrade import DXLinkStreamer
from tastytrade.dxfeed import Candle, Greeks, Quote

from .tasty import get_session


class QuoteRelay:
    def __init__(self) -> None:
        self.latest: dict[str, dict[str, Any]] = {}
        self.candles: dict[str, dict[int, dict]] = {}  # symbol -> {ms ts: ohlc}
        self.clients: set[Any] = set()  # fastapi WebSocket objects
        self._symbols: set[str] = set()
        self._candle_symbols: set[str] = set()
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ---------- lifecycle ----------

    async def ensure_running(self, symbols: set[str]) -> None:
        async with self._lock:
            new = symbols - self._symbols
            self._symbols |= symbols
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
            elif new:
                # restart to pick up new subscriptions (simple + reliable)
                self._task.cancel()
                self._task = asyncio.create_task(self._run())

    async def ensure_candles(self, symbol: str) -> None:
        async with self._lock:
            if symbol in self._candle_symbols:
                return
            self._candle_symbols.add(symbol)
            if self._task is not None and not self._task.done():
                self._task.cancel()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    # ---------- upstream ----------

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                session = await get_session()
                async with DXLinkStreamer(session) as streamer:
                    syms = sorted(self._symbols)
                    if not syms and not self._candle_symbols:
                        await asyncio.sleep(1)
                        continue
                    await streamer.subscribe(Quote, syms)
                    option_syms = [s for s in syms if s.startswith(".")]
                    if option_syms:
                        await streamer.subscribe(Greeks, option_syms)
                    tasks = [
                        asyncio.create_task(
                            self._pump(streamer, Quote, self._on_quote)),
                        asyncio.create_task(
                            self._pump(streamer, Greeks, self._on_greeks)),
                    ]
                    if self._candle_symbols:
                        start = (dt.datetime.now(dt.timezone.utc)
                                 - dt.timedelta(hours=6))
                        await streamer.subscribe_candle(
                            sorted(self._candle_symbols), interval="1m",
                            start_time=start)
                        tasks.append(asyncio.create_task(
                            self._pump(streamer, Candle, self._on_candle)))
                    backoff = 1.0
                    await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # reconnect with backoff
                await self._broadcast({"type": "status", "state": "reconnecting",
                                       "error": str(exc)[:200]})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _pump(self, streamer: DXLinkStreamer, event_cls, handler) -> None:
        async for event in streamer.listen(event_cls):
            await handler(event)

    async def _on_quote(self, q: Quote) -> None:
        bid, ask = float(q.bid_price or 0), float(q.ask_price or 0)
        rec = self.latest.setdefault(q.event_symbol, {"symbol": q.event_symbol})
        rec.update(bid=bid, ask=ask,
                   mid=round((bid + ask) / 2, 4) if bid and ask else bid or ask,
                   ts=time.time())
        await self._broadcast({"type": "quote", **rec})

    async def _on_candle(self, c: Candle) -> None:
        # event symbol carries the aggregation suffix, e.g. "SPCX{=1m}"
        sym = c.event_symbol.split("{")[0]
        if not (c.open and c.close):
            return
        book = self.candles.setdefault(sym, {})
        book[int(c.time)] = {
            "t": int(c.time),
            "o": float(c.open), "h": float(c.high or c.open),
            "l": float(c.low or c.open), "c": float(c.close),
            "v": float(c.volume or 0),
        }
        if len(book) > 500:  # keep the most recent bars only
            for k in sorted(book)[:-400]:
                del book[k]

    def candle_list(self, symbol: str) -> list[dict]:
        book = self.candles.get(symbol, {})
        return [book[k] for k in sorted(book)]

    async def _on_greeks(self, g: Greeks) -> None:
        rec = self.latest.setdefault(g.event_symbol, {"symbol": g.event_symbol})
        rec.update(iv=float(g.volatility or 0), delta=float(g.delta or 0),
                   theta=float(g.theta or 0), gamma=float(g.gamma or 0),
                   ts=time.time())
        await self._broadcast({"type": "greeks", **rec})

    # ---------- downstream ----------

    async def _broadcast(self, msg: dict) -> None:
        dead = []
        for ws in self.clients:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def snapshot(self) -> list[dict]:
        return list(self.latest.values())


relay = QuoteRelay()
