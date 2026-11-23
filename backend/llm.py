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
import time
import urllib.error
import urllib.request

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
# The floating alias, not a pinned version. Google retires numbered Gemini models and
# answers 404 with a note telling you to update your code, which is a deployment that
# stops working on a date nobody wrote down. The alias tracks the current flash model;
# set GEMINI_MODEL to pin a specific one.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
# Where to go when the primary is busy rather than broken. Checked on 2026-08-27, with
# gemini-flash-latest returning 503 and this one answering on the same key, which is the
# whole argument for it: no second account, no second bill, one line of config. It is a
# smaller model, so it will find fewer figures than the primary; the callers' validation
# gates mean fewer, not wronger.
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-flash-lite-latest")
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


# A model that is busy is not a model that refused. Gemini answers a spike in demand with
# HTTP 503 and the words "usually temporary", and one run lost sixteen calls to it across
# the two extractors, both reporting found: 0 for the night. Three attempts with a
# widening pause turns that into a delay instead of a gap.
#
# 429 is deliberately absent. A rate limit keeps firing across a fast loop, which is why
# pdufa.is_fatal stops the whole run on one, and retrying here would spend the budget
# collecting the same refusal.
LLM_ATTEMPTS = 3
LLM_BACKOFF_S = 3.0
_TRANSIENT_STATUSES = ("500", "502", "503", "504")


def _is_transient(exc: BaseException) -> bool:
    """True when the provider was busy rather than unwilling.

    _post has already turned an HTTPError into a RuntimeError naming the status, so the
    status is read out of the message; the Anthropic SDK raises typed errors instead and
    is matched by name.
    """
    name = type(exc).__name__
    if name in ("InternalServerError", "APIConnectionError", "APITimeoutError",
                "APIStatusError", "ServiceUnavailableError"):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    text = str(exc).lower()
    if "429" in text or "quota" in text or "resource_exhausted" in text:
        return False                    # a rate limit is fatal by design, not transient
    return (any(f"http {code}" in text for code in _TRANSIENT_STATUSES)
            or "overloaded" in text or "temporarily unavailable" in text
            or "high demand" in text or "timed out" in text)



def complete(system: str, user: str, max_tokens: int = 1024,
             prefer: str | None = None, thinking_budget: int | None = None) -> str:
    """One completion. Raises when no provider is configured or the call fails, which is
    what the callers already expect: the note degrades to its rules layer and the PDUFA
    run stops on a failure that will repeat. ``prefer`` pins one provider for this call;
    ``thinking_budget`` caps a Gemini thinking model's reasoning so the answer is not
    truncated, and is ignored by the other providers."""
    active = provider(prefer)
    if active is None:
        raise RuntimeError("no model provider configured "
                           "(set GROQ_API_KEY, GEMINI_API_KEY or ANTHROPIC_API_KEY)")
    last = None
    for attempt in range(LLM_ATTEMPTS):
        try:
            if active == "groq":
                return _groq(system, user, max_tokens)
            if active == "gemini":
                return _gemini(system, user, max_tokens, thinking_budget)
            return _anthropic(system, user, max_tokens)
        except Exception as exc:
            if not _is_transient(exc):
                raise
            last = exc
            if attempt + 1 < LLM_ATTEMPTS:
                time.sleep(LLM_BACKOFF_S * (attempt + 1))
    # The primary is busy, not broken. A smaller model on the same key answers while the
    # flagship is overloaded, and a figure read by the small one beats no figure at all:
    # every caller validates what comes back against the document anyway.
    if active == "gemini" and GEMINI_FALLBACK_MODEL \
            and GEMINI_FALLBACK_MODEL != GEMINI_MODEL:
        try:
            return _gemini(system, user, max_tokens, thinking_budget,
                           model=GEMINI_FALLBACK_MODEL)
        except Exception:
            pass                       # the fallback failed too; report the original
    raise last


# --- shared REST plumbing ------------------------------------------------
def _post(label: str, url: str, headers: dict, body: dict,
          timeout: int | None = None) -> dict:
    """POST JSON and parse the reply, turning an HTTP error into a message that names
    the cause. Both providers put the reason in ``error.message``; a bad key is a 400 on
    Gemini and a 401 on Groq, so the code alone does not say why but the body does. The
    body reads once, so this is the only place it can be seen."""
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json",
                 "User-Agent": _USER_AGENT}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout or _TIMEOUT_S) as resp:
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
            thinking_budget: int | None = None, model: str | None = None) -> str:
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
        payload = _post("gemini", GEMINI_URL.format(model=model or GEMINI_MODEL),
                        {"x-goog-api-key": key}, body)
    except RuntimeError as exc:
        # A retired model answers 404 with prose about migrating. Say the one thing
        # that fixes it instead of passing that through.
        if "404" in str(exc) and "no longer available" in str(exc):
            raise RuntimeError(
                f"the Gemini model {model or GEMINI_MODEL!r} has been retired. Set GEMINI_MODEL "
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


# --- a conversation that can call tools ----------------------------------
# ``complete`` is one question and one answer. The chat box (desk_chat.py) is a different
# shape: the model asks for a read of the book, is handed it, asks for another, and only
# then answers. Each provider spells that exchange its own way and wants its own turn
# handed back to it exactly as it wrote it, so the turns are kept here in the provider's
# native form and the caller sees four verbs: ``user``, ``assistant``, ``step`` and
# ``results``.
#
# A tool is {"name", "description", "input_schema"}, the schema a plain JSON Schema
# object. ``step`` returns {"text", "calls"}, each call {"id", "name", "args"}; an answer
# is a step with no calls. ``step(final=True)`` forbids further calls, for the turn where
# the caller has run out of rounds and needs whatever answer the reads so far support.
CHAT_TIMEOUT_S = 120
CHAT_THINKING_BUDGET = 1024


def _retrying(send, fallback=None):
    """``send()`` with the same patience ``complete`` has: three attempts on a busy
    provider with a widening pause, then the fallback if there is one."""
    last = None
    for attempt in range(LLM_ATTEMPTS):
        try:
            return send()
        except Exception as exc:
            if not _is_transient(exc):
                raise
            last = exc
            if attempt + 1 < LLM_ATTEMPTS:
                time.sleep(LLM_BACKOFF_S * (attempt + 1))
    if fallback is not None:
        try:
            return fallback()
        except Exception:
            pass
    raise last


class Conversation:
    """One tool-using exchange with one provider. Subclasses hold the turns."""

    provider = ""
    model = ""

    def __init__(self, system: str, tools: list, max_tokens: int = 2048, post=None):
        self.system, self.tools, self.max_tokens = system, list(tools or []), max_tokens
        self._post = post or _post

    def user(self, text: str) -> None:
        raise NotImplementedError

    def assistant(self, text: str) -> None:
        raise NotImplementedError

    def step(self, final: bool = False) -> dict:
        raise NotImplementedError

    def results(self, results: list) -> None:
        raise NotImplementedError


class GeminiConversation(Conversation):
    """generateContent with functionDeclarations.

    The model's turn is handed back as it came, part for part. A thinking model signs the
    parts that carry a function call (``thoughtSignature``) and refuses the next request
    if a signature it issued is missing, so nothing is rebuilt from what was parsed out
    of the turn. The schema travels as ``parametersJsonSchema``, the field that takes a
    plain JSON Schema; the older ``parameters`` is an OpenAPI subset that rejects
    ``additionalProperties``, which every tool here sets.
    """

    provider = "gemini"

    def __init__(self, system, tools, max_tokens=2048, post=None, model=None):
        super().__init__(system, tools, max_tokens, post)
        self.model = model or GEMINI_MODEL
        self.contents: list = []

    def user(self, text):
        self.contents.append({"role": "user", "parts": [{"text": text}]})

    def assistant(self, text):
        self.contents.append({"role": "model", "parts": [{"text": text}]})

    def body(self, final: bool = False) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": self.system}]},
            "contents": self.contents,
            "generationConfig": {"maxOutputTokens": self.max_tokens, "temperature": 0.2,
                                 "thinkingConfig": {"thinkingBudget": CHAT_THINKING_BUDGET}},
        }
        if self.tools:
            body["tools"] = [{"functionDeclarations": [
                {"name": t["name"], "description": t["description"],
                 "parametersJsonSchema": t["input_schema"]} for t in self.tools]}]
            if final:
                # The tools stay declared, since the turns above name them, and calling
                # them is switched off.
                body["toolConfig"] = {"functionCallingConfig": {"mode": "NONE"}}
        return body

    def read(self, payload: dict) -> dict:
        """{"text", "calls"} out of a response, the model's turn kept as received."""
        candidates = payload.get("candidates") or []
        if not candidates:
            reason = (payload.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise ValueError(f"gemini returned nothing: {reason}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        if not parts:
            raise ValueError("gemini stopped without an answer: "
                             + str(candidates[0].get("finishReason") or "no reason given"))
        self.contents.append({"role": "model", "parts": parts})
        calls = [{"id": p["functionCall"].get("id"), "name": p["functionCall"].get("name"),
                  "args": p["functionCall"].get("args") or {}}
                 for p in parts if isinstance(p.get("functionCall"), dict)]
        text = "".join(p.get("text", "") for p in parts
                       if "text" in p and not p.get("thought")).strip()
        return {"text": text, "calls": calls}

    def step(self, final=False):
        key = os.getenv("GEMINI_API_KEY", "").strip()

        def send(model):
            return self._post("gemini", GEMINI_URL.format(model=model),
                              {"x-goog-api-key": key}, self.body(final), CHAT_TIMEOUT_S)

        fallback = None
        if GEMINI_FALLBACK_MODEL and GEMINI_FALLBACK_MODEL != self.model:
            fallback = lambda: send(GEMINI_FALLBACK_MODEL)
        return self.read(_retrying(lambda: send(self.model), fallback))

    def results(self, results):
        parts = []
        for result in results:
            content = result["content"]
            reply = {"name": result["name"],
                     "response": content if isinstance(content, dict) else {"result": content}}
            if result.get("id"):
                reply["id"] = result["id"]
            parts.append({"functionResponse": reply})
        self.contents.append({"role": "user", "parts": parts})


class GroqConversation(Conversation):
    """Chat completions with ``tools``, the OpenAI shape. A result goes back as a string
    under the call's id, and is cut to ``RESULT_CHARS`` first: the hosted Llama's
    allowance is counted in tokens a minute, and one uncut read of the book can be most
    of a minute's worth."""

    provider = "groq"
    RESULT_CHARS = 14_000

    def __init__(self, system, tools, max_tokens=2048, post=None, model=None):
        super().__init__(system, tools, max_tokens, post)
        self.model = model or GROQ_MODEL
        self.messages: list = [{"role": "system", "content": system}]

    def user(self, text):
        self.messages.append({"role": "user", "content": text})

    def assistant(self, text):
        self.messages.append({"role": "assistant", "content": text})

    def body(self, final: bool = False) -> dict:
        body = {"model": self.model, "messages": self.messages,
                "max_tokens": self.max_tokens, "temperature": 0.2}
        if self.tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t["description"],
                "parameters": t["input_schema"]}} for t in self.tools]
            body["tool_choice"] = "none" if final else "auto"
        return body

    def read(self, payload: dict) -> dict:
        choices = payload.get("choices") or []
        if not choices:
            raise ValueError(f"groq returned nothing: {str(payload)[:120]}")
        message = choices[0].get("message") or {}
        kept = {"role": "assistant", "content": message.get("content") or ""}
        calls = []
        if message.get("tool_calls"):
            kept["tool_calls"] = message["tool_calls"]
            for call in message["tool_calls"]:
                function = call.get("function") or {}
                try:
                    args = json.loads(function.get("arguments") or "{}")
                except ValueError:
                    # Arguments that are not JSON are passed on as they came, so the tool
                    # refuses them by name and the model sees what it sent.
                    args = {"unparsed_arguments": function.get("arguments")}
                calls.append({"id": call.get("id"), "name": function.get("name"),
                              "args": args if isinstance(args, dict) else {}})
        self.messages.append(kept)
        return {"text": (message.get("content") or "").strip(), "calls": calls}

    def step(self, final=False):
        key = os.getenv("GROQ_API_KEY", "").strip()
        return self.read(_retrying(lambda: self._post(
            "groq", GROQ_URL, {"Authorization": f"Bearer {key}"}, self.body(final),
            CHAT_TIMEOUT_S)))

    def results(self, results):
        for result in results:
            content = result["content"]
            text = content if isinstance(content, str) else json.dumps(content, default=str)
            if len(text) > self.RESULT_CHARS:
                text = text[:self.RESULT_CHARS] + " [cut to fit this model's allowance]"
            self.messages.append({"role": "tool", "tool_call_id": result.get("id"),
                                  "name": result["name"], "content": text})


class AnthropicConversation(Conversation):
    """The Messages API with ``tools``, through the SDK the note path already uses. Not
    exercised against the live API when it was written: no Anthropic key was configured
    on the machine, so the tests pin the shapes against a stand-in client."""

    provider = "anthropic"

    def __init__(self, system, tools, max_tokens=2048, post=None, model=None, client=None):
        super().__init__(system, tools, max_tokens, post)
        self.model = model or ANTHROPIC_MODEL
        self.messages: list = []
        self._client = client

    def user(self, text):
        self.messages.append({"role": "user", "content": text})

    def assistant(self, text):
        self.messages.append({"role": "assistant", "content": text})

    def step(self, final=False):
        if self._client is None:
            import anthropic  # lazy, so the app runs without the SDK
            self._client = anthropic.Anthropic()
        kwargs = {"model": self.model, "max_tokens": self.max_tokens, "system": self.system,
                  "messages": list(self.messages)}
        if self.tools:
            kwargs["tools"] = [{"name": t["name"], "description": t["description"],
                                "input_schema": t["input_schema"]} for t in self.tools]
            if final:
                kwargs["tool_choice"] = {"type": "none"}
        message = _retrying(lambda: self._client.messages.create(**kwargs))
        blocks = list(getattr(message, "content", None) or [])
        self.messages.append({"role": "assistant", "content": blocks})
        calls = [{"id": getattr(b, "id", None), "name": getattr(b, "name", None),
                  "args": getattr(b, "input", None) or {}}
                 for b in blocks if getattr(b, "type", "") == "tool_use"]
        text = "\n".join(getattr(b, "text", "") for b in blocks
                         if getattr(b, "type", "") == "text").strip()
        return {"text": text, "calls": calls}

    def results(self, results):
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": r.get("id"),
             "content": (r["content"] if isinstance(r["content"], str)
                         else json.dumps(r["content"], default=str)),
             "is_error": bool(r.get("is_error"))} for r in results]})


_CONVERSATIONS = {"gemini": GeminiConversation, "groq": GroqConversation,
                  "anthropic": AnthropicConversation}


def conversation(system: str, tools: list, prefer: str | None = None,
                 max_tokens: int = 2048) -> Conversation:
    """A tool-using conversation on whichever provider has a key, ``prefer`` first.
    Raises where none is configured, as ``complete`` does."""
    active = provider(prefer)
    if active is None:
        raise RuntimeError("no model provider configured "
                           "(set GROQ_API_KEY, GEMINI_API_KEY or ANTHROPIC_API_KEY)")
    return _CONVERSATIONS[active](system, tools, max_tokens)
