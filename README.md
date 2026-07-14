# TastyTrade Position Analysis 

Localhost web app: pulls tastytrade positions (read-only) and renders a live
payoff analysis graph — expiration curve, T+0 curve, breakevens, live P/L.
Yest this will be on http://localhost or 127.0.0.1 to avoid breaking TT security policies and to keep your account safe.

## Security model

- **Read-only OAuth grant** — no trading permission exists on the token.
- Credentials live only in a `.env` file inside your OS user-data folder
  (Windows: `%LOCALAPPDATA%\Tastier`, macOS: `~/Library/Application Support/Tastier`).
  They are never mixed with source files and never seen by the browser.
- Server binds `127.0.0.1` only — unreachable from your network.
- Code contains zero order/trade endpoints (defense in depth).

## Quick start (release binary — no Python needed)

Download the latest zip from the [Releases](https://github.com/bluewhackadoo/Tastier/releases)
page, extract, and run:

- **Windows:** `Tastier.exe`
- **macOS:** right-click `Tastier.app` → **Open** (the app is not notarized; Gatekeeper
  will warn on first launch).

The first-run setup page asks for your **TT_SECRET** and **TT_REFRESH**.
See [Get your tastytrade OAuth credentials](#get-your-tastytrade-oauth-credentials)
below. Choose **paper** to practice on the cert/sandbox environment, or **live**
for your real account. Credentials are saved to your OS user-data folder only.

## Developer setup (Python 3.11+)

1. **Install:**
   ```
   pip install -r requirements.txt
   ```

2. **Get your tastytrade OAuth credentials** (same steps as the binary).

3. **Configure** (creates the `.env` in your user-data folder, not the project folder):

   Windows PowerShell:
   ```
   $d = "$env:LOCALAPPDATA\Tastier"; New-Item -ItemType Directory -Force $d
   Copy-Item .env.example "$d\.env"
   # edit "$d\.env" and paste TT_SECRET, TT_REFRESH; leave TT_ENV=paper
   ```

   macOS / Linux:
   ```
   mkdir -p ~/Library/Application\ Support/Tastier
   cp .env.example ~/Library/Application\ Support/Tastier/.env
   chmod 600 ~/Library/Application\ Support/Tastier/.env
   # edit the file and paste TT_SECRET, TT_REFRESH; leave TT_ENV=paper
   ```

4. **Validate:**
   ```
   make check
   ```
   Green path prints `"ok": true` with your account list.

5. **Run:**
   ```
   make run
   ```
   Open http://127.0.0.1:8420.

## Get your tastytrade OAuth credentials

Both the release binary and the dev setup need a **read-only** personal OAuth
grant from tastytrade.

1. Log in to the correct portal:
   - **Paper / cert:** https://developer.tastytrade.com → sandbox login
   - **Live:** https://my.tastytrade.com
2. Go to **Manage → My Profile → API → OAuth Applications**.
3. Click **Create Application** (or equivalent). Give it a name like
   "Tastier Local".
4. **Scopes:** enable **read** only. Do **not** enable trade.
5. Create a **personal grant** for that application.
6. Copy the values:
   - **Client Secret** → paste into the **TT_SECRET** field
   - **Refresh Token** → paste into the **TT_REFRESH** field

Paper and live credentials are separate. If you get an auth error, double-check
that the credential matches the selected environment.

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

## Building a release binary

GitHub Actions builds Windows and macOS binaries automatically when you push a
tag like `v0.1.0`:

```
git tag v0.1.0
git push origin v0.1.0
```

The workflow in `.github/workflows/release.yml` produces
`Tastier-Windows-x64.zip` and `Tastier-macOS.zip` and attaches them to a GitHub
release.

To build locally:

```
make build
```

Output:

- Windows: `dist/Tastier.exe`
- macOS: `dist/Tastier.app`

The dev workflow (`make run`) is unchanged; the binary only bundles the app for
users who don't have Python installed.
