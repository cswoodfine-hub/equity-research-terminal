"""The acquisition ledger: what a company paid for each company it bought, from its own
filings, kept in the repo so a rebuilt book carries it.

The deals table learns of an acquisition from a headline or from the 8-K that announces
it, and ``deals.enrich`` reads the terms out of the press release furnished with the
8-K. Lilly furnishes none: its acquisitions appear in the business development bullet of
an earnings release and, with their figures, in the 10-Q's acquisitions note, which the
filing-text fetcher does not store and no reader parses. On 2026-11-27 the book held 22
Lilly acquisition rows since 2025 across thirteen targets, several of them twice (once
from a headline, once from a filing), none with the terms the 10-Q states, and nine with
a figure read off the earnings release that belonged to Boehringer Ingelheim's Jardiance
milestone. A row corrected in the table would have gone at the next rebuild.

``data/acquisitions.csv`` is the record. One row per target, written from the acquirer's
10-Q or 10-K where it states the consideration (a business combination's cash paid net
of cash acquired and the maximum contingent consideration; an asset acquisition's
acquired IPR&D charge), and from the acquirer's or the target's announcement where the
filing has not caught up. Every row cites its source and quotes it.

``load`` writes each row into ``deals`` as a curated acquisition and folds the headline
and filing rows for the same target within ``FOLD_DAYS`` of it into that one row, so the
table says each deal once and says it with its terms. A curated row the file no longer
holds is left alone: the file adds to the book's knowledge and does not take it away.

What the columns mean, because a single "value" would be wrong whichever it picked:

  upfront_musd      cash paid at closing, net of cash acquired, where the filing gives
                    it; for an asset acquisition the acquired IPR&D charge, which is what
                    was paid for the compound
  contingent_musd   the maximum of the milestones, earn-outs or contingent value rights
                    still to pay, as the filing states it
  total_musd        upfront plus contingent where both are known, else the "up to"
                    figure the announcement stated
  announced_value   the words of the announcement, kept verbatim ("up to $2.5 billion")
  sponsor_names     the names the target registers its studies under where they are not
                    the target's own, pipe-separated: AtaiBeckley's are under "Beckley
                    Psytech Limited" and Ventyx's under "Zomagen Biosciences Ltd.", and
                    the trial fetch keeps an acquired sponsor's study only where the
                    registry's lead sponsor begins with a name it was given

A figure the filer has not stated is left empty, never estimated.

A row whose ``status`` is ``not an acquisition`` is the other kind of correction. The
headline parser read an option, a licence, a rumour, a voucher, a property, an analyst's
buy rating or another company's deal as this company's acquisition, and the row names
the party the table holds, says in ``note`` what it actually was, and ``load`` removes the
headline rows for it and writes nothing. The parser has since been taught each shape
(fetchers/deals_news.py), so the row is the record of the misread and the guard against
an old feed item coming back.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
import re

import db
import deal_terms

DATA = db.BACKEND_DIR.parent / "data" / "acquisitions.csv"
FIELDS = ("ticker", "target", "asset", "event_date", "status", "accounting",
          "upfront_musd", "contingent_musd", "total_musd", "announced_value",
          "phase", "sponsor_names", "source", "quote", "note")
# How far from the ledger's date a headline or filing row for the same target may sit
# and still be the same deal. Lilly's Centessa deal was agreed on 2026-03-31, recapped
# in the Q1 release on 2026-04-30 and completed on 2026-06-24: three rows, one deal.
FOLD_DAYS = 200
NOT_AN_ACQUISITION = "not an acquisition"
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def rows(path=None) -> list[dict]:
    """The register's rows, comment lines skipped."""
    source = pathlib.Path(path) if path else DATA
    if not source.exists():
        return []
    with source.open(newline="", encoding="utf-8") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#")]
    out = []
    for r in csv.DictReader(lines):
        row = {k: (r.get(k) or "").strip() for k in FIELDS}
        if row["ticker"] and row["target"] and row["event_date"]:
            out.append(row)
    return out


def _musd(value: str) -> float | None:
    """A column in millions as dollars, or None where the file leaves it empty."""
    value = (value or "").strip().replace(",", "")
    return float(value) * 1e6 if value else None


def same_target(a: str, b: str) -> bool:
    """Whether two party strings name the same company: every own word of the shorter
    name is in the longer. "Centessa Pharmaceuticals plc." and "Centessa" agree;
    "Atai-Beckley" and "AtaiBeckley" agree once hyphens are dropped."""
    wa = deal_terms.party_words(a.replace("-", ""))
    wb = deal_terms.party_words(b.replace("-", ""))
    if not wa or not wb:
        return False
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return all(w in long_ for w in short)


def _within(a: str, b: str, days: int) -> bool:
    try:
        return abs((dt.date.fromisoformat(a[:10]) - dt.date.fromisoformat(b[:10])).days) <= days
    except (TypeError, ValueError):
        return False


def load(conn, path=None) -> dict:
    """Write the register into ``deals``.
    {"written", "updated", "folded", "removed", "skipped"}."""
    out = {"written": 0, "updated": 0, "folded": 0, "removed": 0, "skipped": []}
    for r in rows(path):
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                               (r["ticker"].upper(),)).fetchone()
        if company is None:
            out["skipped"].append(f"{r['ticker']} {r['target']}: no such company")
            continue
        cid = company["id"]
        if r["status"].lower() == NOT_AN_ACQUISITION:
            # The headline rows for a party that was never bought go; a curated row
            # is an analyst's and stays.
            for x in conn.execute(
                    "SELECT id, counterparty, event_date FROM deals"
                    " WHERE company_id = ? AND deal_type = 'acquisition'"
                    "   AND counterparty IS NOT NULL AND is_curated = 0", (cid,)):
                if (same_target(x["counterparty"], r["target"])
                        and _within(x["event_date"] or "", r["event_date"], FOLD_DAYS)):
                    conn.execute("DELETE FROM deals WHERE id = ?", (x["id"],))
                    out["removed"] += 1
            continue
        upfront, contingent, total = (_musd(r["upfront_musd"]), _musd(r["contingent_musd"]),
                                      _musd(r["total_musd"]))
        if total is None and upfront is not None and contingent is not None:
            total = upfront + contingent
        headline = total or ((upfront or 0) + (contingent or 0)) or None
        accession = r["source"] if _ACCESSION.match(r["source"]) else None
        url = r["source"] if r["source"].startswith("http") else None
        area = r["asset"] or None
        quote = r["quote"] or f"{r['ticker']} acquisition of {r['target']}"
        existing = [dict(x) for x in conn.execute(
            "SELECT id, is_curated, event_date, counterparty, article_url, source_url"
            "  FROM deals WHERE company_id = ? AND deal_type = 'acquisition'"
            "    AND counterparty IS NOT NULL", (cid,))
            if same_target(x["counterparty"], r["target"])
            and _within(x["event_date"] or "", r["event_date"], FOLD_DAYS)]
        curated = [x for x in existing if x["is_curated"]]
        others = [x for x in existing if not x["is_curated"]]
        # The headline's link is worth keeping on the curated row: it is how a reader
        # finds the wire story the book first saw.
        article = next((x["article_url"] for x in others if x["article_url"]), None)
        values = (r["event_date"], area, quote, url, r["announced_value"] or None,
                  "filing" if accession else ("news" if r["announced_value"] else None),
                  "filing" if accession else "news",
                  upfront, contingent, total, headline, r["quote"] or None,
                  r["source"] or None, accession, r["note"] or None)
        if curated:
            keep = curated[0]
            conn.execute(
                "UPDATE deals SET event_date = ?, area = ?, quote = ?, source_url = ?,"
                "  announced_value = ?, announced_value_source = ?, event_date_source = ?,"
                "  upfront_usd = ?, milestones_usd = ?, total_usd = ?, headline_usd = ?,"
                "  terms_evidence = ?, terms_source = ?, accession = ?, rationale = ?,"
                "  counterparty = ?, article_url = COALESCE(article_url, ?)"
                " WHERE id = ?", values + (r["target"], article, keep["id"]))
            out["updated"] += 1
            for extra in curated[1:]:
                conn.execute("DELETE FROM deals WHERE id = ?", (extra["id"],))
                out["folded"] += 1
        else:
            conn.execute(
                "INSERT INTO deals (company_id, deal_type, is_curated, event_date, area,"
                "  quote, source_url, announced_value, announced_value_source,"
                "  event_date_source, upfront_usd, milestones_usd, total_usd, headline_usd,"
                "  terms_evidence, terms_source, accession, rationale, counterparty,"
                "  article_url)"
                " VALUES (?, 'acquisition', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                "  ?, ?)", (cid,) + values + (r["target"], article))
            out["written"] += 1
        for other in others:
            conn.execute("DELETE FROM deals WHERE id = ?", (other["id"],))
            out["folded"] += 1
    conn.commit()
    return out


def sponsor_names(ticker: str, path=None) -> list[str]:
    """The registry names of this company's targets that differ from the targets' own,
    for ``acquired_sponsors.for_company``."""
    out: list[str] = []
    for r in rows(path):
        if r["ticker"].upper() != (ticker or "").upper():
            continue
        out.extend(n.strip() for n in r["sponsor_names"].split("|") if n.strip())
    return out


def without_terms(conn, ticker: str | None = None, within_days: int = 1825,
                  today=None) -> list[dict]:
    """Acquisition rows that carry no terms: no figure parsed, none curated. The read
    the run's health summary reports, so a bought company with no ledger row is named."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=within_days)).isoformat()
    query = """SELECT c.ticker, d.counterparty, d.event_date, d.announced_value
                 FROM deals d JOIN companies c ON c.id = d.company_id
                WHERE d.deal_type = 'acquisition' AND d.counterparty IS NOT NULL
                  AND d.headline_usd IS NULL AND COALESCE(d.event_date, '') >= ?"""
    params: list = [cutoff]
    if ticker:
        query += " AND c.ticker = ?"
        params.append(ticker.upper())
    return [dict(r) for r in conn.execute(query + " ORDER BY c.ticker, d.event_date",
                                          params)]
