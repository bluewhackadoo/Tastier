"""Known-answer tests for the graph math. If these pass, the curves are right."""

import math

import pytest

from app.payoff import (Leg, analysis, breakevens, bs_price, net_open_cost,
                        pl_curve, spot_grid, value_at)


def test_bs_call_known_value():
    # Classic textbook case: S=100 K=100 T=1 sigma=0.20 r=0 -> C = 7.9656
    c = bs_price(100, 100, 1.0, 0.20, "C", r=0.0)
    assert abs(c - 7.9656) < 1e-3


def test_bs_put_call_parity():
    S, K, T, iv, r = 105, 100, 0.5, 0.35, 0.02
    c = bs_price(S, K, T, iv, "C", r)
    p = bs_price(S, K, T, iv, "P", r)
    assert abs((c - p) - (S - K * math.exp(-r * T))) < 1e-9


def test_bs_expiration_is_intrinsic():
    assert bs_price(110, 100, 0.0, 0.5, "C") == 10.0
    assert bs_price(90, 100, 0.0, 0.5, "P") == 10.0
    assert bs_price(90, 100, 0.0, 0.5, "C") == 0.0


def test_bs_non_positive_spot_is_intrinsic():
    # a wide-strike grid can probe spot <= 0; log() must not blow up
    assert bs_price(0.0, 100, 0.5, 0.3, "P") == 100.0
    assert bs_price(-5.0, 100, 0.5, 0.3, "C") == 0.0


def test_wide_strike_grid_stays_positive_and_analysis_survives():
    # a 100P against a 650C — wide strikes must not push the grid <= 0
    legs = [
        Leg(qty=-4, multiplier=100, open_price=1.4, strike=100, option_type="P",
            dte_years=0.7, iv=0.5),
        Leg(qty=-2, multiplier=100, open_price=2.0, strike=650, option_type="C",
            dte_years=0.7, iv=0.4),
    ]
    grid = spot_grid(450, legs)
    assert min(grid) > 0
    result = analysis(legs, 450.0)  # must not raise math domain error
    assert len(result["grid"]) == len(result["expiration_pl"]) > 50


IC = [  # short iron condor: -1 95P +1 90P -1 105C +1 110C, net credit 1.80
    Leg(qty=-1, multiplier=100, open_price=2.00, strike=95, option_type="P", dte_years=0.1, iv=0.3),
    Leg(qty=+1, multiplier=100, open_price=1.00, strike=90, option_type="P", dte_years=0.1, iv=0.3),
    Leg(qty=-1, multiplier=100, open_price=1.90, strike=105, option_type="C", dte_years=0.1, iv=0.3),
    Leg(qty=+1, multiplier=100, open_price=1.10, strike=110, option_type="C", dte_years=0.1, iv=0.3),
]


def test_iron_condor_credit():
    assert abs(net_open_cost(IC) - (-180.0)) < 1e-9  # net credit $180


def test_iron_condor_expiration_pl():
    grid = [80.0, 92.5, 100.0, 107.5, 120.0]
    pl = pl_curve(IC, grid, at_expiration=True)
    assert abs(pl[2] - 180.0) < 1e-9          # max profit between shorts
    assert abs(pl[0] - (180.0 - 500.0)) < 1e-9  # below long put: credit - width
    assert abs(pl[4] - (180.0 - 500.0)) < 1e-9  # above long call
    assert abs(pl[1] - (180.0 - 250.0)) < 1e-9  # 92.5: short put ITM by 2.5


def test_iron_condor_breakevens():
    grid = spot_grid(100.0, IC, points=801)
    pl = pl_curve(IC, grid, at_expiration=True)
    bes = breakevens(grid, pl)
    assert len(bes) == 2
    assert abs(bes[0] - 93.20) < 0.05   # 95 - 1.80
    assert abs(bes[1] - 106.80) < 0.05  # 105 + 1.80


def test_covered_call():
    legs = [
        Leg(qty=100, multiplier=1, open_price=50.0),                    # shares
        Leg(qty=-1, multiplier=100, open_price=2.0, strike=55,
            option_type="C", dte_years=0.05, iv=0.4),
    ]
    pl = pl_curve(legs, [40.0, 55.0, 70.0], at_expiration=True)
    assert abs(pl[0] - (-1000 + 200)) < 1e-9   # shares -$1000, keep $200 credit
    assert abs(pl[1] - (500 + 200)) < 1e-9     # max at strike
    assert abs(pl[2] - 700.0) < 1e-9           # capped above strike


def test_t0_between_intrinsic_and_smooth():
    """T+0 curve of a long call should exceed expiration curve (time value)."""
    legs = [Leg(qty=1, multiplier=100, open_price=3.0, strike=100,
                option_type="C", dte_years=0.25, iv=0.3)]
    grid = [90.0, 100.0, 110.0]
    exp = pl_curve(legs, grid, at_expiration=True)
    t0 = pl_curve(legs, grid, at_expiration=False)
    for e, t in zip(exp, t0):
        assert t > e  # time value strictly positive pre-expiration


def test_analysis_payload_shape():
    a = analysis(IC, spot=100.0)
    for key in ("spot", "grid", "expiration_pl", "t0_pl", "breakevens",
                "max_profit", "max_loss", "net_open_cost", "live_pl"):
        assert key in a
    assert len(a["grid"]) == len(a["expiration_pl"]) == len(a["t0_pl"])
    assert a["max_profit"] == 180.0
    assert a["max_loss"] == -320.0


def test_grid_contains_spot_and_strikes():
    g = spot_grid(100.0, IC)
    assert min(g) < 90 and max(g) > 110


def test_condor_chains_merge_into_one_curve_group():
    # a back-month strangle (one chain) plus protective wings added later
    # (another chain) jointly form an iron condor; the chart must not split
    # them into two phantom sub-positions (matches mergeCondorGroups)
    def mk(qty, k, t, dte, chain):
        return Leg(qty=qty, multiplier=100, open_price=1.0, strike=k,
                   option_type=t, dte_years=dte / 365, iv=0.4, chain=chain)
    legs = [
        mk(1, 110, "P", 63, 1), mk(-1, 120, "P", 63, 1),
        mk(-1, 180, "C", 63, 1), mk(1, 190, "C", 63, 1),
        mk(-4, 125, "P", 91, 2), mk(-4, 175, "C", 91, 2),
        mk(4, 100, "P", 91, 3), mk(4, 200, "C", 91, 3),
    ]
    r = analysis(legs, 400.0)
    # 91d merges to a single terminal group (embodied in the outer shape),
    # leaving only the 63d curve — no 345/455 / 280/520 strike-pair labels
    assert [c["label"] for c in r["curves"]] == ["63d"]
