# Tasty Live Analysis (P1)

Localhost web app: pulls tastytrade positions (read-only) and renders a live
payoff analysis graph — expiration curve, T+0 curve, breakevens, live P/L.

## Security model

- **Read-only OAuth grant** — no trading permission exists on the token.
- Credentials live only in `.env` (chmod 600, gitignored). The browser never
  sees them; it talks only to the local backend.
- Server binds `127.0.0.1` only — unreachable from your network.
- Code contains zero order/trade endpoints (defense in depth).

## Setup (5 minutes)

1. **Install** (Python 3.11+):
   ```
   pip install -r requirements.txt
   ```

2. **Create a read-only OAuth grant**
   - Log in at **my.tastytrade.com** → **Manage** → **My Profile** → **API** →
     **OAuth Applications** → create a personal OAuth app.
   - Scopes: check **read** only. Leave trade unchecked.
   - Generate a **personal grant** → copy the **client secret** and
     **refresh token**.
   - For the paper account: do the same on the **cert/sandbox** portal
     (developer.tastytrade.com → sandbox) — paper uses separate credentials.

3. **Configure**
   ```
   cp .env.example .env
   chmod 600 .env
   # paste TT_SECRET, TT_REFRESH; leave TT_ENV=paper
   ```

4. **Validate**
   ```
   make check
   ```
   Green path prints `"ok": true` with your account list. Any problem is
   named specifically (missing var, bad permissions, auth failure).

5. **Run**
   ```
   make run
   ```
   Open http://127.0.0.1:8420 — positions load on the left, click one for the
   live analysis graph. If setup is incomplete the page shows a guided
   checklist instead.

## Tests

| Command         | What it validates                                            |
|-----------------|--------------------------------------------------------------|
| `make test`     | Offline: BS pricing known answers, iron condor / covered call P&L, breakevens, T+0 > expiration, position schema, grouping, API routing with mocked broker |
| `make test-e2e` | Live against your paper account: auth → accounts → positions → DXLink quote received ≤20s → analysis payload |

## Architecture

```
browser (React + Recharts, no build step)
   │  REST: /api/positions /api/analysis        WS: /ws/quotes
   ▼
FastAPI (127.0.0.1:8420)
   │  holds session + token refresh
   ├─► tastytrade REST  — accounts, positions, option details
   └─► DXLink websocket — Quote + Greeks, one upstream conn, fan-out relay
```

T+0 line = Black-Scholes per leg using **live IV from the Greeks stream** and
live spot; expiration line = intrinsic. Both computed server-side in
`app/payoff.py` (fully unit-tested), rendered client-side.

## Initial user test checklist (paper account)

1. `make check` → ok:true, paper account listed
2. `make run` → positions grouped by underlying, live marks ticking
3. Click a position → graph renders; T+0 line moves with quotes (3s refresh)
4. "stream live" indicator green; kill wifi → "stream down" → restore → auto-reconnects
5. `make test-e2e` → all pass
