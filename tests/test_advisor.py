"""Offline tests for the advisor's model-reply parsing and provider pick."""

import pytest

from app.advisor import parse_json_reply, provider_status


def test_parse_plain_json():
    d = parse_json_reply('{"summary": "ok", "recommendations": []}')
    assert d["summary"] == "ok"


def test_parse_fenced_json():
    d = parse_json_reply('```json\n{"summary": "ok", "recommendations": [{"type": "roll"}]}\n```')
    assert d["recommendations"][0]["type"] == "roll"


def test_parse_json_with_prose_around_it():
    d = parse_json_reply('Here you go:\n{"summary": "s", "nested": {"a": 1}} trailing words')
    assert d["nested"]["a"] == 1


def test_parse_rejects_no_json():
    with pytest.raises(ValueError):
        parse_json_reply("no json here at all")


def test_provider_status_no_keys(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                "DEEPSEEK_API_KEY", "KIMI_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    st = provider_status()
    assert st["provider"] is None and "API key" in st["missing"]


def test_provider_status_prefers_forced(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "y")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    st = provider_status()
    assert st["provider"] == "gemini"
