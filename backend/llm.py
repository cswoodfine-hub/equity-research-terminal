"""One text completion, over whichever model provider has a key.

The app was wired to the Anthropic SDK. This is the seam in front of it: the morning
note and the PDUFA extraction call ``complete`` and neither knows nor cares which
provider answered. Groq and Gemini are called over their REST endpoints with urllib, the
way every other source in this app is called, so they need no SDK installed. Anthropic
keeps its SDK, which is already wired and tested.

Selection is explicit or automatic. ``LLM_PROVIDER`` pins one. Otherwise the first key
present wins, in order Groq, Gemini, Anthropic. A provider whose key is absent is never
chosen, so a stale ``LLM_PROVIDER`` degrades rather than crashes.

The key rides in a header, never the URL, so a proxy or a log cannot capture it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
# The floating alias, not a pinned version. Google retires numbered Gemini models and
# answers 404 with a note telling you to update your code, which is a deployment that
# stops working on a date nobody wrote down. The alias tracks the current flash model;
# set GEMINI_MODEL to pin a specific one.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
ANTHROPIC_MODEL = "claude-opus-4-8"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/"
              "models/{model}:generateContent")
_TIMEOUT_S = 60
# Groq sits behind Cloudflare, which blocks urllib's default agent with a 1010. Any
# named agent gets through; without this the key looks rejected when it is fine.
_USER_AGENT = "Novatalis Research/0.1"

# Provider, its key variable, and its model. Order is the auto-selection precedence.
_PROVIDERS = (
    ("groq", "GROQ_API_KEY", GROQ_MODEL),
    ("gemini", "GEMINI_API_KEY", GEMINI_MODEL),
    ("anthropic", "ANTHROPIC_API_KEY", ANTHROPIC_MODEL),
)
_KEYVAR = {name: keyvar for name, keyvar, _ in _PROVIDERS}
_MODEL = {name: model for name, _, model in _PROVIDERS}


def _has(var: str) -> bool:
    return bool((os.getenv(var) or "").strip())


def provider(prefer: str | None = None) -> str | None:
    """The provider to use, or None when no key is configured.

    ``prefer`` pins one provider for a single call, used so the morning note runs on
    Gemini while the bulk PDUFA and readout classifiers run on whatever the global
    ``LLM_PROVIDER`` selects. A preferred provider whose key is absent is ignored, so
    the pin degrades to the normal selection rather than failing.
    """
    want = (prefer or "").strip().lower()
    if want and _has(_KEYVAR.get(want, "")):
        return want
    pinned = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    for name, keyvar, _ in _PROVIDERS:
        if name == pinned and _has(keyvar):
            return name
    # An unset or unusable pin falls through to the first key present.
    for name, keyvar, _ in _PROVIDERS:
        if _has(keyvar):
            return name
    return None


def model_name(prefer: str | None = None) -> str | None:
    """The model string to record on a note, or None when no provider is configured."""
    return _MODEL.get(provider(prefer))


def complete(system: str, user: str, max_tokens: int = 1024,
             prefer: str | None = None, thinking_budget: int | None = None) -> str:
    """One completion. Raises when no provider is configured or the call fails, which is
    what the callers already expect: the note degrades to its rules layer and the PDUFA
    run stops on a failure that will repeat. ``prefer`` pins one provider for this call;
    ``thinking_budget`` caps a Gemini thinking model's reasoning so the answer is not
    truncated, and is ignored by the other providers."""
    active = provider(prefer)
    if active == "groq":
        return _groq(system, user, max_tokens)
    if active == "gemini":
        return _gemini(system, user, max_tokens, thinking_budget)
    if active == "anthropic":
        return _anthropic(system, user, max_tokens)
    raise RuntimeError("no model provider configured "
                       "(set GROQ_API_KEY, GEMINI_API_KEY or ANTHROPIC_API_KEY)")


# --- shared REST plumbing ------------------------------------------------
def _post(label: str, url: str, headers: dict, body: dict) -> dict:
    """POST JSON and parse the reply, turning an HTTP error into a message that names
    the cause. Both providers put the reason in ``error.message``; a bad key is a 400 on
    Gemini and a 401 on Groq, so the code alone does not say why but the body does. The
    body reads once, so this is the only place it can be seen."""
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json",
                 "User-Agent": _USER_AGENT}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = ((json.loads(exc.read().decode("utf-8")).get("error") or {})
                      .get("message", ""))
        except Exception:
            pass
        raise RuntimeError(f"{label} HTTP {exc.code}: {detail or exc.reason}") from exc


# --- Groq, over its OpenAI-compatible endpoint ---------------------------
def groq_text(payload: dict) -> str:
    """The text out of a chat-completions response, or a raised error. Pure."""
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError(f"groq returned nothing: {str(payload)[:120]}")
    return ((choices[0].get("message") or {}).get("content") or "").strip()


def _groq(system: str, user: str, max_tokens: int) -> str:
    key = os.getenv("GROQ_API_KEY", "").strip()
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    return groq_text(_post("groq", GROQ_URL, {"Authorization": f"Bearer {key}"}, body))


# --- Gemini, over REST ---------------------------------------------------
def gemini_text(payload: dict) -> str:
    """The text out of a generateContent response, or a raised error. Pure.

    A response with no candidates is a block or an empty result, not a normal answer, so
    it is surfaced as an error the caller logs rather than returned as an empty note.
    """
    candidates = payload.get("candidates") or []
    if not candidates:
        reason = (payload.get("promptFeedback") or {}).get("blockReason", "no candidates")
        raise ValueError(f"gemini returned nothing: {reason}")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(part.get("text", "") for part in parts).strip()


def _gemini(system: str, user: str, max_tokens: int,
            thinking_budget: int | None = None) -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    # Low temperature: the note states facts and the extraction reads them, neither wants
    # invention. The honest guards are in the callers, not here.
    generation = {"maxOutputTokens": max_tokens, "temperature": 0.2}
    if thinking_budget is not None:
        # gemini-flash-latest is a thinking model. Left unbounded its reasoning can spend
        # the whole output budget and the visible answer truncates mid-sentence. A budget
        # caps the reasoning so the text completes. It is a soft target the model can
        # overshoot, so the caller still sets maxOutputTokens well above it.
        generation["thinkingConfig"] = {"thinkingBudget": thinking_budget}
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": generation,
    }
    try:
        payload = _post("gemini", GEMINI_URL.format(model=GEMINI_MODEL),
                        {"x-goog-api-key": key}, body)
    except RuntimeError as exc:
        # A retired model answers 404 with prose about migrating. Say the one thing
        # that fixes it instead of passing that through.
        if "404" in str(exc) and "no longer available" in str(exc):
            raise RuntimeError(
                f"the Gemini model {GEMINI_MODEL!r} has been retired. Set GEMINI_MODEL "
                f"to a current one, or leave it unset to use the floating alias."
            ) from exc
        raise
    return gemini_text(payload)


# --- Anthropic, over the SDK ---------------------------------------------
def _anthropic(system: str, user: str, max_tokens: int) -> str:
    import anthropic  # lazy, so the app runs without the SDK

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=max_tokens,
        system=system, messages=[{"role": "user", "content": user}])
    return "\n".join(block.text for block in message.content
                     if getattr(block, "type", "") == "text").strip()
