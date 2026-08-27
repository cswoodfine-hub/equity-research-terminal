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


# --- a busy model is not a model that refused ------------------------------
# Gemini answers a spike in demand with HTTP 503 and the words "usually temporary". One
# refresh lost sixteen calls to it across the PDUFA and guidance extractors, both
# reporting found: 0 for the night.

def _attempts(monkeypatch, errors, provider="gemini"):
    """Run complete() against a provider that raises `errors` in turn, then answers."""
    monkeypatch.setattr(llm, "provider", lambda prefer=None: provider)
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def fake(*_args, **_kwargs):
        i = calls["n"]
        calls["n"] += 1
        if i < len(errors):
            raise errors[i]
        return "ok"

    monkeypatch.setattr(llm, "_gemini", fake)
    monkeypatch.setattr(llm, "_groq", fake)
    monkeypatch.setattr(llm, "_anthropic", fake)
    return calls


def test_a_503_is_tried_again(monkeypatch):
    calls = _attempts(monkeypatch, [
        RuntimeError("gemini HTTP 503: This model is currently experiencing high demand")])
    assert llm.complete("s", "u") == "ok"
    assert calls["n"] == 2


def test_it_gives_up_after_three_attempts(monkeypatch):
    boom = RuntimeError("gemini HTTP 503: high demand")
    calls = _attempts(monkeypatch, [boom, boom, boom, boom])
    try:
        llm.complete("s", "u")
    except RuntimeError as exc:
        assert "503" in str(exc)
    else:
        raise AssertionError("the failure was swallowed")
    # Three on the primary, then one on the smaller fallback model.
    assert calls["n"] == llm.LLM_ATTEMPTS + 1


def test_a_rate_limit_is_not_retried(monkeypatch):
    """429 keeps firing across a fast loop, which is why pdufa.is_fatal stops the whole
    run on one. Retrying here would spend the budget collecting the same refusal."""
    calls = _attempts(monkeypatch, [RuntimeError("gemini HTTP 429: quota exceeded")])
    try:
        llm.complete("s", "u")
    except RuntimeError:
        pass
    assert calls["n"] == 1


def test_a_bad_key_is_not_retried(monkeypatch):
    calls = _attempts(monkeypatch, [RuntimeError("gemini HTTP 401: api key not valid")])
    try:
        llm.complete("s", "u")
    except RuntimeError:
        pass
    assert calls["n"] == 1


def test_a_timeout_is_transient(monkeypatch):
    calls = _attempts(monkeypatch, [TimeoutError("read timed out")])
    assert llm.complete("s", "u") == "ok"
    assert calls["n"] == 2


def test_a_working_call_is_made_once(monkeypatch):
    calls = _attempts(monkeypatch, [])
    assert llm.complete("s", "u") == "ok"
    assert calls["n"] == 1


def test_no_provider_still_says_so(monkeypatch):
    monkeypatch.setattr(llm, "provider", lambda prefer=None: None)
    try:
        llm.complete("s", "u")
    except RuntimeError as exc:
        assert "no model provider configured" in str(exc)
    else:
        raise AssertionError("a missing provider was not reported")


# --- a smaller model on the same key ---------------------------------------
# Retrying a spike is not enough when the flagship is busy for hours. On 2026-08-27
# gemini-flash-latest returned 503 on every attempt while gemini-flash-lite-latest
# answered on the same key, and a batch that had found nothing found a real figure.

def test_the_fallback_model_answers_when_the_primary_is_busy(monkeypatch):
    monkeypatch.setattr(llm, "provider", lambda prefer=None: "gemini")
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
    seen = []

    def fake(system, user, max_tokens, thinking_budget=None, model=None):
        seen.append(model or llm.GEMINI_MODEL)
        if (model or llm.GEMINI_MODEL) == llm.GEMINI_MODEL:
            raise RuntimeError("gemini HTTP 503: high demand")
        return "ok"

    monkeypatch.setattr(llm, "_gemini", fake)
    assert llm.complete("s", "u") == "ok"
    # The primary got its full allowance first, then the smaller model once.
    assert seen == [llm.GEMINI_MODEL] * llm.LLM_ATTEMPTS + [llm.GEMINI_FALLBACK_MODEL]


def test_the_original_failure_is_reported_when_the_fallback_fails_too(monkeypatch):
    monkeypatch.setattr(llm, "provider", lambda prefer=None: "gemini")
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    def fake(system, user, max_tokens, thinking_budget=None, model=None):
        raise RuntimeError("gemini HTTP 503: high demand"
                           if model is None else "fallback also down")

    monkeypatch.setattr(llm, "_gemini", fake)
    try:
        llm.complete("s", "u")
    except RuntimeError as exc:
        # The primary's failure is the one worth reading; the fallback is an attempt to
        # rescue it, not the story.
        assert "503" in str(exc)
    else:
        raise AssertionError("the failure was swallowed")


def test_a_permanent_failure_never_reaches_the_fallback(monkeypatch):
    monkeypatch.setattr(llm, "provider", lambda prefer=None: "gemini")
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
    seen = []

    def fake(system, user, max_tokens, thinking_budget=None, model=None):
        seen.append(model)
        raise RuntimeError("gemini HTTP 401: api key not valid")

    monkeypatch.setattr(llm, "_gemini", fake)
    try:
        llm.complete("s", "u")
    except RuntimeError:
        pass
    assert seen == [None]          # one attempt, no retry, no fallback


def test_the_fallback_is_skipped_when_it_is_the_same_model(monkeypatch):
    monkeypatch.setattr(llm, "provider", lambda prefer=None: "gemini")
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
    monkeypatch.setattr(llm, "GEMINI_FALLBACK_MODEL", llm.GEMINI_MODEL)
    seen = []

    def fake(system, user, max_tokens, thinking_budget=None, model=None):
        seen.append(model)
        raise RuntimeError("gemini HTTP 503: high demand")

    monkeypatch.setattr(llm, "_gemini", fake)
    try:
        llm.complete("s", "u")
    except RuntimeError:
        pass
    assert len(seen) == llm.LLM_ATTEMPTS
