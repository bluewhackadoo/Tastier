"""Payoff math for multi-leg option positions.

Pure functions, no I/O — the entire test harness for graph correctness
lives against this module.

Conventions:
- qty is signed: +2 = long 2 contracts, -1 = short 1.
- Equity legs use strike=None, option_type=None; qty is share count.
- All P/L is relative to net open cost (credit positive for shorts).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


SQRT2 = math.sqrt(2.0)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price(
    spot: float,
    strike: float,
    t_years: float,
    iv: float,
    option_type: str,  # "C" or "P"
    r: float = 0.0,
) -> float:
    """Black-Scholes European price. At t<=0 returns intrinsic."""
    if t_years <= 0 or iv <= 0:
        if option_type == "C":
            return max(spot - strike, 0.0)
        return max(strike - spot, 0.0)
    sig_sqrt_t = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / sig_sqrt_t
    d2 = d1 - sig_sqrt_t
    if option_type == "C":
        return spot * norm_cdf(d1) - strike * math.exp(-r * t_years) * norm_cdf(d2)
    return strike * math.exp(-r * t_years) * norm_cdf(-d2) - spot * norm_cdf(-d1)


def bs_delta(
    spot: float,
    strike: float,
    t_years: float,
    iv: float,
    option_type: str,  # "C" or "P"
    r: float = 0.0,
) -> float:
    """Black-Scholes delta. At/after expiration returns the step function."""
    if t_years <= 0 or iv <= 0:
        if option_type == "C":
            return 1.0 if spot > strike else 0.0
        return -1.0 if spot < strike else 0.0
    sig_sqrt_t = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / sig_sqrt_t
    return norm_cdf(d1) if option_type == "C" else norm_cdf(d1) - 1.0


def bs_theta(
    spot: float,
    strike: float,
    t_years: float,
    iv: float,
    option_type: str,  # "C" or "P"
    r: float = 0.0,
) -> float:
    """Black-Scholes theta per calendar day. Zero at/after expiration."""
    if t_years <= 0 or iv <= 0:
        return 0.0
    sig_sqrt_t = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / sig_sqrt_t
    d2 = d1 - sig_sqrt_t
    theta = -(spot * norm_pdf(d1) * iv) / (2.0 * math.sqrt(t_years))
    if r:
        if option_type == "C":
            theta -= r * strike * math.exp(-r * t_years) * norm_cdf(d2)
        else:
            theta += r * strike * math.exp(-r * t_years) * norm_cdf(-d2)
    return theta / 365.0


@dataclass
class Leg:
    qty: float                 # signed; contracts for options, shares for equity
    multiplier: float          # 100 for standard options, 1 for equity
    open_price: float          # per-unit average open price (always positive)
    strike: float | None = None
    option_type: str | None = None  # "C" | "P" | None (equity)
    dte_years: float = 0.0     # time to expiration in years
    iv: float = 0.0            # live implied vol (from Greeks stream)
    symbol: str = ""


def net_open_cost(legs: list[Leg]) -> float:
    """Signed cash paid to open. Negative = net credit received."""
    return sum(l.qty * l.multiplier * l.open_price for l in legs)


def value_at(legs: list[Leg], spot: float, at_expiration: bool) -> float:
    """Mark-to-model value of the whole position at a hypothetical spot."""
    total = 0.0
    for l in legs:
        if l.strike is None:  # equity
            total += l.qty * l.multiplier * spot
        else:
            t = 0.0 if at_expiration else l.dte_years
            total += l.qty * l.multiplier * bs_price(
                spot, l.strike, t, l.iv, l.option_type or "C"
            )
    return total


def pl_curve(
    legs: list[Leg],
    spots: list[float],
    at_expiration: bool,
) -> list[float]:
    cost = net_open_cost(legs)
    return [value_at(legs, s, at_expiration) - cost for s in spots]


def theta_curve(legs: list[Leg], spots: list[float]) -> list[float]:
    """Position theta ($/day) at each hypothetical spot. Equity legs are 0."""
    out: list[float] = []
    for s in spots:
        total = 0.0
        for l in legs:
            if l.strike is not None:
                total += l.qty * l.multiplier * bs_theta(
                    s, l.strike, l.dte_years, l.iv, l.option_type or "C"
                )
        out.append(total)
    return out


def spot_grid(center: float, legs: list[Leg], points: int = 121) -> list[float]:
    """Grid spanning strikes +/- padding, always including the center."""
    strikes = [l.strike for l in legs if l.strike is not None]
    lo = min(strikes + [center]) if strikes else center
    hi = max(strikes + [center]) if strikes else center
    span = max(hi - lo, center * 0.05, 1.0)
    lo, hi = lo - span * 0.35, hi + span * 0.35
    step = (hi - lo) / (points - 1)
    return [lo + i * step for i in range(points)]


def breakevens(spots: list[float], pl: list[float]) -> list[float]:
    """Zero crossings of the expiration P/L via linear interpolation."""
    out: list[float] = []
    for i in range(1, len(spots)):
        a, b = pl[i - 1], pl[i]
        if a == 0.0:
            out.append(spots[i - 1])
        elif (a < 0 < b) or (a > 0 > b):
            frac = -a / (b - a)
            out.append(spots[i - 1] + frac * (spots[i] - spots[i - 1]))
    # dedupe near-equal values
    deduped: list[float] = []
    for v in out:
        if not deduped or abs(v - deduped[-1]) > 1e-6:
            deduped.append(v)
    return deduped


def analysis(legs: list[Leg], spot: float) -> dict:
    """Full payload for the frontend graph."""
    grid = spot_grid(spot, legs)
    exp = pl_curve(legs, grid, at_expiration=True)
    t0 = pl_curve(legs, grid, at_expiration=False)
    cost = net_open_cost(legs)
    live_value = value_at(legs, spot, at_expiration=False)
    return {
        "spot": spot,
        "grid": [round(x, 4) for x in grid],
        "expiration_pl": [round(x, 2) for x in exp],
        "t0_pl": [round(x, 2) for x in t0],
        "theta": [round(x, 2) for x in theta_curve(legs, grid)],
        "breakevens": [round(x, 2) for x in breakevens(grid, exp)],
        "max_profit": round(max(exp), 2),
        "max_loss": round(min(exp), 2),
        "net_open_cost": round(cost, 2),
        "live_pl": round(live_value - cost, 2),
    }
