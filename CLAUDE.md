# Tastier — working notes

Localhost options-position viewer for tastytrade. **Read-only by design**: no
order or trade endpoint exists anywhere in this codebase, and the OAuth grant
should be created read-scope only. Keep it that way — the trading fork lives
in a separate repo (see *Repos*).

## Run it

```powershell
./run.ps1            # uvicorn on 127.0.0.1:8420 with --reload
make test            # offline suite (excludes the live e2e)
make build           # PyInstaller exe (see Packaging)
```

`.env` lives **outside the repo** in the OS user-data folder
(`%LOCALAPPDATA%\Tastier\.env`, macOS `~/Library/Application Support/Tastier`),
overridable with `TASTIER_ENV_DIR`. It holds `TT_SECRET`, `TT_REFRESH`,
`TT_ENV`, and optionally one LLM key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` /
`GEMINI_API_KEY`, plus `LLM_PROVIDER` / `LLM_MODEL`).

**`.env` is read at process start.** `--reload` picks up code edits but *not*
`.env` edits — restart after changing credentials. The startup log prints the
config dir, credential presence, and which LLM provider/model is active.

## Architecture

**Backend** (`app/`) — segmented by concern, keep it that way:

| module | role |
| --- | --- |
| `config.py` | settings, user-data `.env` location, `save_credentials` |
| `tasty.py` | tastytrade API: positions, order chains, roll basis, logos, descriptions |
| `streamer.py` | one DXLink connection; quote/greeks/candle relay, fanned out to browser sockets |
| `payoff.py` | Black-Scholes, payoff curves, breakevens — pure math, no I/O |
| `grouping.py` | **single source of truth** for strategy clustering |
| `advisor.py` | LLM position analysis (Anthropic/OpenAI/Gemini via raw REST) |
| `main.py` | FastAPI routes, caches, orchestration |

**Frontend** — still **no build step**. `static/index.html` is now just a shell:
CSS, the CDN `<script>` tags (React + htm + Recharts), and
`<script type="module" src="/js/main.js">`. The app is an ES module graph under
`static/js/`, served by the `/js/{path}` route in `main.py` (no-cache, forced
`text/javascript`).

| module | role |
| --- | --- |
| `vendor.js` | **the only** reader of the CDN globals — re-exports React hooks, `html`, Recharts pieces |
| `api.js` | `ORIGIN`, `api()`, `wsUrl()` |
| `format.js` | `fmt`/`money`/`fmtK`/`signColor`, date + strike display |
| `scale.js` | `interp`, `niceStep`, `DTE_SHADES` |
| `hooks.js` | `useDividerDrag` |
| `clusters.js` | rehydrates server clusters + RSB badge detection (see invariant 1) |
| `App.js` | top-level state, polling, websocket, left panel |
| `components/` | `Analysis`, `PositionTable`, `AdvisorPanel`, `CandleChart`, `TVTicker`, `chartOverlay`, `ChartTip`, `legs`, `TickerLogo`, `SetupHelp` |

Module rules that keep this working without a bundler: **relative specifiers
with explicit `.js`** (no bare imports — there is no import map), and never read
`window.React`/`Recharts` outside `vendor.js`. Because the browser resolves the
graph at runtime, a mistyped import path fails only on load — `tests/test_api.py`
walks the graph offline and asserts every import resolves, nothing is orphaned,
and `index.html` still points at the entry.

## Invariants (break these and the UI lies)

1. **Grouping happens once, server-side.** `app/grouping.py` partitions legs
   into strategies. `/api/positions` returns clusters per underlying;
   `/api/analysis` returns them for the selected position and hands the same
   partition to `payoff.analysis`. The chart, position table and left panel all
   render that one partition. They previously each had their own logic and
   drifted — that's the bug class this prevents.
   `tests/test_grouping.py` pins it to a golden captured from the original
   frontend implementation. If you change grouping, that test must be updated
   deliberately, never silently.
   The browser's only role is `static/js/clusters.js`, which *rehydrates* the
   server's partition (symbols → leg objects) and falls back to one-group-per-
   expiration if a payload arrives without clusters. Never grow that file into
   a second grouping implementation.
2. **The chart shows enabled legs; the table shows every leg.** Per-strategy
   toggles hide legs from the chart math (`?hide=` on the analysis endpoint)
   but rows stay visible so they can be re-enabled.
3. **Money/greeks are position-sized**, and group-level prices are weighted by
   contract count then normalized per unit (gcd) — a +2/-4/+2 butterfly reports
   its per-1x credit, not a raw sum of leg prices.
4. **P/L is "without rolls"** — unrealized on currently-open legs. The
   roll-adjusted basis (from transaction history) appears only in the group
   `Trd Prc` column with a `w/ N rolls` badge.

## Privacy — non-negotiable

**Never commit real position data.** Test fixtures under `tests/fixtures/` are
**synthetic**: tickers renamed, symbols remapped, cost basis zeroed, while the
grouping structure (chains, relative strikes, quantity ratios, put/call mix,
expirations) is preserved. Real positions were leaked to a public repo once and
required a history purge plus deleting a release tag that still pointed at the
leak commit — check tags, not just branches, if it ever happens again.

A **pre-commit hook** enforces this (`hooks/pre-commit`); enable it once per
clone with `git config core.hooksPath hooks`. It blocks staged `.env`/`*.log`/
`analyses/`, option symbols whose ticker isn't in the synthetic allowlist, and
your account number (set `TASTIER_ACCT` or `.git/acct-guard`).

Also keep out of commits: account numbers, `.env`, `tastier.log`, saved advisor
runs (`analyses/`), and screenshots of positions. `.claude/` and `logos/` are
gitignored.

## Verifying changes

Run the offline suite before pushing (`make test`). For anything that renders,
drive the in-app browser rather than guessing:

- Use the **ext-shaped** Browser tools: `navigate`, `javascript_tool`,
  `read_page`, `read_console_messages`, `preview_start/stop/logs`.
- The **screenshot action is broken** in this environment (times out). Verify
  structurally instead — query the rendered SVG (`path.recharts-area-area`,
  `path.recharts-line-curve`, overlay `text` labels) and table DOM. For
  refactors, capture a before/after DOM snapshot and diff it; that catches what
  a screenshot would, deterministically.
- `javascript_tool` rejects top-level `await` — return a
  `new Promise(res => setTimeout(...))` as the last expression. Keep each call
  under ~30s or it times out; batch long sweeps.

## Gotchas that have burned us

- **Stale processes.** uvicorn bakes in code and `.env` at start; a page can
  also serve from browser cache. `index.html` is sent `Cache-Control: no-cache`
  and dev runs use `--reload`, but if a fix "doesn't apply", suspect a stale
  process or cached page first.
- **Port 8420 conflicts** between a manually-run server and tooling. The
  preview config uses `autoPort` with `python -m app.serve` (honours `$PORT`).
- **Packaging**: build from the project venv with
  `SETUPTOOLS_USE_DISTUTILS=stdlib`; a global-Python build produced a broken
  124MB exe. `dist/Tastier.exe` must not be running during a rebuild.
- **Gemini model names**: Google 404s retired pinned models for new API keys —
  use the rolling `gemini-flash-latest` alias.
- **TradingView**: licensed index feeds (`SP:SPX`) refuse to render in
  third-party embeds; cash indices map to FOREX.com proxies
  (`FOREXCOM:SPXUSD`). Logos are cached to disk so each is fetched once.

## Repos

| repo | visibility | purpose |
| --- | --- | --- |
| `Tastier` | private | the read-only viewer (this one); tag `v0.2.0-server-grouping` |
| `TastierDev` | private | feature work until security review, then merge back |
| `TastierTrade` | private | fork where trading features are built |

`Tastier` was public and may be published again — assume anything committed
here could become public and sanitize accordingly.
