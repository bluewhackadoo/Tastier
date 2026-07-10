"""DXLink quote relay.

One upstream DXLink connection per server; latest Quote/Greeks per symbol
are cached and pushed to all connected browser websockets. The browser
never talks to DXLink directly and never sees an API token.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from tastytrade import DXLinkStreamer
from tastytrade.dxfeed import Greeks, Quote

from .tasty import get_session


class QuoteRelay:
    def __init__(self) -> None:
        self.latest: dict[str, dict[str, Any]] = {}
        self.clients: set[Any] = set()  # fastapi WebSocket objects
        self._symbols: set[str] = set()
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
                    if not syms:
                        await asyncio.sleep(1)
                        continue
                    await streamer.subscribe(Quote, syms)
                    option_syms = [s for s in syms if s.startswith(".")]
                    if option_syms:
                        await streamer.subscribe(Greeks, option_syms)
                    backoff = 1.0
                    quote_task = asyncio.create_task(
                        self._pump(streamer, Quote, self._on_quote)
                    )
                    greeks_task = asyncio.create_task(
                        self._pump(streamer, Greeks, self._on_greeks)
                    )
                    await asyncio.gather(quote_task, greeks_task)
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
