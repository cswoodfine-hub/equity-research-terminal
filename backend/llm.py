"""One text completion, over whichever model provider has a key.

The app was wired to the Anthropic SDK. This is the seam in front of it: the morning
note and the PDUFA extraction call ``complete`` and neither knows nor cares which
provider answered. Gemini is called over its REST endpoint with urllib, the way every
other source in this app is called, so it needs no SDK installed. Anthropic keeps its
SDK, which is already wired and tested.

Selection is explicit or automatic. ``LLM_PROVIDER`` pins one. Otherwise Gemini wins
when ``GEMINI_API_KEY`` is set, then Anthropic when ``ANTHROPIC_API_KEY`` is set, then
nothing, which leaves the note on its rules layer and PDUFA switched off. A provider
whose key is absent is never chosen, so a stale ``LLM_PROVIDER`` degrades rather than
crashes.

The key travels in a header, never the URL, so it cannot be logged by a proxy or land in
a stored request line.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
ANTHROPIC_MODEL = "claude-opus-4-8"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/"
              "models/{model}:generateContent")
_TIMEOUT_S = 60


def _has(var: str) -> bool:
    return bool((os.getenv(var) or "").strip())


def provider() -> str | None:
    """The provider to use, or None when no key is configured."""
    pinned = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if pinned == "gemini" and _has("GEMINI_API_KEY"):
        return "gemini"
    if pinned == "anthropic" and _has("ANTHROPIC_API_KEY"):
        return "anthropic"
    # An unset or unusable pin falls through to auto rather than failing.
    if _has("GEMINI_API_KEY"):
        return "gemini"
    if _has("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def model_name() -> str | None:
    """The model string to record on a note, or None when no provider is configured."""
    return {"gemini": GEMINI_MODEL, "anthropic": ANTHROPIC_MODEL}.get(provider())


def complete(system: str, user: str, max_tokens: int = 1024) -> str:
    """One completion. Raises when no provider is configured or the call fails, which is
    what the callers already expect: the note degrades to its rules layer and the PDUFA
    run stops on a failure that will repeat."""
    active = provider()
    if active == "gemini":
        return _gemini(system, user, max_tokens)
    if active == "anthropic":
        return _anthropic(system, user, max_tokens)
    raise RuntimeError("no model provider configured "
                       "(set GEMINI_API_KEY or ANTHROPIC_API_KEY)")


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
        # wants invention. The models honest guards are in the callers, not here.
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
    }
    request = urllib.request.Request(
        GEMINI_URL.format(model=GEMINI_MODEL),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return gemini_text(json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        # Surface Google's own message. A bad key is a 400, not a 401, so the status
        # code alone does not say why; the body names it ("API key not valid",
        # "RESOURCE_EXHAUSTED"), which is what lets the caller tell a repeating failure
        # from a one-off. The body reads once, so this is the only place it can be seen.
        detail = ""
        try:
            detail = ((json.loads(exc.read().decode("utf-8")).get("error") or {})
                      .get("message", ""))
        except Exception:
            pass
        raise RuntimeError(f"gemini HTTP {exc.code}: {detail or exc.reason}") from exc


# --- Anthropic, over the SDK ---------------------------------------------
def _anthropic(system: str, user: str, max_tokens: int) -> str:
    import anthropic  # lazy, so the app runs without the SDK

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=max_tokens,
        system=system, messages=[{"role": "user", "content": user}])
    return "\n".join(block.text for block in message.content
                     if getattr(block, "type", "") == "text").strip()
