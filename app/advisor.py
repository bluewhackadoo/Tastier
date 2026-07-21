"""LLM-backed position analysis (advisory only, read-only by design).

Builds a compact dossier for one underlying's open position and asks the
configured LLM for management suggestions. API keys live in the same local
.env as the tastytrade credentials and never reach the browser — only the
generated text does. No trading endpoints exist and none are added here.

Provider selection: LLM_PROVIDER=anthropic|openai|gemini|deepseek|kimi in .env,
else the first of ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY /
DEEPSEEK_API_KEY / KIMI_API_KEY that is set.
Model override: LLM_MODEL. (GitHub Copilot has no public completions API,
so it isn't offered.)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

from .config import ENV_DIR

PROVIDERS = ("anthropic", "openai", "gemini", "deepseek", "kimi")
_KEY_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    # Moonshot's docs use MOONSHOT_API_KEY; accept KIMI_API_KEY too.
    "kimi": ("KIMI_API_KEY", "MOONSHOT_API_KEY"),
}
DEFAULT_MODELS = {
    "anthropic": "claude-3-5-sonnet-20241022",
    "openai": "gpt-4o",
    # Google rolling alias: pinned versions (e.g. gemini-2.5-flash) often
    # 404 for newer API keys, while gemini-flash-latest resolves correctly.
    "gemini": "gemini-flash-latest",
    "deepseek": "deepseek-chat",
    "kimi": "moonshot-v1-8k",
}
# Curated, known-good models shown in the UI. The provider's actual API key
# may grant access to only a subset; provider_models() tries to narrow this.
MODEL_OPTIONS = {
    "anthropic": [
        "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet-20240620",
        "claude-3-opus-20240229",
        "claude-3-5-haiku-20241022",
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-2024-08-06",
        "gpt-4-turbo-2024-04-09",
        "gpt-3.5-turbo-0125",
    ],
    "gemini": [
        "gemini-flash-latest",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.5-pro",
        "gemini-1.5-pro-latest",
    ],
    "deepseek": [
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "kimi": [
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
    ],
}
# Approximate pricing in USD per 1M tokens (input / output). Used to sort the
# model dropdown by cost and to label each option. Prices drift over time, so
# these are ballpark figures for relative ranking, not billing estimates.
MODEL_PRICING = {
    "anthropic": {
        "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
        "claude-3-5-sonnet-20240620": {"input": 3.00, "output": 15.00},
        "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
        "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    },
    "openai": {
        "gpt-3.5-turbo-0125": {"input": 0.50, "output": 1.50},
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-2024-08-06": {"input": 2.50, "output": 10.00},
        "gpt-4-turbo-2024-04-09": {"input": 10.00, "output": 30.00},
    },
    "gemini": {
        "gemini-flash-latest": {"input": 0.075, "output": 0.30},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
        "gemini-1.5-flash-latest": {"input": 0.075, "output": 0.30},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-1.5-pro-latest": {"input": 1.25, "output": 5.00},
    },
    "deepseek": {
        "deepseek-chat": {"input": 0.27, "output": 1.10},
        "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    },
    "kimi": {
        # Moonshot AI pricing is CNY-based; these USD figures are approximate.
        "moonshot-v1-8k": {"input": 1.00, "output": 1.00},
        "moonshot-v1-32k": {"input": 2.00, "output": 2.00},
        "moonshot-v1-128k": {"input": 4.00, "output": 4.00},
    },
}

# Filled at startup by refresh_models_and_pricing(); keyed by provider name.
_MODEL_CACHE: dict[str, list[dict]] = {}


def _load_pricing_overrides() -> None:
    """Merge user-supplied pricing from <env dir>/pricing/models_pricing.json
    into MODEL_PRICING. This lets you tune prices without rebuilding the app."""
    path = ENV_DIR / "pricing" / "models_pricing.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for provider, models in data.items():
            if provider not in MODEL_PRICING:
                MODEL_PRICING[provider] = {}
            for model_id, prices in models.items():
                if isinstance(prices, dict) and "input" in prices and "output" in prices:
                    MODEL_PRICING[provider][model_id] = {
                        "input": float(prices["input"]),
                        "output": float(prices["output"]),
                    }
    except Exception:
        # Pricing overrides are optional; a bad file should not block startup.
        pass


def _app_root() -> Path:
    """Resolve the directory holding this module, including inside a PyInstaller
    one-file/one-dir bundle where datas are extracted to sys._MEIPASS."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "app"
    return Path(__file__).resolve().parent


# User-editable override lives next to their .env. If it exists, it wins.
_USER_PROMPT_FILE = ENV_DIR / "prompts" / "position_analysis.md"
_BUNDLED_PROMPT_FILE = _app_root() / "prompts" / "position_analysis.md"

_DEFAULT_SYSTEM_PROMPT = """You are an expert options position manager reviewing one \
underlying's open position for a retail trader who runs premium-selling and \
defined-risk strategies. You receive a dossier: current legs with greeks and \
marks, strategy grouping, roll history, live P/L, and trailing-1-year trading \
stats for this ticker.

Respond with STRICT JSON only (no markdown fences, no prose outside JSON):
{
  "ratings": {
    "health": {"score": 1-10, "label": "1-3 words"},
    "risk":   {"score": 1-10, "label": "1-3 words"},
    "pl":     {"score": 1-10, "label": "1-3 words"}
  },
  "summary": ["3-5 short bullets, each <= 12 words"],
  "outlook": ["2-4 short bullets: what must happen to win/lose from here"],
  "recommendations": [
    {
      "type": "hold_collect_theta" | "roll" | "adjust_directional" | "cut_losses" | "take_profits" | "other",
      "title": "short imperative headline",
      "details": "concrete, specific guidance (strikes/expiries/credit targets when relevant)",
      "confidence": "low" | "medium" | "high"
    }
  ],
  "warnings": ["0-3 short bullets: assignment/earnings/liquidity risks"]
}

Ratings: health = how sound the position is RIGHT NOW (10 = excellent);
risk = forward-looking danger (10 = severe risk); pl = quality of current
P/L vs what the position can realistically still deliver (10 = excellent).

Rules: keep every bullet short and plain — one clause, no semicolons.
2-5 recommendations ordered by preference; at most 2 of type
"adjust_directional" (double-down or directional adjustments); "roll"
recommendations must say which legs, which direction (out/in/up/down or a
combination), and roughly what credit/debit to expect; be candid when
cutting losses or taking profits beats managing. This is decision support,
not an order — never assume execution."""


def _provider_key(provider: str) -> str | None:
    """Return the first configured API key for a provider, stripped of
    whitespace and optional surrounding quotes. Supports a tuple of candidate
    env var names for backwards/forwards compatibility."""
    keys = _KEY_VARS.get(provider)
    if not keys:
        return None
    candidates = keys if isinstance(keys, tuple) else (keys,)
    for var in candidates:
        value = os.environ.get(var)
        if value:
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            return value
    return None


def _load_system_prompt() -> str:
    """Load the editable prompt file, falling back to the bundled copy or the
    inline default."""
    for path in (_USER_PROMPT_FILE, _BUNDLED_PROMPT_FILE):
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception:
                pass
    return _DEFAULT_SYSTEM_PROMPT


def providers_available() -> dict:
    """Key presence per provider (never the keys themselves)."""
    return {p: bool(_provider_key(p)) for p in PROVIDERS}


def provider_status(force: str | None = None, model: str | None = None) -> dict:
    """Which provider/model would run, or what's missing. `force` (from the
    UI's provider selector) overrides the LLM_PROVIDER env default; `model`
    overrides the LLM_MODEL env default."""
    forced = (force or os.environ.get("LLM_PROVIDER", "")).strip().lower()
    if forced and forced in PROVIDERS:
        if _provider_key(forced):
            return {"provider": forced, "model": _model(forced, model)}
        return {"provider": None,
                "missing": f"LLM_PROVIDER={forced} but the key is not set in .env"}
    for p in PROVIDERS:
        if _provider_key(p):
            return {"provider": p, "model": _model(p, model)}
    return {"provider": None,
            "missing": "no LLM API key in .env — set ANTHROPIC_API_KEY, "
                       "OPENAI_API_KEY, GEMINI_API_KEY, DEEPSEEK_API_KEY, "
                       "KIMI_API_KEY, or MOONSHOT_API_KEY "
                       "(and optionally LLM_PROVIDER / LLM_MODEL)"}


def _model_info(provider: str, model_id: str) -> dict:
    """Build a model entry with pricing and recommended flag."""
    price = MODEL_PRICING.get(provider, {}).get(model_id, {})
    inp = price.get("input")
    out = price.get("output")
    total = (inp + out) if inp is not None and out is not None else None
    return {
        "id": model_id,
        "input": inp,
        "output": out,
        "total": total,
        "recommended": DEFAULT_MODELS[provider] == model_id,
    }


async def provider_models(provider: str) -> list[dict]:
    """Return models available for a provider, sorted by total cost per 1M
    tokens (cheapest first). Tries the provider's API when the key is present;
    on any failure returns the curated fallback. Results are cached for the
    process lifetime after the first successful fetch."""
    p = provider.strip().lower()
    if p not in PROVIDERS:
        raise ValueError(f"unknown provider '{provider}'")
    if p in _MODEL_CACHE:
        return _MODEL_CACHE[p]
    fallback_ids = list(MODEL_OPTIONS[p])
    key = _provider_key(p)
    ids = []
    if key:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if p == "anthropic":
                    r = await client.get(
                        "https://api.anthropic.com/v1/models",
                        headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
                    r.raise_for_status()
                    ids = [m["id"] for m in r.json().get("data", [])]
                elif p == "openai":
                    r = await client.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {key}"})
                    r.raise_for_status()
                    ids = [m["id"] for m in r.json().get("data", [])]
                elif p == "gemini":
                    r = await client.get(
                        "https://generativelanguage.googleapis.com/v1beta/models",
                        params={"key": key})
                    r.raise_for_status()
                    ids = [m["name"].split("/")[-1]
                           for m in r.json().get("models", [])
                           if "generateContent" in m.get("supportedGenerationMethods", [])]
                elif p == "deepseek":
                    r = await client.get(
                        "https://api.deepseek.com/models",
                        headers={"Authorization": f"Bearer {key}"})
                    r.raise_for_status()
                    ids = [m["id"] for m in r.json().get("data", [])]
                else:  # kimi
                    base = os.environ.get("KIMI_BASE_URL", "https://api.moonshot.ai/v1").rstrip("/")
                    r = await client.get(
                        f"{base}/models",
                        headers={"Authorization": f"Bearer {key}"})
                    r.raise_for_status()
                    ids = [m["id"] for m in r.json().get("data", [])]
        except Exception:
            ids = []
    if not ids:
        ids = fallback_ids
    # Preserve known-good order first, then append any API-only extras, then
    # sort the whole list by total cost (unknown prices go to the end).
    ordered_ids = [m for m in fallback_ids if m in ids]
    ordered_ids += [m for m in ids if m not in fallback_ids]
    infos = [_model_info(p, m) for m in ordered_ids]
    infos.sort(key=lambda x: (x["total"] is None, x["total"] or 0, x["id"]))
    # Update the curated list with anything new discovered from the API.
    MODEL_OPTIONS[p] = [info["id"] for info in infos]
    _MODEL_CACHE[p] = infos
    return infos


async def refresh_models_and_pricing() -> None:
    """Populate model caches and pricing at startup. For every provider with a
    key, ask its API for the current model list so the UI dropdowns are fresh.
    Pricing is loaded from the bundled defaults plus an optional user override
    file in <env dir>/pricing/models_pricing.json."""
    _load_pricing_overrides()
    for p in PROVIDERS:
        if not _provider_key(p):
            continue
        try:
            await provider_models(p)
        except Exception:
            # Keep the hardcoded fallback; network/model-list failures are not
            # fatal at startup.
            pass


def _model(provider: str, model: str | None = None) -> str:
    forced = (model or os.environ.get("LLM_MODEL", "")).strip()
    return forced or DEFAULT_MODELS[provider]


def parse_json_reply(text: str) -> dict:
    """Extract the first JSON object from a model reply (tolerates fences)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in model reply")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON object in model reply")


async def analyze(dossier: dict, provider: str | None = None,
                  model: str | None = None) -> dict:
    """Run the dossier through the configured (or explicitly requested) LLM;
    returns the parsed JSON plus provider/model metadata. Raises RuntimeError
    with a readable message on any failure."""
    st = provider_status(provider, model)
    if not st.get("provider"):
        raise RuntimeError(st["missing"])
    provider, model = st["provider"], st["model"]
    user_msg = ("Analyze this options position dossier and respond with the "
                "required JSON only:\n" + json.dumps(dossier, indent=1))
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            if provider == "anthropic":
                # generous budget: reasoning models emit thinking blocks (no
                # "text") before the answer, so a small cap can eat the whole
                # budget and leave the visible reply empty
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                             "anthropic-version": "2023-06-01"},
                    json={"model": model, "max_tokens": 8000,
                          "system": _load_system_prompt(),
                          "messages": [{"role": "user", "content": user_msg}]})
                r.raise_for_status()
                data = r.json()
                text = "".join(b.get("text", "") for b in data["content"])
                if not text.strip() and data.get("stop_reason") == "max_tokens":
                    raise RuntimeError(
                        f"{provider} spent its whole token budget before "
                        "answering (thinking-heavy model?) — try again or set "
                        "LLM_MODEL to a non-reasoning model")
            elif provider == "openai":
                r = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                    json={"model": model,
                          "messages": [{"role": "system", "content": _load_system_prompt()},
                                       {"role": "user", "content": user_msg}]})
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
            elif provider == "deepseek":
                r = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
                    json={"model": model,
                          "messages": [{"role": "system", "content": _load_system_prompt()},
                                       {"role": "user", "content": user_msg}]})
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
            elif provider == "kimi":
                base = os.environ.get("KIMI_BASE_URL", "https://api.moonshot.ai/v1").rstrip("/")
                r = await client.post(
                    f"{base}/chat/completions",
                    headers={"Authorization": f"Bearer {_provider_key('kimi')}"},
                    json={"model": model,
                          "messages": [{"role": "system", "content": _load_system_prompt()},
                                       {"role": "user", "content": user_msg}]})
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
            else:  # gemini
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    params={"key": os.environ["GEMINI_API_KEY"]},
                    json={"systemInstruction": {"parts": [{"text": _load_system_prompt()}]},
                          "contents": [{"role": "user", "parts": [{"text": user_msg}]}]})
                r.raise_for_status()
                text = "".join(p.get("text", "")
                               for p in r.json()["candidates"][0]["content"]["parts"])
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        raise RuntimeError(f"{provider} API error {exc.response.status_code}: {detail}")
    except httpx.HTTPError as exc:
        raise RuntimeError(f"{provider} API unreachable: {exc}")

    try:
        parsed: dict[str, Any] = parse_json_reply(text)
    except Exception as exc:
        snippet = " ".join(text.split())[:200] or "<empty reply>"
        raise RuntimeError(
            f"couldn't parse model reply as JSON: {exc} — reply began: {snippet}")
    parsed.setdefault("recommendations", [])
    return {"provider": provider, "model": model, **parsed}
