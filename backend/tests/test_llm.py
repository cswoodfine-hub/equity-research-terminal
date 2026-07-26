"""Provider selection, including the per-call pin the morning note uses. No network."""

import llm


def _only(monkeypatch, **present):
    """Set the given key vars and clear the rest, so selection is deterministic."""
    for var in ("GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    for var, value in present.items():
        monkeypatch.setenv(var, value)


def test_no_key_means_no_provider(monkeypatch):
    _only(monkeypatch)
    assert llm.provider() is None
    assert llm.model_name() is None


def test_auto_selection_prefers_groq_then_gemini(monkeypatch):
    _only(monkeypatch, GROQ_API_KEY="g", GEMINI_API_KEY="m")
    assert llm.provider() == "groq"


def test_llm_provider_env_pins_the_default(monkeypatch):
    _only(monkeypatch, GROQ_API_KEY="g", GEMINI_API_KEY="m", LLM_PROVIDER="gemini")
    assert llm.provider() == "gemini"


def test_prefer_pins_one_call_over_the_global_default(monkeypatch):
    """The note pins Gemini even when the global default is Groq."""
    _only(monkeypatch, GROQ_API_KEY="g", GEMINI_API_KEY="m", LLM_PROVIDER="groq")
    assert llm.provider("gemini") == "gemini"
    assert llm.model_name("gemini") == llm.GEMINI_MODEL


def test_prefer_degrades_when_its_key_is_absent(monkeypatch):
    """A pin for a provider with no key falls back to the normal selection, never fails."""
    _only(monkeypatch, GROQ_API_KEY="g")
    assert llm.provider("gemini") == "groq"


def test_prefer_ignores_an_unknown_provider(monkeypatch):
    _only(monkeypatch, GROQ_API_KEY="g")
    assert llm.provider("nonesuch") == "groq"
