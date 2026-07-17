"""LLM-backed position analysis (advisory only, read-only by design).

Builds a compact dossier for one underlying's open position and asks the
configured LLM for management suggestions. API keys live in the same local
.env as the tastytrade credentials and never reach the browser — only the
generated text does. No trading endpoints exist and none are added here.

Provider selection: LLM_PROVIDER=anthropic|openai|gemini in .env, else the
first of ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY that is set.
Model override: LLM_MODEL. (GitHub Copilot has no public completions API,
so it isn't offered.)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

PROVIDERS = ("anthropic", "openai", "gemini")
_KEY_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-5.1",
    # rolling alias: Google retires pinned models for new API users
    # (gemini-2.5-flash 404s on fresh keys), the alias always resolves
    "gemini": "gemini-flash-latest",
}

SYSTEM_PROMPT = """You are an expert options position manager reviewing one \
underlying's open position for a retail trader who runs premium-selling and \
defined-risk strategies. You receive a dossier: current legs with greeks and \
marks, strategy grouping, roll history, live P/L, and trailing-1-year trading \
stats for this ticker.

Respond with STRICT JSON only (no markdown fences, no prose outside JSON):
{
  "summary": "2-3 sentence assessment of the position as it stands",
  "outlook": "1-2 sentences on what has to happen for it to win/lose from here",
  "recommendations": [
    {
      "type": "hold_collect_theta" | "roll" | "adjust_directional" | "cut_losses" | "take_profits" | "other",
      "title": "short imperative headline",
      "details": "concrete, specific guidance (strikes/expiries/credit targets when relevant)",
      "confidence": "low" | "medium" | "high"
    }
  ],
  "warnings": "key risks, assignment/earnings/liquidity concerns, or empty string"
}

Rules: 2-5 recommendations ordered by preference; at most 2 of type
"adjust_directional" (double-down or directional adjustments); "roll"
recommendations must say which legs, which direction (out/in/up/down or a
combination), and roughly what credit/debit to expect; be candid when
cutting losses or taking profits beats managing. This is decision support,
not an order — never assume execution."""


def provider_status() -> dict:
    """Which provider/model would run, or what's missing."""
    forced = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if forced and forced in PROVIDERS:
        if os.environ.get(_KEY_VARS[forced]):
            return {"provider": forced, "model": _model(forced)}
        return {"provider": None,
                "missing": f"LLM_PROVIDER={forced} but {_KEY_VARS[forced]} is not set in .env"}
    for p in PROVIDERS:
        if os.environ.get(_KEY_VARS[p]):
            return {"provider": p, "model": _model(p)}
    return {"provider": None,
            "missing": "no LLM API key in .env — set ANTHROPIC_API_KEY, "
                       "OPENAI_API_KEY, or GEMINI_API_KEY (and optionally "
                       "LLM_PROVIDER / LLM_MODEL)"}


def _model(provider: str) -> str:
    return os.environ.get("LLM_MODEL", "").strip() or DEFAULT_MODELS[provider]


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


async def analyze(dossier: dict) -> dict:
    """Run the dossier through the configured LLM; returns the parsed JSON
    plus provider/model metadata. Raises RuntimeError with a readable
    message on any failure."""
    st = provider_status()
    if not st.get("provider"):
        raise RuntimeError(st["missing"])
    provider, model = st["provider"], st["model"]
    user_msg = ("Analyze this options position dossier and respond with the "
                "required JSON only:\n" + json.dumps(dossier, indent=1))
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            if provider == "anthropic":
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                             "anthropic-version": "2023-06-01"},
                    json={"model": model, "max_tokens": 2000,
                          "system": SYSTEM_PROMPT,
                          "messages": [{"role": "user", "content": user_msg}]})
                r.raise_for_status()
                text = "".join(b.get("text", "") for b in r.json()["content"])
            elif provider == "openai":
                r = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                    json={"model": model,
                          "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                       {"role": "user", "content": user_msg}]})
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
            else:  # gemini
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    params={"key": os.environ["GEMINI_API_KEY"]},
                    json={"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
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
        raise RuntimeError(f"couldn't parse model reply as JSON: {exc}")
    parsed.setdefault("recommendations", [])
    return {"provider": provider, "model": model, **parsed}
