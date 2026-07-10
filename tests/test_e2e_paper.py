"""Live end-to-end against YOUR paper account. Runs only when creds exist.

    make test-e2e     (requires TT_SECRET / TT_REFRESH in .env, TT_ENV=paper)

Asserts full chain: auth -> accounts -> positions -> streamer symbols ->
DXLink quote received -> analysis payload renders.
"""

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("TT_SECRET") and os.environ.get("TT_REFRESH")),
    reason="no tastytrade credentials in environment",
)


@pytest.mark.asyncio
async def test_full_chain_paper():
    from app.tasty import fetch_positions, list_accounts
    from app.streamer import relay
    from app import payoff

    accounts = await list_accounts()
    assert accounts, "no accounts visible to this grant"
    acct = accounts[0]["account_number"]

    legs = await fetch_positions(acct)
    if not legs:
        pytest.skip("paper account has no open positions to validate against")

    symbols = {l["streamer_symbol"] for l in legs} | {l["underlying"] for l in legs}
    await relay.ensure_running(symbols)

    # wait up to 20s for a quote on any tracked symbol
    for _ in range(40):
        if any(s in relay.latest and relay.latest[s].get("mid") for s in symbols):
            break
        await asyncio.sleep(0.5)
    else:
        pytest.fail("no DXLink quote received within 20s")

    underlying = legs[0]["underlying"]
    spot = relay.latest.get(underlying, {}).get("mid") or legs[0]["mark_price"]
    p_legs = [payoff.Leg(qty=l["qty"], multiplier=l["multiplier"],
                         open_price=l["open_price"], strike=l["strike"],
                         option_type=l["option_type"], dte_years=l["dte_years"],
                         iv=relay.latest.get(l["streamer_symbol"], {}).get("iv", 0.2))
              for l in legs if l["underlying"] == underlying]
    result = payoff.analysis(p_legs, float(spot))
    assert len(result["grid"]) > 50
    await relay.stop()
