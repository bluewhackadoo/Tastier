"""Schema + grouping tests against a recorded fixture (no network)."""

import json
from pathlib import Path

from app.tasty import group_by_underlying

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures/positions_iron_condor.json").read_text()
)

REQUIRED = {"symbol", "underlying", "instrument_type", "qty", "multiplier",
            "open_price", "mark_price", "strike", "option_type",
            "expiration", "dte_years", "streamer_symbol"}


def test_fixture_schema():
    for leg in FIXTURE:
        assert REQUIRED <= set(leg), f"missing keys in {leg['symbol']}"
        assert isinstance(leg["qty"], (int, float)) and leg["qty"] != 0
        if leg["instrument_type"] == "Equity Option":
            assert leg["strike"] and leg["option_type"] in ("C", "P")
            assert leg["streamer_symbol"].startswith(".")
        else:
            assert leg["strike"] is None


def test_grouping():
    groups = group_by_underlying(FIXTURE)
    assert set(groups) == {"SPX", "SOXL"}
    assert len(groups["SPX"]) == 4
    assert len(groups["SOXL"]) == 1
