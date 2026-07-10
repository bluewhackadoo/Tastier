"""Localhost web server. Run with:  make run   (binds 127.0.0.1 only)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from . import payoff
from .config import settings
from .streamer import relay
from .tasty import fetch_positions, group_by_underlying, list_accounts

app = FastAPI(title="Tastier Live Analysis", docs_url=None, redoc_url=None)
STATIC = Path(__file__).resolve().parent.parent / "static"

# in-memory cache of last-fetched legs per account (source of truth = tasty)
_legs_cache: dict[str, list[dict]] = {}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health() -> dict:
    problems = settings.validate()
    return {"ok": not problems, "env": settings.tt_env, "problems": problems}


@app.get("/api/setup/validate")
async def setup_validate() -> dict:
    """Full credential check: env file -> auth -> account discovery."""
    problems = settings.validate()
    if problems:
        return {"ok": False, "stage": "env", "problems": problems}
    try:
        accounts = await list_accounts()
    except Exception as exc:
        return {"ok": False, "stage": "auth", "problems": [str(exc)[:300]]}
    return {"ok": True, "stage": "done", "accounts": accounts,
            "env": settings.tt_env}


@app.get("/api/accounts")
async def accounts() -> list[dict]:
    try:
        return await list_accounts()
    except Exception as exc:
        raise HTTPException(502, f"tastytrade auth/accounts failed: {exc}")


@app.get("/api/positions/{account_number}")
async def positions(account_number: str) -> dict:
    try:
        legs = await fetch_positions(account_number)
    except Exception as exc:
        raise HTTPException(502, f"positions fetch failed: {exc}")
    _legs_cache[account_number] = legs
    symbols = {l["streamer_symbol"] for l in legs} | {
        l.get("underlying_streamer") or l["underlying"] for l in legs}
    await relay.ensure_running(symbols)
    return {"groups": group_by_underlying(legs)}


@app.get("/api/analysis/{account_number}/{underlying:path}")
async def analysis(account_number: str, underlying: str) -> dict:
    legs_raw = [l for l in _legs_cache.get(account_number, [])
                if l["underlying"] == underlying]
    if not legs_raw:
        raise HTTPException(404, "no cached legs; call /api/positions first")

    spot_symbol = legs_raw[0].get("underlying_streamer") or underlying
    q = relay.latest.get(spot_symbol, {}) or relay.latest.get(underlying, {})
    spot = q.get("mid") or q.get("bid") or 0.0
    if not spot:
        spot = next((l["mark_price"] for l in legs_raw if l["strike"] is None), 0.0)
    if not spot:
        raise HTTPException(503, "no spot price yet; quote stream warming up")

    legs = []
    for l in legs_raw:
        live = relay.latest.get(l["streamer_symbol"], {})
        legs.append(payoff.Leg(
            qty=l["qty"], multiplier=l["multiplier"], open_price=l["open_price"],
            strike=l["strike"], option_type=l["option_type"],
            dte_years=l["dte_years"], iv=live.get("iv", 0.0) or 0.20,
            symbol=l["symbol"],
        ))
    result = payoff.analysis(legs, float(spot))
    result["legs"] = legs_raw
    result["leg_stats"] = _leg_stats(legs_raw, float(spot))
    # day P/L for this underlying: mark move off prior close plus anything
    # realized today on legs still open (fully-closed legs aren't visible
    # on a positions-only read)
    pl_day = 0.0
    for l, s in zip(legs_raw, result["leg_stats"]):
        base = l.get("close_price") or l["open_price"]
        pl_day += l["qty"] * l["multiplier"] * (s["mark"] - base)
        pl_day += l.get("realized_day", 0.0)
    result["pl_day"] = round(pl_day, 2) or 0.0
    return result


def _leg_stats(legs_raw: list[dict], spot: float) -> list[dict]:
    """Per-leg detail rows for the position table (all position-sized)."""
    out = []
    for l in legs_raw:
        live = relay.latest.get(l["streamer_symbol"], {})
        mark = float(live.get("mid") or l["mark_price"])
        qm = l["qty"] * l["multiplier"]
        if l["strike"] is not None:
            iv = float(live.get("iv", 0.0) or 0.20)
            delta = payoff.bs_delta(spot, l["strike"], l["dte_years"], iv,
                                    l["option_type"])
            theta = payoff.bs_theta(spot, l["strike"], l["dte_years"], iv,
                                    l["option_type"])
            intrinsic = (max(spot - l["strike"], 0.0) if l["option_type"] == "C"
                         else max(l["strike"] - spot, 0.0))
        else:
            iv, delta, theta, intrinsic = None, 1.0, 0.0, mark
        r2 = lambda v: round(v, 2) or 0.0  # `or` normalizes -0.0
        out.append({
            "symbol": l["symbol"], "qty": l["qty"], "strike": l["strike"],
            "option_type": l["option_type"], "expiration": l["expiration"],
            "dte_days": round(l["dte_years"] * 365),
            "trd_prc": l["open_price"], "mark": r2(mark),
            "iv": iv,
            "delta": r2(qm * delta),
            "theta": r2(qm * theta),
            # cash-flow signed like the tastytrade grid: credits positive
            "cost": r2(-qm * l["open_price"]),
            "ext": r2(-qm * (mark - intrinsic)),
            "pl_open": r2(qm * (mark - l["open_price"])),
        })
    return out


@app.websocket("/ws/quotes")
async def ws_quotes(ws: WebSocket) -> None:
    await ws.accept()
    relay.clients.add(ws)
    try:
        for rec in relay.snapshot():
            await ws.send_json({"type": "quote", **rec})
        while True:
            await ws.receive_text()  # keepalive pings from client
    except WebSocketDisconnect:
        pass
    finally:
        relay.clients.discard(ws)


@app.on_event("shutdown")
async def shutdown() -> None:
    await relay.stop()
