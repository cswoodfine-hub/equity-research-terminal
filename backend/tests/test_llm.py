"""The provider seam. No network: the HTTP call itself is never made here.

What matters is selection (the right provider for the keys present) and parsing (the
text out of a Gemini response, and the error out of a blocked one).
"""

import pytest

import llm


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
                "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)


# --- selection ------------------------------------------------------------
def test_no_key_is_no_provider(monkeypatch):
    assert llm.provider() is None
    assert llm.model_name() is None
    with pytest.raises(RuntimeError, match="no model provider"):
        llm.complete("s", "u")


def test_groq_key_selects_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    assert llm.provider() == "groq"
    assert llm.model_name() == llm.GROQ_MODEL


def test_gemini_key_selects_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert llm.provider() == "gemini"
    assert llm.model_name() == llm.GEMINI_MODEL


def test_anthropic_key_selects_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert llm.provider() == "anthropic"
    assert llm.model_name() == llm.ANTHROPIC_MODEL


def test_a_free_key_is_not_shadowed_by_a_dead_paid_one(monkeypatch):
    """Auto order is Groq, then Gemini, then Anthropic, so a working free key wins over
    a paid one the account cannot use."""
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "y")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "z")
    assert llm.provider() == "groq"

    monkeypatch.delenv("GROQ_API_KEY")
    assert llm.provider() == "gemini"


def test_an_explicit_pin_is_honoured(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert llm.provider() == "anthropic"


def test_a_pin_without_its_key_falls_through(monkeypatch):
    """A stale pin must not select a provider that cannot run."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert llm.provider() == "gemini"


def test_a_blank_key_is_not_a_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    assert llm.provider() is None


# --- parsing a Gemini response -------------------------------------------
def test_groq_text_reads_the_message():
    payload = {"choices": [{"message": {"content": "one two"}}]}
    assert llm.groq_text(payload) == "one two"
    with pytest.raises(ValueError):
        llm.groq_text({"choices": []})


def test_gemini_text_joins_the_parts():
    payload = {"candidates": [{"content": {"parts": [{"text": "one "}, {"text": "two"}]}}]}
    assert llm.gemini_text(payload) == "one two"


def test_a_blocked_response_is_an_error_not_an_empty_note():
    """No candidates means a safety block or an empty result, which the note layer
    should log and fall back from, not store as a blank note."""
    with pytest.raises(ValueError, match="SAFETY"):
        llm.gemini_text({"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(ValueError):
        llm.gemini_text({})


def test_complete_routes_to_the_selected_provider(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setattr(llm, "_groq",
                        lambda system, user, mx: f"{system}|{user}|{mx}")
    assert llm.complete("sys", "usr", 42) == "sys|usr|42"
