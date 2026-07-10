"""Tastytrade integration: session lifecycle, positions, symbol mapping.

Read-only by design — this module never imports or calls any order/trade
endpoint. The OAuth grant itself should also be created read-only scope,
giving defense in depth.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from decimal import Decimal
from typing import Any

from tastytrade import Account, Session
from tastytrade.instruments import Future, FutureOption, Option

from .config import settings

_session: Session | None = None


async def get_session() -> Session:
    global _session
    if _session is None:
        _session = Session(
            provider_secret=settings.tt_secret,
            refresh_token=settings.tt_refresh,
            is_test=settings.is_test,
        )
    await _session.refresh()  # no-op if still valid; handles expiry
    return _session


def _f(x: Any) -> float:
    return float(x) if isinstance(x, (int, float, Decimal)) else 0.0


async def list_accounts() -> list[dict]:
    session = await get_session()
    accounts = await Account.get(session)
    return [
        {
            "account_number": a.account_number,
            "nickname": getattr(a, "nickname", None),
            "margin_or_cash": getattr(a, "margin_or_cash", None),
        }
        for a in accounts
    ]


async def fetch_positions(account_number: str) -> list[dict]:
    """Raw positions normalized to our schema, enriched with option details
    and DXLink streamer symbols, grouped by underlying."""
    session = await get_session()
    account = await Account.get(session, account_number)
    positions = await account.get_positions(session, include_marks=True)

    option_symbols = [
        p.symbol for p in positions if p.instrument_type.value == "Equity Option"
    ]
    fut_opt_symbols = [
        p.symbol for p in positions if p.instrument_type.value == "Future Option"
    ]
    option_map: dict[str, Option | FutureOption] = {}
    if option_symbols:
        # Option.get fetches a single symbol per call in this SDK version;
        # no batch endpoint exists, so fan out concurrently.
        opts = await asyncio.gather(*(Option.get(session, s) for s in option_symbols))
        option_map = {o.symbol: o for o in opts}
    if fut_opt_symbols:
        fopts = await asyncio.gather(
            *(FutureOption.get(session, s) for s in fut_opt_symbols)
        )
        option_map.update({o.symbol: o for o in fopts})

    # futures contracts need their DXLink streamer symbol for spot quotes:
    # the contract legs themselves, plus the underlying of futures options
    contracts = {p.symbol for p in positions if p.instrument_type.value == "Future"}
    contracts |= {o.underlying_symbol for o in option_map.values()
                  if isinstance(o, FutureOption)}
    fut_streamer: dict[str, str] = dict(await asyncio.gather(
        *(_future_streamer(session, c) for c in contracts)))

    today = dt.date.today()
    out: list[dict] = []
    for p in positions:
        sign = 1 if p.quantity_direction == "Long" else -1
        leg: dict = {
            "symbol": p.symbol,
            "underlying": p.underlying_symbol,
            "instrument_type": p.instrument_type.value,
            "qty": sign * _f(p.quantity),
            "multiplier": _f(p.multiplier) or 1.0,
            "open_price": _f(p.average_open_price),
            "mark_price": _f(p.mark_price),
            "close_price": _f(p.close_price),          # prior daily close
            "realized_day": _f(p.realized_day_gain),   # $ realized today
            "strike": None,
            "option_type": None,
            "expiration": None,
            "dte_years": 0.0,
            "streamer_symbol": p.underlying_symbol,  # default: equity quote
            "underlying_streamer": p.underlying_symbol,  # spot quote symbol
        }
        if p.instrument_type.value == "Future":
            ss = fut_streamer.get(p.symbol, p.symbol)
            leg.update(streamer_symbol=ss, underlying_streamer=ss)
        opt = option_map.get(p.symbol)
        if opt is not None:
            dte_days = max((opt.expiration_date - today).days, 0)
            leg.update(
                strike=_f(opt.strike_price),
                option_type="C" if opt.option_type.value == "C" else "P",
                expiration=opt.expiration_date.isoformat(),
                dte_years=dte_days / 365.0,
                streamer_symbol=opt.streamer_symbol,
            )
            if isinstance(opt, FutureOption):
                leg["underlying_streamer"] = fut_streamer.get(
                    opt.underlying_symbol, opt.underlying_symbol)
        out.append(leg)
    return out


async def _future_streamer(session: Session, contract: str) -> tuple[str, str]:
    """Resolve a futures contract to its DXLink streamer symbol."""
    try:
        fut = await Future.get(session, contract)
        return contract, fut.streamer_symbol
    except Exception:
        return contract, contract


def group_by_underlying(legs: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for leg in legs:
        groups.setdefault(leg["underlying"], []).append(leg)
    return groups
