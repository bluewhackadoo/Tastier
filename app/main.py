"""Localhost web server. Run with:  make run   (binds 127.0.0.1 only)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import reduce
from math import gcd
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from . import advisor, payoff
from .config import ENV_DIR as CONFIG_DIR, save_credentials, settings
from .streamer import relay
from .tasty import (fetch_logo, fetch_order_chains, fetch_positions,
                    fetch_roll_basis, fetch_year_stats, group_by_underlying,
                    list_accounts, reset_session)


log = logging.getLogger("tastier")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # app-level logging (uvicorn only configures its own loggers);
    # LOG_LEVEL=DEBUG in .env or the environment for more detail
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level, format="%(levelname)s:     %(name)s - %(message)s")
    if level != "DEBUG":  # these two are very chatty at their own levels
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("tastytrade").setLevel(logging.INFO)
    from .config import ENV_PATH
    log.info("config dir: %s (.env %s)", CONFIG_DIR,
             "found" if ENV_PATH.exists() else "MISSING")
    log.info("tastytrade creds: TT_SECRET=%s TT_REFRESH=%s TT_ENV=%s",
             "set" if settings.tt_secret else "MISSING",
             "set" if settings.tt_refresh else "MISSING", settings.tt_env)
    st = advisor.provider_status()
    if st.get("provider"):
        log.info("LLM advisor: provider=%s model=%s", st["provider"], st["model"])
    else:
        log.info("LLM advisor: disabled — %s", st.get("missing"))
    log.info("note: .env is read at process start; restart after editing it")
    yield
    await relay.stop()  # tear down the DXLink relay on shutdown


app = FastAPI(title="Tastier Live Analysis", docs_url=None, redoc_url=None,
              lifespan=lifespan)
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
# Release binaries run from a read-only temp folder; keep the logo cache in
# the same per-user config directory that holds the .env file.
LOGO_DIR = CONFIG_DIR / "logos"
# saved advisor runs, one JSON file per account+underlying (newest first)
ANALYSES_DIR = CONFIG_DIR / "analyses"
ANALYSES_KEEP = 30


def _analyses_file(account_number: str, underlying: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", f"{account_number}_{underlying}")
    return ANALYSES_DIR / f"{safe}.json"


def _load_analyses(account_number: str, underlying: str) -> list[dict]:
    f = _analyses_file(account_number, underlying)
    if f.exists():
        try:
            hist = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(hist, list):
                return hist
        except Exception:
            log.warning("analyses: unreadable history file %s", f)
    return []


def _save_analysis(account_number: str, underlying: str, result: dict) -> None:
    hist = _load_analyses(account_number, underlying)
    hist.insert(0, result)
    del hist[ANALYSES_KEEP:]
    ANALYSES_DIR.mkdir(parents=True, exist_ok=True)
    _analyses_file(account_number, underlying).write_text(
        json.dumps(hist), encoding="utf-8")

# in-memory cache of last-fetched legs per account (source of truth = tasty)
_legs_cache: dict[str, list[dict]] = {}
# per-account, per-underlying roll basis from transaction history; fetched
# lazily on first analysis (never on the 3s poll) since it doesn't change
# intraday for a read-only viewer
_roll_cache: dict[str, dict[str, dict]] = {}
# per-(account, underlying) order-chain map {symbol: chain_id}
_chain_cache: dict[tuple[str, str], dict[str, int]] = {}


async def _order_chains(account_number: str, underlying: str) -> dict[str, int]:
    key = (account_number, underlying)
    if key not in _chain_cache:
        try:
            _chain_cache[key] = await fetch_order_chains(account_number, underlying)
        except Exception:
            _chain_cache[key] = {}
    return _chain_cache[key]


@app.get("/")
async def index() -> FileResponse:
    # no-cache = always revalidate (cheap 304 when unchanged); stale cached
    # copies of this single-file app have repeatedly masked fresh deploys
    return FileResponse(STATIC / "index.html",
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
async def health() -> dict:
    problems = settings.validate()
    return {"ok": not problems, "env": settings.tt_env, "problems": problems,
            "llm": advisor.provider_status()}  # provider/model or what's missing


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


@app.post("/api/setup/credentials")
async def setup_credentials(creds: dict) -> dict:
    """Save user-supplied tastytrade OAuth credentials to the local .env file.

    Only callable against 127.0.0.1; intended for the desktop release binary
    setup flow. Credentials never leave the user's machine.
    """
    secret = str(creds.get("tt_secret", "")).strip()
    refresh = str(creds.get("tt_refresh", "")).strip()
    env = str(creds.get("tt_env", "paper")).strip().lower()
    if env not in ("paper", "live"):
        return {"ok": False, "problems": ["TT_ENV must be 'paper' or 'live'"]}
    if not secret or not refresh:
        return {"ok": False, "problems": ["TT_SECRET and TT_REFRESH are required"]}
    save_credentials(secret, refresh, env)
    # Re-read .env so settings reflects the new values in this process, and
    # drop the cached tastytrade session — it copied the OLD credentials at
    # construction, so keeping it means auth keeps failing ("Invalid JWT")
    # until a restart even though the new credentials are fine.
    from .config import ENV_PATH, load_dotenv
    load_dotenv(ENV_PATH, override=True)
    settings.__init__()  # type: ignore[misc]
    reset_session()
    return await setup_validate()


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
    # attach order-chain ids so same-expiry strategies opened separately
    # stay separate in the UI (cached; one history call per underlying)
    underlyings = sorted({l["underlying"] for l in legs})
    chain_maps = await asyncio.gather(
        *(_order_chains(account_number, u) for u in underlyings))
    merged: dict[str, int] = {}
    for m in chain_maps:
        merged.update(m)
    for l in legs:
        l["chain"] = merged.get(l["symbol"])

    _legs_cache[account_number] = legs
    symbols = {l["streamer_symbol"] for l in legs} | {
        l.get("underlying_streamer") or l["underlying"] for l in legs}
    await relay.ensure_running(symbols)
    return {"groups": group_by_underlying(legs)}


@app.get("/api/analysis/{account_number}/{underlying:path}")
async def analysis(account_number: str, underlying: str, hide: str = "") -> dict:
    """Payoff analysis. `hide` is a comma-separated list of leg symbols to
    exclude from the chart/summary math (the UI's per-strategy toggles);
    the table data (leg_stats, roll_basis) always covers every leg."""
    legs_raw = [l for l in _legs_cache.get(account_number, [])
                if l["underlying"] == underlying]
    if not legs_raw:
        raise HTTPException(404, "no cached legs; call /api/positions first")

    hidden = {s for s in hide.split(",") if s} if hide else set()
    enabled = [l for l in legs_raw if l["symbol"] not in hidden]

    spot_symbol = legs_raw[0].get("underlying_streamer") or underlying
    q = relay.latest.get(spot_symbol, {}) or relay.latest.get(underlying, {})
    spot = q.get("mid") or q.get("bid") or 0.0
    if not spot:
        spot = next((l["mark_price"] for l in legs_raw if l["strike"] is None), 0.0)
    if not spot:
        raise HTTPException(503, "no spot price yet; quote stream warming up")

    legs = []
    for l in enabled:
        live = relay.latest.get(l["streamer_symbol"], {})
        legs.append(payoff.Leg(
            qty=l["qty"], multiplier=l["multiplier"], open_price=l["open_price"],
            strike=l["strike"], option_type=l["option_type"],
            dte_years=l["dte_years"], iv=live.get("iv", 0.0) or 0.20,
            symbol=l["symbol"], chain=l.get("chain"),
        ))
    result = payoff.analysis(legs, float(spot))
    result["legs"] = enabled          # chart-facing: flags, curves context
    stats_all = _leg_stats(legs_raw, float(spot))
    result["leg_stats"] = stats_all   # table-facing: every leg, always
    result["roll_basis"] = await _roll_basis(account_number, underlying, legs_raw)
    result["description"] = legs_raw[0].get("underlying_desc", "") if legs_raw else ""
    # day P/L for the ENABLED legs: mark move off prior close plus anything
    # realized today on legs still open (fully-closed legs aren't visible
    # on a positions-only read)
    mark_by_sym = {s["symbol"]: s["mark"] for s in stats_all}
    pl_day = 0.0
    for l in enabled:
        base = l.get("close_price") or l["open_price"]
        pl_day += l["qty"] * l["multiplier"] * (mark_by_sym[l["symbol"]] - base)
        pl_day += l.get("realized_day", 0.0)
    result["pl_day"] = round(pl_day, 2) or 0.0
    return result


async def _roll_basis(account_number: str, underlying: str,
                      legs_raw: list[dict]) -> dict:
    """Per-expiration roll-adjusted trade price + roll count for this
    underlying, keyed by the leg expiration ISO date. Empty for
    futures/equity or when no transaction history matches."""
    acct = _roll_cache.setdefault(account_number, {})
    if underlying not in acct:
        if underlying.startswith("/"):  # futures options: skip (symbol fmt differs)
            acct[underlying] = {}
        else:
            try:
                acct[underlying] = await fetch_roll_basis(account_number, underlying)
            except Exception:
                acct[underlying] = {}
    roll = acct[underlying]

    by_exp: dict[str, list[dict]] = {}
    for l in legs_raw:
        if l["strike"] is not None and l["expiration"]:
            by_exp.setdefault(l["expiration"], []).append(l)

    out: dict[str, dict] = {}
    for exp_iso, gl in by_exp.items():
        yymmdd = exp_iso[2:4] + exp_iso[5:7] + exp_iso[8:10]  # 2026-10-16 -> 261016
        r = roll.get(yymmdd)
        if not r:
            continue
        units = reduce(gcd, [abs(round(l["qty"])) for l in gl]) or 1
        mult = gl[0]["multiplier"] or 100
        out[exp_iso] = {
            "trd_prc": round(r["credit"] / (units * mult), 2),
            "rolls": r["rolls"],
        }
    return out


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
            "chain": l.get("chain"),
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


_logo_mem: dict[str, bytes | None] = {}  # symbol -> svg bytes, or None = no logo


@app.post("/api/analyze/{account_number}/{underlying:path}")
async def analyze_position(account_number: str, underlying: str) -> dict:
    """On-demand LLM analysis of one underlying's open position. Advisory
    text only — this app has no order endpoints and none are added here."""
    legs_raw = [l for l in _legs_cache.get(account_number, [])
                if l["underlying"] == underlying]
    if not legs_raw:
        raise HTTPException(404, "no cached legs; call /api/positions first")

    spot_symbol = legs_raw[0].get("underlying_streamer") or underlying
    q = relay.latest.get(spot_symbol, {}) or relay.latest.get(underlying, {})
    spot = q.get("mid") or q.get("bid") or 0.0
    if not spot:
        spot = next((l["mark_price"] for l in legs_raw if l["strike"] is None), 0.0)

    stats = _leg_stats(legs_raw, float(spot or 0))
    pa: dict = {}
    if spot:
        legs_p = [payoff.Leg(
            qty=l["qty"], multiplier=l["multiplier"], open_price=l["open_price"],
            strike=l["strike"], option_type=l["option_type"],
            dte_years=l["dte_years"],
            iv=(relay.latest.get(l["streamer_symbol"], {}) or {}).get("iv", 0.0) or 0.20,
            symbol=l["symbol"], chain=l.get("chain")) for l in legs_raw]
        pa = payoff.analysis(legs_p, float(spot))
    try:
        year = await fetch_year_stats(account_number, underlying)
    except Exception:
        year = {}

    dossier = {
        "underlying": underlying,
        "description": legs_raw[0].get("underlying_desc", ""),
        "spot": spot,
        "position": {k: pa.get(k) for k in
                     ("live_pl", "net_open_cost", "max_profit", "max_loss",
                      "breakevens", "exp_dte")},
        "legs": [{k: s.get(k) for k in
                  ("qty", "strike", "option_type", "expiration", "dte_days",
                   "trd_prc", "mark", "delta", "theta", "iv", "chain")}
                 for s in stats],
        "roll_history": await _roll_basis(account_number, underlying, legs_raw),
        "trailing_1yr": year,
    }
    log.info("advisor: analyzing %s (%d legs, %d roll-chain entries)",
             underlying, len(stats), len(dossier["roll_history"]))
    try:
        result = await advisor.analyze(dossier)
    except RuntimeError as exc:
        log.warning("advisor: %s failed — %s", underlying, exc)
        return {"ok": False, "problems": [str(exc)]}
    log.info("advisor: %s done via %s/%s (%d recommendations)", underlying,
             result.get("provider"), result.get("model"),
             len(result.get("recommendations", [])))
    result["ok"] = True
    result["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result["spot_at_run"] = spot
    result["live_pl_at_run"] = pa.get("live_pl")
    _save_analysis(account_number, underlying, result)
    return result


@app.get("/api/analyses/{account_number}/{underlying:path}")
async def analyses_history(account_number: str, underlying: str) -> list[dict]:
    """Saved advisor runs for an underlying, newest first."""
    return _load_analyses(account_number, underlying)


@app.get("/api/logo/{symbol}")
async def logo(symbol: str) -> Response:
    """TradingView company logo for a ticker, cached on disk + in memory so
    each symbol is fetched from TradingView at most once."""
    symbol = symbol.upper()
    hit = "public, max-age=604800"
    if symbol in _logo_mem:
        data = _logo_mem[symbol]
        if data is None:
            raise HTTPException(404, "no logo")
        return Response(data, media_type="image/svg+xml", headers={"Cache-Control": hit})

    svg = LOGO_DIR / f"{symbol}.svg"
    none = LOGO_DIR / f"{symbol}.none"
    if svg.exists():
        data = svg.read_bytes()
        _logo_mem[symbol] = data
        return Response(data, media_type="image/svg+xml", headers={"Cache-Control": hit})
    if none.exists():
        _logo_mem[symbol] = None
        raise HTTPException(404, "no logo")

    data = await fetch_logo(symbol)
    LOGO_DIR.mkdir(exist_ok=True)
    if data:
        svg.write_bytes(data)
        _logo_mem[symbol] = data
        return Response(data, media_type="image/svg+xml", headers={"Cache-Control": hit})
    none.write_text("")  # negative cache marker
    _logo_mem[symbol] = None
    raise HTTPException(404, "no logo")


@app.get("/api/candles/{symbol:path}")
async def candles(symbol: str) -> list[dict]:
    """1-minute candles for a DXLink symbol (subscribes on first request)."""
    await relay.ensure_candles(symbol)
    out = relay.candle_list(symbol)
    if not out:  # give the freshly-restarted stream a moment to backfill
        for _ in range(20):
            await asyncio.sleep(0.25)
            out = relay.candle_list(symbol)
            if out:
                break
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
