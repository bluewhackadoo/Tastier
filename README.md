# Tastier

A local-only TastyTrade dashboard: live positions, payoff graphs, and AI
position analysis. Runs on `127.0.0.1:8420` so your TT credentials never leave
your machine.

## What it does

- **Live positions** — pulls open positions (read-only), groups by underlying,
  streams live marks via DXLink.
- **Payoff graph** — server-side Black-Scholes T+0 curve using live IV plus
  expiration P/L, breakevens, and live P/L. Rendered in the browser with
  Recharts.
- **AI analysis** — asks an LLM to rate position health/risk/P-L and suggest
  actions. Supports Anthropic, OpenAI, Gemini, DeepSeek, and Kimi (Moonshot).
- **History** — every analysis is saved per symbol; switch between past runs
  from the dropdown.
- **Editable prompt** — the position-analysis system prompt lives in
  `app/prompts/position_analysis.md`. A copy in your OS user-data folder can
  override it without rebuilding the app.

## Security model

- **Read-only OAuth grant** — the app cannot trade.
- Credentials live only in a `.env` file inside your OS user-data folder
  (`%LOCALAPPDATA%\Tastier` on Windows, `~/Library/Application Support/Tastier`
  on macOS). Never in source control, never sent to the browser.
- Server binds `127.0.0.1` only.
- No order/trade endpoints in the codebase.

## Quick start (release binary)

Download a zip from [Releases](https://github.com/bluewhackadoo/Tastier/releases):

- **Windows:** run `Tastier.exe`.
- **macOS:** right-click `Tastier.app` → **Open**.

The first-run setup page asks for **TT_SECRET** and **TT_REFRESH**.
See [OAuth setup](#oauth-setup) below. Choose **paper** for the sandbox or
**live** for your real account.

## Developer setup (Python 3.11+)

```bash
pip install -r requirements.txt

# Copy the example .env to your user-data folder and edit it.
# Windows PowerShell:
$d = "$env:LOCALAPPDATA\Tastier"; New-Item -ItemType Directory -Force $d
Copy-Item .env.example "$d\.env"
# macOS / Linux:
mkdir -p ~/Library/Application\ Support/Tastier
cp .env.example ~/Library/Application\ Support/Tastier/.env
chmod 600 ~/Library/Application\ Support/Tastier/.env

make check   # should print ok:true with your accounts
make run     # open http://127.0.0.1:8420
```

## OAuth setup

Get a **read-only** personal OAuth grant from tastytrade.

1. Log in to the right portal:
   - **Paper:** https://developer.tastytrade.com (sandbox login)
   - **Live:** https://my.tastytrade.com
2. **Manage → My Profile → API → OAuth Applications**.
3. Create an app named `Tastier Local`. Scope: **read only**.
4. Create a personal grant.
5. Copy **Client Secret** → `TT_SECRET`, **Refresh Token** → `TT_REFRESH`.

Paper and live credentials are separate. If auth fails, make sure `TT_ENV`
matches the portal you used.

## LLM analysis setup

Add one or more keys to your user-data `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
DEEPSEEK_API_KEY=sk-...
# Kimi/Moonshot accepts either name:
KIMI_API_KEY=sk-...
MOONSHOT_API_KEY=sk-...

# Optional:
LLM_PROVIDER=anthropic          # anthropic | openai | gemini | deepseek | kimi
LLM_MODEL=claude-sonnet-5       # override the default model
KIMI_BASE_URL=https://api.moonshot.ai/v1  # proxy/OpenRouter support
```

The model dropdown is refreshed from each provider at startup. Optional
pricing overrides go in `<user-data>/Tastier/pricing/models_pricing.json`.

## Tests

| Command | What it checks |
|---------|----------------|
| `make test` | Offline: option pricing, P&L, breakevens, position grouping, mocked broker routes |
| `make test-e2e` | Live paper account: auth → positions → DXLink quote → analysis |

## Architecture

```
browser (React + Recharts, no build step)
   │  REST: /api/positions, /api/analyze, /api/analyses
   │  WS:  /ws/quotes
   ▼
FastAPI (127.0.0.1:8420)
   │  session + token refresh
   ├─► tastytrade REST  — accounts, positions, option details
   ├─► DXLink websocket — Quote/Greeks, single upstream, fan-out relay
   └─► LLM providers      — Anthropic, OpenAI, Gemini, DeepSeek, Kimi
```

Key files:

- `app/main.py` — FastAPI routes, DXLink relay, analysis endpoints.
- `app/advisor.py` — LLM provider selection, model enumeration, pricing.
- `app/payoff.py` — T+0/expiration curves and Greeks-based valuation.
- `app/prompts/position_analysis.md` — editable system prompt.
- `run_app.py` — PyInstaller entry point that locates bundled assets.

## Release builds

Push a version tag to build Windows and macOS binaries via GitHub Actions:

```bash
git tag v0.1.0
git push origin v0.1.0
```

`.github/workflows/release.yml` attaches `Tastier-Windows-x64.zip` and
`Tastier-macOS.zip` to a GitHub release. `.github/workflows/nightly.yml`
builds a daily pre-release at 4 AM Pacific if the repo changed in the last 24
hours.

Build locally with:

```bash
make build
```

Output: `dist/Tastier.exe` (Windows) or `dist/Tastier.app` (macOS).
