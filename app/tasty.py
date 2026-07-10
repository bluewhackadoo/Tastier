"""Tastytrade integration: session lifecycle, positions, symbol mapping.

Read-only by design — this module never imports or calls any order/trade
endpoint. The OAuth grant itself should also be created read-only scope,
giving defense in depth.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from tastytrade import Account, Session
from tastytrade.instruments import Option

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
    option_map: dict[str, Option] = {}
    if option_symbols:
        opts = await Option.get(session, option_symbols)
        option_map = {o.symbol: o for o in opts}

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
            "strike": None,
            "option_type": None,
            "expiration": None,
            "dte_years": 0.0,
            "streamer_symbol": p.underlying_symbol,  # default: equity quote
        }
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
        out.append(leg)
    return out


def group_by_underlying(legs: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for leg in legs:
        groups.setdefault(leg["underlying"], []).append(leg)
    return groups
