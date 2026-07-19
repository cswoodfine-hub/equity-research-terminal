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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
ANTHROPIC_MODEL = "claude-opus-4-8"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/"
              "models/{model}:generateContent")
_TIMEOUT_S = 60

# Provider, its key variable, and its model. Order is the auto-selection precedence.
_PROVIDERS = (
    ("groq", "GROQ_API_KEY", GROQ_MODEL),
    ("gemini", "GEMINI_API_KEY", GEMINI_MODEL),
    ("anthropic", "ANTHROPIC_API_KEY", ANTHROPIC_MODEL),
)


def _has(var: str) -> bool:
    return bool((os.getenv(var) or "").strip())


def provider() -> str | None:
    """The provider to use, or None when no key is configured."""
    pinned = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    for name, keyvar, _ in _PROVIDERS:
        if name == pinned and _has(keyvar):
            return name
    # An unset or unusable pin falls through to the first key present.
    for name, keyvar, _ in _PROVIDERS:
        if _has(keyvar):
            return name
    return None


def model_name() -> str | None:
    """The model string to record on a note, or None when no provider is configured."""
    active = provider()
    return next((model for name, _, model in _PROVIDERS if name == active), None)


def complete(system: str, user: str, max_tokens: int = 1024) -> str:
    """One completion. Raises when no provider is configured or the call fails, which is
    what the callers already expect: the note degrades to its rules layer and the PDUFA
    run stops on a failure that will repeat."""
    active = provider()
    if active == "groq":
        return _groq(system, user, max_tokens)
    if active == "gemini":
        return _gemini(system, user, max_tokens)
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
        headers={**headers, "Content-Type": "application/json"}, method="POST")
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


def _gemini(system: str, user: str, max_tokens: int) -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        # Low temperature: the note states facts and the extraction reads them, neither
        # wants invention. The honest guards are in the callers, not here.
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
    }
    payload = _post("gemini", GEMINI_URL.format(model=GEMINI_MODEL),
                    {"x-goog-api-key": key}, body)
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
