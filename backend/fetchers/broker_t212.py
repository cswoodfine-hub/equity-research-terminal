"""The user's own Trading 212 account, read only: account summary, positions and history.

A source that needs a login (CLAUDE.md): the key lives in ``.env`` as ``T212_API_KEY``, with
``T212_API_SECRET`` beside it for a key issued with a secret and ``T212_ENV`` set to
``live`` or ``demo``. It is never written to the database, a log or a message, and a
rejected or expired key is a soft error, never a crash. Every view built on it says the
figures are from the user's own account.

Only GET endpoints are called. This module has no route that places, changes or cancels an
order, and none is to be added: trading stays with the account holder.

Authentication (docs.trading212.com/api): HTTP Basic with the key as the user and the
secret as the password; a key issued without a secret (the older single-key form) is sent
on its own in the ``Authorization`` header. Rate limits are per account: the account
summary once every 5 seconds, positions once a second, history 20 a minute.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

import env  # noqa: F401  load .env before the key is read

BASES = {"live": "https://live.trading212.com/api/v0",
         "demo": "https://demo.trading212.com/api/v0"}
_TIMEOUT_S = 30
_USER_AGENT = "NovatalisResearch/0.1"


def configured() -> bool:
    return bool(os.getenv("T212_API_KEY", "").strip())


def _base() -> str:
    return BASES.get(os.getenv("T212_ENV", "live").strip().lower(), BASES["live"])


def _auth() -> str:
    key = os.getenv("T212_API_KEY", "").strip()
    secret = os.getenv("T212_API_SECRET", "").strip()
    if secret:
        return "Basic " + base64.b64encode(f"{key}:{secret}".encode()).decode()
    return key                                  # the older single-key form


def get(path: str):
    """GET one endpoint; (status, parsed body or None). Never raises on HTTP errors."""
    request = urllib.request.Request(_base() + path, headers={
        "Authorization": _auth(), "Accept": "application/json", "User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, {"error": type(exc).__name__}


def check() -> dict:
    """Whether the key reaches the account: the status and the summary's field names only,
    so a check never prints a balance or a credential."""
    if not configured():
        return {"ok": False, "reason": "no T212_API_KEY in .env"}
    status, body = get("/equity/account/summary")
    reasons = {401: "key rejected (wrong key, missing secret, or deleted)",
               403: "key lacks the account-data permission, or the IP is not allowed",
               429: "rate limited, try again in a few seconds"}
    return {"ok": status == 200, "status": status,
            "env": os.getenv("T212_ENV", "live").strip().lower() or "live",
            "auth": "key and secret" if os.getenv("T212_API_SECRET", "").strip()
            else "key only",
            "reason": None if status == 200 else reasons.get(status, "no answer"),
            "fields": sorted(body.keys()) if status == 200 and isinstance(body, dict)
            else None}


def universe_ticker(t212_ticker: str) -> str:
    """The listing's root as the book names companies: ``NVO_US_EQ`` is NVO, and a London
    listing carries a lower-case ``l`` (``AZNl_EQ``), which is dropped."""
    root = (t212_ticker or "").split("_")[0]
    return root[:-1] if root.endswith("l") and root[:-1].isupper() else root


def positions() -> dict:
    """The open positions, read live: {"ok", "status", "currency", "rows"}. Each row: the
    Trading 212 ticker, the book's ticker it maps to, name, ISIN, quantity, average price
    paid and current price in the instrument's currency, and value, cost, unrealised
    profit and FX effect in the account's currency."""
    if not configured():
        return {"ok": False, "reason": "no T212_API_KEY in .env", "rows": []}
    status, body = get("/equity/positions")
    if status != 200 or not isinstance(body, list):
        return {"ok": False, "status": status, "rows": []}
    rows = []
    for p in body:
        inst, wallet = p.get("instrument") or {}, p.get("walletImpact") or {}
        rows.append({
            "t212_ticker": inst.get("ticker"), "ticker": universe_ticker(inst.get("ticker")),
            "name": inst.get("name"), "isin": inst.get("isin"),
            "currency": inst.get("currency"), "quantity": p.get("quantity"),
            "average_price": p.get("averagePricePaid"), "current_price": p.get("currentPrice"),
            "opened": p.get("createdAt"), "value": wallet.get("currentValue"),
            "cost": wallet.get("totalCost"), "unrealised": wallet.get("unrealizedProfitLoss"),
            "fx_effect": wallet.get("fxImpact"), "account_currency": wallet.get("currency")})
    return {"ok": True, "status": status, "rows": rows,
            "currency": next((r["account_currency"] for r in rows if r["account_currency"]),
                             None)}
