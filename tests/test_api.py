"""API tests with the tasty layer mocked — validates routing, caching, analysis wiring."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, _legs_cache
from app.streamer import relay

FIXTURE = json.loads(
    (Path(__file__).parent / "positions_iron_condor.json").read_text()
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200 and "ok" in r.json()


@pytest.mark.asyncio
async def test_positions_and_analysis(client):
    with patch("app.main.fetch_positions", new=AsyncMock(return_value=FIXTURE)), \
         patch.object(relay, "ensure_running", new=AsyncMock()):
        r = await client.get("/api/positions/TEST123")
        assert r.status_code == 200
        assert set(r.json()["groups"]) == {"SPX", "SOXL"}

        # seed a fake live quote for SPX so analysis has a spot
        relay.latest["SPX"] = {"symbol": "SPX", "mid": 5975.0}
        r = await client.get("/api/analysis/TEST123/SPX")
        assert r.status_code == 200
        a = r.json()
        assert a["spot"] == 5975.0
        assert len(a["grid"]) == len(a["expiration_pl"]) == len(a["t0_pl"])
        assert a["max_profit"] > 0 > a["max_loss"]
        assert len(a["breakevens"]) == 2
        assert len(a["legs"]) == 4


@pytest.mark.asyncio
async def test_analysis_without_positions_404(client):
    _legs_cache.clear()
    r = await client.get("/api/analysis/NOPE/SPX")
    assert r.status_code == 404
