"""Tastytrade integration: session lifecycle, positions, symbol mapping.

Read-only by design — this module never imports or calls any order/trade
endpoint. The OAuth grant itself should also be created read-only scope,
giving defense in depth.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from decimal import Decimal
from typing import Any

import httpx
from tastytrade import Account, Session
from tastytrade.instruments import Equity, Future, FutureOption, Option

from .config import settings

_session: Session | None = None

# OCC option symbol -> expiration YYMMDD (e.g. "NVDA  261016P00175000")
_OCC_EXP = re.compile(r"(\d{6})[PC]\d")

# TradingView's public symbol-search + logo CDN (used by their own widgets)
_TV_HEADERS = {"User-Agent": "Mozilla/5.0",
               "Origin": "https://www.tradingview.com",
               "Referer": "https://www.tradingview.com/"}


async def fetch_descriptions(underlyings: list[str]) -> dict[str, str]:
    """Company/instrument descriptions from tastytrade for equity underlyings."""
    if not underlyings:
        return {}
    try:
        session = await get_session()
        eqs = await Equity.get(session, underlyings)
        if not isinstance(eqs, list):
            eqs = [eqs]
        return {e.symbol: (e.description or "") for e in eqs}
    except Exception:
        return {}


async def fetch_logo(symbol: str) -> bytes | None:
    """Resolve a ticker to its TradingView logo SVG (equities). None if the
    symbol has no logo or the lookup fails."""
    async with httpx.AsyncClient(headers=_TV_HEADERS, timeout=10) as c:
        try:
            r = await c.get(
                "https://symbol-search.tradingview.com/symbol_search/",
                params={"text": symbol, "type": "stock", "lang": "en"})
            data = r.json()
        except Exception:
            return None
        items = data if isinstance(data, list) else []
        # prefer an exact ticker match, else the first result carrying a logo
        logoid = next((i.get("logoid") for i in items
                       if (i.get("symbol") or "").upper() == symbol.upper()
                       and i.get("logoid")), None)
        if not logoid:
            logoid = next((i.get("logoid") for i in items if i.get("logoid")), None)
        if not logoid:
            return None
        try:
            lr = await c.get(f"https://s3-symbol-logo.tradingview.com/{logoid}.svg")
            if lr.status_code == 200 and "svg" in lr.headers.get("content-type", ""):
                return lr.content
        except Exception:
            return None
    return None


async def get_session() -> Session:
    global _session
    if _session is None:
        _session = Session(
            provider_secret=settings.tt_secret,
            refresh_token=settings.tt_refresh,
            is_test=settings.is_test,
        )
    try:
        await _session.refresh()  # no-op if still valid; handles expiry
    except Exception:
        # a Session copies credentials at construction; if auth fails, drop
        # it so the next call rebuilds from current settings (e.g. after the
        # setup flow saved new credentials) instead of retrying stale ones
        _session = None
        raise
    return _session


def reset_session() -> None:
    """Forget the cached tastytrade session (e.g. after credentials change)."""
    global _session
    _session = None


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

    # attach tastytrade company/instrument descriptions per underlying
    descs = await fetch_descriptions(
        sorted({l["underlying"] for l in out if not l["underlying"].startswith("/")}))
    for l in out:
        l["underlying_desc"] = descs.get(l["underlying"], "")
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


async def fetch_order_chains(account_number: str, underlying: str) -> dict[str, int]:
    """Group option symbols into order chains from transaction history.

    Two symbols belong to the same chain if they ever traded together in one
    order (union-find over per-order symbol sets). This recovers how the
    positions were actually built — e.g. a put vertical and a call vertical
    opened separately stay separate chains even when their legs share an
    expiration and would otherwise pattern-match an iron condor.
    Returns {option_symbol: chain_id}.
    """
    session = await get_session()
    account = await Account.get(session, account_number)
    txns = await account.get_history(session, underlying_symbol=underlying,
                                     per_page=250)
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    orders: dict[Any, list[str]] = {}
    for t in txns:
        it = getattr(t, "instrument_type", None)
        if it is None or "Option" not in str(it.value) or not t.symbol:
            continue
        orders.setdefault(t.order_id, []).append(t.symbol)
    for syms in orders.values():
        for s in syms[1:]:
            union(syms[0], s)

    roots: dict[str, int] = {}
    out: dict[str, int] = {}
    for s in parent:
        r = find(s)
        out[s] = roots.setdefault(r, len(roots))
    return out


async def fetch_roll_basis(account_number: str, underlying: str) -> dict[str, dict]:
    """Roll-adjusted cost basis for one equity-option underlying.

    Returns {expiration_YYMMDD: {"credit": gross_premium, "rolls": n}} where
    credit is the gross premium collected across the whole order chain for
    that expiration and rolls counts orders that both open and close a
    position (tastytrade's "w/ N rolls"). Dividing credit by the current
    position's (units x multiplier) reproduces tastytrade's Avg Trd Pr.
    """
    session = await get_session()
    account = await Account.get(session, account_number)
    txns = await account.get_history(session, underlying_symbol=underlying,
                                     per_page=250)
    by_exp: dict[str, dict] = {}
    orders: dict[tuple, dict] = {}  # (exp, order_id) -> {open, close}
    for t in txns:
        it = getattr(t, "instrument_type", None)
        if it is None or "Option" not in str(it.value):
            continue
        m = _OCC_EXP.search(t.symbol or "")
        if not m:
            continue
        exp = m.group(1)
        rec = by_exp.setdefault(exp, {"credit": 0.0})
        rec["credit"] += float(t.value or 0)
        sub = str(t.transaction_sub_type or "")
        o = orders.setdefault((exp, t.order_id), {"open": False, "close": False})
        if "Open" in sub:
            o["open"] = True
        if "Close" in sub:
            o["close"] = True
    for exp, rec in by_exp.items():
        rec["rolls"] = sum(1 for (e, _), o in orders.items()
                           if e == exp and o["open"] and o["close"])
    return by_exp
