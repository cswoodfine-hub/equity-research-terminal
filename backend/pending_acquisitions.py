"""An acquisition agreed and not completed, stated wherever the asset is valued.

The book holds Palsonify in Vertex's valuation, and on 2026-11-16 Vertex did not own it:
its 8-K of 2026-07-07 is an Item 1.01, the merger agreement, and no Item 2.01, the
completion, has been filed. Keeping the product in the acquirer's book anyway is a
deliberate choice, and this module exists so that the choice is visible on the page
rather than passing as ownership: the asset's forecast note and the company's both say
the deal is pending, on what terms, and that the price the acquirer has agreed to pay
is not in the valuation beside the asset it is buying.

``data/pending_acquisitions.csv`` holds the deals. A row comes out when the Item 2.01 is
filed, and keying by the acquirer's ticker and the asset's name means it survives the
database being rebuilt.
"""

from __future__ import annotations

import csv
import pathlib

import db

DATA = db.BACKEND_DIR.parent / "data" / "pending_acquisitions.csv"
FIELDS = ("acquirer", "asset", "target", "announced", "terms", "basis")


def rows(path=None) -> list[dict]:
    """The register's rows, comment lines skipped. A missing file is an empty register."""
    source = pathlib.Path(path) if path else DATA
    if not source.exists():
        return []
    with source.open(newline="", encoding="utf-8") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#")]
    return [{k: (r.get(k) or "").strip() for k in FIELDS}
            for r in csv.DictReader(lines)
            if (r.get("acquirer") or "").strip() and (r.get("asset") or "").strip()]


def for_company(ticker: str, path=None) -> list[dict]:
    return [r for r in rows(path) if r["acquirer"].upper() == (ticker or "").upper()]


def for_asset(ticker: str, asset_name: str | None, path=None) -> dict | None:
    name = (asset_name or "").strip().lower()
    return next((r for r in for_company(ticker, path)
                 if name and r["asset"].strip().lower() == name), None)


def sentence(entry: dict, acquirer_name: str | None = None) -> str:
    """The one sentence both notes carry, so the asset page and the company page cannot
    describe the same deal two ways."""
    who = acquirer_name or entry["acquirer"]
    return (f"{entry['asset']} is held in {who}'s book, but {who} has not completed its "
            f"acquisition of {entry['target']}: the deal was agreed on "
            f"{entry['announced']} for {entry['terms']}, and no completion has been "
            f"filed. Until it is, the valuation counts an asset {who} does not yet own "
            f"and leaves out the price it has agreed to pay for it.")


_FORMS = {"inc", "incorporated", "corp", "corporation", "co", "company", "plc", "ag",
          "sa", "se", "nv", "ltd", "limited", "llc", "holdings", "group", "and"}
_TRADES = {"pharmaceuticals", "pharmaceutical", "therapeutics", "biosciences",
           "biotherapeutics", "pharma"}


def short_name(name: str | None) -> str | None:
    """A company as a sentence names it: "Vertex Pharmaceuticals Inc" reads "Vertex"."""
    words = (name or "").replace(",", " ").split()
    while words and words[-1].lower().strip(".") in _FORMS:
        words.pop()
    if len(words) > 1 and words[-1].lower() in _TRADES:
        words.pop()
    return " ".join(words) or name


def _company_name(ticker: str) -> str | None:
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT name FROM companies WHERE ticker = ?",
                           (ticker.upper(),)).fetchone()
        return short_name(row["name"]) if row else None
    finally:
        conn.close()


def lines_for_company(ticker: str, path=None) -> list[str]:
    """The sentences a company's note carries, one per pending deal."""
    entries = for_company(ticker, path)
    if not entries:
        return []
    who = _company_name(ticker)
    return [sentence(e, who) for e in entries]


def lines_for_asset(ticker: str, asset_name: str | None, path=None) -> list[str]:
    entry = for_asset(ticker, asset_name, path)
    return [sentence(entry, _company_name(ticker))] if entry else []
