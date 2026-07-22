"""Strategy grouping — the single source of truth for how a position's legs
partition into strategies (iron condor, vertical, butterfly, ...).

Ported verbatim from the original frontend clusterLegs() so the server can
drive both the position table and the payoff chart from one implementation.
A golden test (tests/test_grouping.py) pins this to the captured frontend
behavior; keep the two in lockstep if either changes.

Legs are plain dicts with at least: strike, option_type ("P"/"C"), qty
(signed), expiration (ISO date), symbol, chain (int|None), and one of
dte_days / dte_years. strike is None for equity/futures legs.
"""

from __future__ import annotations

from math import floor
from typing import Any

Leg = dict[str, Any]


def _js_round(x: float) -> int:
    """JS Math.round: half rounds up toward +inf (differs from Python's
    banker's rounding on exact .5)."""
    return floor(x + 0.5)


def dte_days(l: Leg) -> int:
    if l.get("dte_days") is not None:
        return int(l["dte_days"])
    return _js_round((l.get("dte_years") or 0) * 365)


def _by_strike(ls: list[Leg]) -> list[Leg]:
    return sorted(ls, key=lambda l: (l["strike"], 0 if l["option_type"] == "P" else 1))


def is_condor_shape(ls: list[Leg]) -> bool:
    if len(ls) != 4:
        return False
    if len({l["strike"] for l in ls}) != 4:
        return False
    puts = sorted((l for l in ls if l["option_type"] == "P"), key=lambda l: l["strike"])
    calls = sorted((l for l in ls if l["option_type"] == "C"), key=lambda l: l["strike"])
    q0 = abs(ls[0]["qty"])
    if any(abs(l["qty"]) != q0 for l in ls):
        return False
    if len(puts) == 2 and len(calls) == 2:
        (p_lo, p_hi), (c_lo, c_hi) = puts, calls
        if p_lo["qty"] > 0 and p_hi["qty"] < 0 and c_lo["qty"] < 0 and c_hi["qty"] > 0:
            return True
        if p_lo["qty"] < 0 and p_hi["qty"] > 0 and c_lo["qty"] > 0 and c_hi["qty"] < 0:
            return True
    if len(puts) == 4 or len(calls) == 4:
        signs = [1 if l["qty"] > 0 else -1 for l in sorted(ls, key=lambda l: l["strike"])]
        if signs in ([1, -1, -1, 1], [-1, 1, 1, -1]):
            return True
    return False


def classify(ls: list[Leg]) -> str:
    """Name the strategy for one strike-sorted group of legs."""
    puts = [l for l in ls if l["option_type"] == "P"]
    calls = [l for l in ls if l["option_type"] == "C"]
    q0 = abs(ls[0]["qty"]) if ls else 0
    same_abs = all(abs(l["qty"]) == q0 for l in ls)

    if len(ls) == 4 and len(puts) == 2 and len(calls) == 2 and same_abs:
        (p_lo, p_hi), (c_lo, c_hi) = puts, calls
        if p_lo["qty"] > 0 and p_hi["qty"] < 0 and c_lo["qty"] < 0 and c_hi["qty"] > 0:
            return "Iron Butterfly" if p_hi["strike"] == c_lo["strike"] else "Iron Condor"
        if p_lo["qty"] < 0 and p_hi["qty"] > 0 and c_lo["qty"] > 0 and c_hi["qty"] < 0:
            return "Reverse Iron Condor"
    if len(ls) == 4 and same_abs and (len(puts) == 4 or len(calls) == 4) \
            and is_condor_shape(ls):
        kind = "Put" if len(puts) == 4 else "Call"
        signs = [1 if l["qty"] > 0 else -1 for l in sorted(ls, key=lambda l: l["strike"])]
        return f"{kind} Condor" if signs == [1, -1, -1, 1] else f"Reverse {kind} Condor"
    if len(ls) == 3 and (len(puts) == 3 or len(calls) == 3):
        a, b, c = ls
        if a["qty"] == c["qty"] and b["qty"] == -2 * a["qty"]:
            return ("" if a["qty"] > 0 else "Reverse ") + "Butterfly"
    if len(ls) == 2 and len(puts) == 1 and len(calls) == 1 \
            and (puts[0]["qty"] > 0) == (calls[0]["qty"] > 0):
        kind = "Straddle" if puts[0]["strike"] == calls[0]["strike"] else "Strangle"
        return ("Short " if puts[0]["qty"] < 0 else "") + kind
    if len(ls) == 2 and (len(puts) == 2 or len(calls) == 2) \
            and ls[0]["qty"] == -ls[1]["qty"]:
        return "Vertical"
    if len(ls) == 1:
        return ("Short " if ls[0]["qty"] < 0 else "") \
            + ("Call" if ls[0]["option_type"] == "C" else "Put")
    return "Custom"


def _extract_verticals(legs: list[Leg]) -> list[list[Leg]] | None:
    longs = [l for l in legs if l["qty"] > 0]
    shorts = [l for l in legs if l["qty"] < 0]
    if not longs or len(longs) != len(shorts):
        return None
    if any(abs(l["qty"]) != abs(shorts[i]["qty"]) for i, l in enumerate(longs)):
        return None
    return [[l, shorts[i]] for i, l in enumerate(longs)]


def decompose(ls: list[Leg]) -> list[list[Leg]]:
    """A same-expiry Custom cluster may be several stacked verticals/condors."""
    if len(ls) < 4 or classify(ls) != "Custom":
        return [ls]
    pv = _extract_verticals([l for l in ls if l["option_type"] == "P"])
    cv = _extract_verticals([l for l in ls if l["option_type"] == "C"])
    puts = [l for l in ls if l["option_type"] == "P"]
    calls = [l for l in ls if l["option_type"] == "C"]
    if pv and cv and len(pv) == len(cv):
        return [_by_strike(pv[i] + cv[i]) for i in range(len(pv))]
    if pv and not calls:
        return [_by_strike(v) for v in pv]
    if cv and not puts:
        return [_by_strike(v) for v in cv]
    return [ls]


def merge_condor_groups(groups: list[list[Leg]]) -> list[list[Leg]]:
    """Pairwise-merge chain groups whose union is a condor shape."""
    merged: list[list[Leg]] = []
    used: set[int] = set()
    for i, g1 in enumerate(groups):
        if i in used:
            continue
        partner = -1
        for j in range(i + 1, len(groups)):
            if j not in used and is_condor_shape(g1 + groups[j]):
                partner = j
                break
        if partner >= 0:
            merged.append(g1 + groups[partner])
            used.update((i, partner))
        else:
            merged.append(g1)
    return merged


def _sig(ls: list[Leg]) -> str:
    parts = {f'{l["strike"]}:{l["option_type"]}:{1 if l["qty"] > 0 else (-1 if l["qty"] < 0 else 0)}'
             for l in ls}
    return "|".join(sorted(parts))


def cluster_legs(legs: list[Leg]) -> list[dict]:
    """Partition a position's legs into labeled strategy clusters, in display
    order. Returns [{"label", "legs", "dte"}] — equity/futures first, then one
    or more strategies per expiration."""
    clusters: list[dict] = []
    eq = [l for l in legs if l["strike"] is None]
    if eq:
        label = "Futures" if "/" in (eq[0].get("symbol") or "") else "Stock"
        clusters.append({"label": label, "legs": eq, "dte": 0})

    by_exp: dict[str, list[Leg]] = {}
    for l in legs:
        if l["strike"] is not None:
            by_exp.setdefault(l["expiration"], []).append(l)

    for exp in sorted(by_exp):
        dl = by_exp[exp]
        by_chain: dict[object, list[Leg]] = {}
        for l in dl:
            by_chain.setdefault("__unknown__" if l.get("chain") is None else l["chain"],
                                []).append(l)
        # JS object iteration puts integer-like keys first (ascending), then
        # string keys ("__unknown__") in insertion order — match that
        def _chain_key(k: object) -> tuple:
            return (0, k) if isinstance(k, (int, float)) else (1,)
        groups = [by_chain[k] for k in sorted(by_chain, key=_chain_key)]

        # merge groups with identical strike/type/sign signature (qty summed)
        merged: list[list[Leg]] = []
        for g in groups:
            key = _sig(g)
            idx = next((k for k, m in enumerate(merged) if _sig(m) == key), -1)
            if idx >= 0:
                for leg in g:
                    match = next((l for l in merged[idx]
                                  if l["strike"] == leg["strike"]
                                  and l["option_type"] == leg["option_type"]), None)
                    if match:
                        match["qty"] += leg["qty"]
                    else:
                        merged[idx].append(leg)
            else:
                merged.append(g)

        for m in merge_condor_groups(merged):
            for sub in decompose(_by_strike(m)):
                sub = _by_strike(sub)
                clusters.append({"label": f"{classify(sub)} · {dte_days(sub[0])}d",
                                 "legs": sub, "dte": dte_days(sub[0])})
    return clusters


def fingerprint(legs: list[Leg]) -> list[dict]:
    """Grouping fingerprint for tests: label + sorted leg symbols per cluster."""
    return [{"label": c["label"], "legs": sorted(l["symbol"] for l in c["legs"])}
            for c in cluster_legs(legs)]
