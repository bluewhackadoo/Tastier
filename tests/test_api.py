"""API tests with the tasty layer mocked — validates routing, caching, analysis wiring."""

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, _legs_cache
from app.streamer import relay

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "positions_iron_condor.json").read_text()
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
        assert set(r.json()["groups"]) == {"EPIC", "BOLT"}

        # seed a fake live quote for EPIC so analysis has a spot
        relay.latest["EPIC"] = {"symbol": "EPIC", "mid": 4475.0}
        r = await client.get("/api/analysis/TEST123/EPIC")
        assert r.status_code == 200
        a = r.json()
        assert a["spot"] == 4475.0
        assert len(a["grid"]) == len(a["expiration_pl"]) == len(a["t0_pl"])
        assert a["max_profit"] > 0 > a["max_loss"]
        assert len(a["breakevens"]) == 2
        assert len(a["legs"]) == 4


@pytest.mark.asyncio
async def test_analysis_without_positions_404(client):
    _legs_cache.clear()
    r = await client.get("/api/analysis/NOPE/EPIC")
    assert r.status_code == 404


# --- frontend ES module graph -------------------------------------------
# static/index.html is a shell that loads static/js/main.js as a module; the
# graph is resolved by the browser with no build step, so a mistyped relative
# import only fails at runtime. These tests catch it offline instead.

JS_DIR = Path(__file__).parent.parent / "static" / "js"
INDEX = Path(__file__).parent.parent / "static" / "index.html"
_IMPORT_RE = re.compile(r"""^\s*(?:import|export)\b[^;'"]*?from\s+["']([^"']+)["']""",
                        re.MULTILINE)


def _js_files() -> list[Path]:
    return sorted(JS_DIR.rglob("*.js"))


def test_js_entry_and_shell():
    html = INDEX.read_text(encoding="utf-8")
    assert '<script type="module" src="/js/main.js">' in html
    # the old ~1.3k-line inline app must be gone, not merely duplicated
    assert "function App()" not in html
    assert (JS_DIR / "main.js").is_file()


def test_js_imports_all_resolve():
    """Every relative import in the graph points at a file that exists."""
    missing = []
    for f in _js_files():
        for spec in _IMPORT_RE.findall(f.read_text(encoding="utf-8")):
            if not spec.startswith("."):
                continue  # bare specifier: would need an import map, none used
            target = (f.parent / spec).resolve()
            if not target.is_file():
                missing.append(f"{f.relative_to(JS_DIR)} -> {spec}")
    assert not missing, f"unresolved imports: {missing}"


def test_js_graph_is_fully_reachable_from_entry():
    """No orphan modules: everything under static/js is reachable from main.js."""
    seen: set[Path] = set()
    stack = [(JS_DIR / "main.js").resolve()]
    while stack:
        f = stack.pop()
        if f in seen:
            continue
        seen.add(f)
        for spec in _IMPORT_RE.findall(f.read_text(encoding="utf-8")):
            if spec.startswith("."):
                stack.append((f.parent / spec).resolve())
    orphans = {f.resolve() for f in _js_files()} - seen
    assert not orphans, f"unreachable modules: {sorted(p.name for p in orphans)}"


@pytest.mark.asyncio
async def test_js_module_served_with_module_mime(client):
    r = await client.get("/js/main.js")
    assert r.status_code == 200
    # a module served as text/plain is rejected by the browser outright
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "no-cache"
    assert "createRoot" in r.text


@pytest.mark.asyncio
async def test_js_route_rejects_non_modules_and_escapes(client):
    for bad in ("/js/nope.js", "/js/../index.html", "/js/%2e%2e/index.html",
                "/js/../../app/main.py"):
        r = await client.get(bad)
        assert r.status_code != 200, f"{bad} should not be served"
