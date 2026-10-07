"""The guided input step for new revenue: a closed acquisition, drafted into forecast rows
for an analyst to approve, so nothing reaches a valuation without a source.

The model holds what the book was seeded with. When a deal closes, the acquirer's revenue
changes and the model does not, until someone writes the rows. This drafts them from free,
filed sources and queues them:

1. Detection (``detect``). A closing is read only from the acquirer's own filings
   (``closings.py``), never from the headline deals table. Every filing read is recorded in
   ``closing_reads`` and every closing in ``deal_closings``, one per company and target, so
   a filing is read once and a closing drafted once. A one-off catch-up
   (``catch_up``, or ``python input_drafts.py --catch-up``) reads every unread filing when
   this goes live; each refresh after it reads only filings dated on or after the
   company's newest read, with 40 fetches a run as a safety cap.
2. Drafting (``draft``). The target's products are the book's assets its own registered
   trials map to, and the ones its projections name. A public target has filed revenue
   (its company facts) and usually management's projections (its merger proxy or 14D-9),
   which become a base, a peak and the growth between them in the engine's marketed mode.
   A private target has neither, and the draft says so rather than guess. The cash paid
   becomes a pending claim on equity until a filed balance sheet carries the deal.

   Where a filing prints several projection cases, one is taken by a stated rule
   (``closings.choose_case``): the case the target's board and financial advisers relied
   on for the fairness opinion; failing that, management's base case over an upside or a
   downside case; failing that, the most recent. Each drafted row's note names the case,
   the reason and the filing's own caption.

   Risk is applied once, and it belongs to the product. An unadjusted forecast is drafted
   as it is and the engine applies the probability for the product's stage; where the
   filing prints only a risk-adjusted forecast, it is drafted with a probability of 1 and
   a note that the target's own adjustment is inside it. A product in development takes
   the unadjusted case where one is printed. Its probability is its own whoever bought it
   (``pos_granular.acquired``).

   A product the book does not hold is named by the target's approved label (openFDA),
   and accepting its first row adds it under the buyer, in the book and in
   ``data/marketed_additions.csv``, so there is no separate step to add it.
3. Review (``queue``, ``decide``). A row is accepted as drafted, edited then accepted, or
   rejected. Acceptance writes the row to the book (``assumptions.save`` or
   ``other_claims``) and to its seed file under data/, because the seeds bootstrap and never
   overwrite: a value only in the book is lost on a rebuild, and one only in the file never
   reaches a book that already holds the key.

Every drafted row carries its source, the sentence or cells it came from, and a grade. A
row whose mapping to one product is not one-to-one, or whose source is missing, is drafted
``incomplete`` and cannot be accepted until it is edited.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import pathlib
import re

import assumptions as assumptions_module
import closings
import db

SINCE = "2025-01-01"
READS_PER_RUN = 40
DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
SEED_DIR = DATA_DIR / "assumptions"
CLAIMS_PATH = DATA_DIR / "other_claims.csv"
ADDITIONS_PATH = DATA_DIR / "marketed_additions.csv"
ADDITIONS_HEADER = ["ticker", "brand", "generic", "internal_code", "modality",
                    "licensed_on", "source"]

_PERIODIC_SECTIONS = ("mdna", "financial_review")
_TRIGGER_KIND = {"10-Q": "10-Q", "10-K": "10-K", "20-F": "20-F", "6-K": "6-K"}
# The company-wide rows a new product takes from the acquirer's own seeds: the filed cost
# ratios, the discount rate legs and the forecast window. Same company, same numbers,
# graded as borrowed because they were struck for another product.
SIBLING_KEYS = ("cogs_pct", "sga_pct", "rd_pct", "other_costs_pct", "tax_rate",
                "risk_free", "erp", "beta", "cost_of_debt", "debt_weight",
                "forecast_start_year", "forecast_years")
EDITABLE = ("asset_id", "key", "value", "text_value", "unit", "year", "source", "quote",
            "note", "evidence", "region", "scenario")


# --- detection ---------------------------------------------------------------------

def _names(conn) -> dict:
    return {r["id"]: closings.aliases(r["name"], r["ticker"])
            for r in conn.execute("SELECT id, ticker, name FROM companies")}


def _stored(conn, accession: str, sections=None) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT section, text FROM filing_sections WHERE accession = ? ORDER BY section",
        (accession,)).fetchall()
    return [(r["section"], r["text"]) for r in rows
            if r["text"] and (sections is None or r["section"] in sections)]


def _candidates(conn, since: str) -> list[dict]:
    current = conn.execute(
        """SELECT f.company_id, f.form_type, f.filed_date, f.accession, f.title, f.url
             FROM filings f LEFT JOIN closing_reads r ON r.accession = f.accession
            WHERE r.accession IS NULL AND f.filed_date >= ?
              AND (f.form_type = '6-K'
                   OR (f.form_type = '8-K'
                       AND (f.title LIKE '%Acquisition or disposition completed%'
                            OR ((f.title LIKE '%Regulation FD disclosure%'
                                 OR f.title LIKE '%Other events%')
                                AND f.title NOT LIKE '%Results of operations%'))))""",
        (since,)).fetchall()
    periodic = conn.execute(
        """SELECT DISTINCT s.company_id, s.form_type, s.filed_date, s.accession,
                  s.form_type AS title, f.url
             FROM filing_sections s LEFT JOIN closing_reads r ON r.accession = s.accession
             LEFT JOIN filings f ON f.accession = s.accession
            WHERE r.accession IS NULL AND s.filed_date >= ?
              AND s.form_type IN ('10-Q', '10-K', '20-F')
              AND s.section IN ('mdna', 'financial_review')""", (since,)).fetchall()
    rows = [dict(r) for r in current] + [dict(r) for r in periodic]
    return sorted(rows, key=lambda r: (r["filed_date"] or "", r["accession"]))


def _kind(row: dict) -> str:
    if row["form_type"] == "8-K":
        return ("8-K item 2.01" if "Acquisition or disposition completed" in (row["title"] or "")
                else "8-K press release")
    return _TRIGGER_KIND.get(row["form_type"], row["form_type"])


def _record_read(conn, row: dict, verdict: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO closing_reads (accession, company_id, form_type, filed_date,"
        " verdict) VALUES (?, ?, ?, ?, ?)",
        (row["accession"], row["company_id"], row["form_type"], row["filed_date"], verdict))


def _stream(form_type: str) -> str:
    return "periodic" if form_type in ("10-Q", "10-K", "20-F") else "current"


def _floors(conn) -> dict:
    """{(company_id, stream): the newest filing date read}. Current reports and periodic
    reports keep separate floors, since a periodic report's text is stored later than the
    current reports filed after it."""
    out: dict = {}
    for r in conn.execute("SELECT company_id, form_type, MAX(filed_date) AS newest"
                          " FROM closing_reads GROUP BY company_id, form_type"):
        key = (r["company_id"], _stream(r["form_type"]))
        if r["newest"] and (key not in out or r["newest"] > out[key]):
            out[key] = r["newest"]
    return out


def _existing_closing(conn, company_id: int, target: str):
    for found in conn.execute("SELECT * FROM deal_closings WHERE company_id = ?",
                              (company_id,)):
        if closings.same_target(found["target"], target):
            return found
    return None


def detect(conn, edgar=None, since: str = SINCE, limit: int | None = READS_PER_RUN,
           catch_up: bool = False) -> dict:
    """Read candidate filings for a completed acquisition.

    The one-off catch-up (``catch_up``) reads every unread candidate since ``since``, with
    no cap, so the queue starts complete. A refresh then reads only the filings dated on
    or after the company's newest read, fetching at most ``limit`` current reports a run
    as a safety cap. Text already stored by the filing text fetcher is read in place. A
    filing left unread, for the cap, a failed fetch or no EDGAR client, is not recorded,
    and the company's later filings wait with it, so the floor never passes a filing that
    was not read. Returns counts and the new closings.
    """
    names = _names(conn)
    floors = {} if catch_up else _floors(conn)
    cap = None if catch_up else limit
    fetched, new, errors, verdicts, held = 0, [], [], {}, set()
    for row in _candidates(conn, since):
        stream = (row["company_id"], _stream(row["form_type"]))
        if stream in held or (row["filed_date"] or "") < floors.get(stream, ""):
            continue
        periodic = row["form_type"] in ("10-Q", "10-K", "20-F")
        texts = _stored(conn, row["accession"], _PERIODIC_SECTIONS if periodic else None)
        if not texts and periodic:
            continue
        if not texts:
            if (edgar is None or not row.get("url")
                    or (cap is not None and fetched >= cap)):
                held.add(stream)
                continue
            try:
                texts = edgar.current_report(row["url"])
                fetched += 1
            except Exception as exc:          # a transient failure is retried next run
                errors.append(f"{row['accession']}: {exc}")
                held.add(stream)
                continue
        kind = _kind(row)
        found, sale = [], False
        for section, text in texts:
            result = closings.find_closings(
                text, names.get(row["company_id"], set()),
                lead_only=kind in ("8-K press release", "6-K"),
                item_201=kind == "8-K item 2.01" and section == "body")
            sale = sale or (result["disposition"] and kind == "8-K item 2.01")
            for acquisition in result["acquisitions"]:
                if not any(closings.same_target(a["target"], acquisition["target"])
                           for a, _t in found):
                    found.append((acquisition, text))
        kept = []
        for acquisition, text in found:
            date = acquisition["closing_date"]
            if periodic and not date:
                continue                       # a 10-K's undated mention is history
            date = date or row["filed_date"]
            if date < since[:len(date)]:
                continue
            kept.append(({**acquisition, "closing_date": date}, text))
        verdict = "acquisition" if kept else ("disposition" if sale else "none")
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        _record_read(conn, row, verdict)
        for acquisition, text in kept:
            if _existing_closing(conn, row["company_id"], acquisition["target"]):
                continue
            paid = closings.consideration(text, acquisition["target"])
            context = {"consideration": {**paid, "accession": row["accession"],
                                         "form": row["form_type"]}}
            cursor = conn.execute(
                """INSERT INTO deal_closings (company_id, target, target_key, closing_date,
                       trigger_accession, trigger_kind, trigger_url, quote, context)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (row["company_id"], acquisition["target"],
                 closings.target_key(acquisition["target"]), acquisition["closing_date"],
                 row["accession"], kind, row.get("url"), acquisition["quote"],
                 json.dumps(context)))
            new.append({"id": cursor.lastrowid, "company_id": row["company_id"],
                        "target": acquisition["target"],
                        "closing_date": acquisition["closing_date"], "kind": kind,
                        "accession": row["accession"]})
    conn.commit()
    return {"fetched": fetched, "verdicts": verdicts, "closings": new, "errors": errors}


# --- drafting ----------------------------------------------------------------------

# First words of a descriptive asset name that are ordinary English, not a drug's name:
# "Candidate UTI vaccine low dose formulation 1" is not named by a filing that says
# "candidate".
_COMMON_FIRST = {"candidate", "vaccine", "compound", "programme", "program", "product",
                 "therapy", "investigational", "antibody", "molecule", "undisclosed",
                 "unnamed", "novel", "oral", "injectable", "combination"}


def _named(asset, text: str) -> bool:
    """Whether a filing's text names the asset, by brand or by its ingredient's first
    word. Short names are left out, since four letters match too much, and so is a first
    word that is ordinary English."""
    text = (text or "").lower()
    first = (asset["generic_name"] or "").split(" ")[0]
    names = [asset["brand_name"], None if first.lower() in _COMMON_FIRST else first]
    return any(n and len(n) >= 5 and re.search(rf"(?<![\w-]){re.escape(n.lower())}(?![\w-])",
                                               text) for n in names)


def _linked_assets(conn, company_id: int, target: str, texts: list[str]) -> list[dict]:
    """The acquirer's assets the target's own registered trials map to, and the ones a
    filing about the deal names."""
    first = closings.target_key(target).split(" ")[0]
    out: dict = {}
    for r in conn.execute(
            """SELECT DISTINCT a.id, a.brand_name, a.generic_name, a.is_marketed, a.modality
                 FROM trials t JOIN assets a ON a.id = t.asset_id
                WHERE a.owner_company_id = ? AND LOWER(t.lead_sponsor) LIKE ?""",
            (company_id, f"{first}%")):
        out[r["id"]] = {**dict(r), "linked_by": "the target's registered trials"}
    joined = " ".join(texts)
    for r in conn.execute(
            """SELECT id, brand_name, generic_name, is_marketed, modality FROM assets
                WHERE owner_company_id = ?""",
            (company_id,)) if joined else []:
        if r["id"] not in out and _named(r, joined):
            out[r["id"]] = {**dict(r), "linked_by": "named in the filing"}
    for asset in out.values():
        asset["named"] = _named(asset, joined)
        rows = assumptions_module.rows(conn, asset["id"], "base")
        asset["modelled_rows"] = len(rows)
        asset["mode"] = next((r["text_value"] for r in rows
                              if r["key"] == "therapy_mode" and r["indication_id"] is None),
                             None)
    return sorted(out.values(), key=lambda a: (-a["is_marketed"], a["id"]))


def _proposed(label: dict, sponsor: str, texts: list[str]) -> dict:
    """A product the book does not hold, as the target's approved label states it."""
    proposed = {"brand": label["brand"], "generic": label.get("generic"),
                "modality": label.get("modality"), "is_marketed": 1,
                "internal_code": label.get("internal_code"),
                "licensed_on": label.get("approval_date"),
                "source": (f"openFDA drugsfda {label.get('application_number')}, sponsor "
                           f"{sponsor}, first approved {label.get('approval_date')}")}
    asset = {"id": None, "brand_name": label["brand"], "generic_name": label.get("generic"),
             "is_marketed": 1, "modality": label.get("modality"),
             "linked_by": "the target's approved label", "modelled_rows": 0, "mode": None,
             "loe": None, "proposed": proposed}
    asset["named"] = _named(asset, " ".join(texts))
    return asset


def _asset_name(asset: dict) -> str:
    return asset.get("brand_name") or asset.get("generic_name") or f"asset {asset['id']}"


def _loe(conn, asset_id: int) -> dict | None:
    try:
        import loe
        found = loe.for_assets(conn, [asset_id], exclude_orphan=True).get(asset_id)
    except Exception:
        return None
    return {"date": found.get("date"), "basis": found.get("basis")} if found else None


def _existing(conn, asset_id: int, key: str, year=None):
    return conn.execute(
        """SELECT value, text_value, source FROM assumptions WHERE asset_id = ?
            AND indication_id IS NULL AND region = 'US' AND scenario = 'base' AND key = ?
            AND IFNULL(year, 0) = IFNULL(?, 0)""", (asset_id, key, year)).fetchone()


def _sibling(conn, company_id: int, modality: str | None, exclude: int):
    """The acquirer's most fully seeded marketed product, the same modality first."""
    return conn.execute(
        """SELECT a.id, a.brand_name, a.generic_name, COUNT(s.id) n
             FROM assets a JOIN assumptions s ON s.asset_id = a.id AND s.scenario = 'base'
            WHERE a.owner_company_id = ? AND a.id != IFNULL(?, -1) AND a.is_marketed = 1
              AND EXISTS (SELECT 1 FROM assumptions m WHERE m.asset_id = a.id
                          AND m.key = 'therapy_mode' AND m.text_value = 'marketed')
            GROUP BY a.id
            ORDER BY (a.modality IS ?) DESC, n DESC, a.id LIMIT 1""",
        (company_id, exclude, modality)).fetchone()


def _balance_date(conn, company_id: int) -> str | None:
    row = conn.execute(
        "SELECT MAX(period_end) FROM financials WHERE company_id = ?"
        " AND metric = 'CashAndEquivalents'", (company_id,)).fetchone()
    return row[0] if row else None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def _money(value: float) -> str:
    return f"{value:,.0f}"


def _consideration(conn, closing, context: dict) -> dict:
    """The cash paid as a filing states it: the trigger first, then any later report of
    the acquirer's stored in the book that names the target."""
    paid = context.get("consideration") or {}
    if paid.get("cash"):
        return paid
    first = closings.target_key(closing["target"]).split(" ")[0]
    for r in conn.execute(
            """SELECT accession, form_type, text FROM filing_sections
                WHERE company_id = ? AND filed_date >= ? AND LOWER(text) LIKE ?
                ORDER BY filed_date""",
            (closing["company_id"], (closing["closing_date"] or "")[:7], f"%{first}%")):
        found = closings.consideration(r["text"], closing["target"])
        if found.get("cash"):
            return {**found, "accession": r["accession"], "form": r["form_type"],
                    "cvr_quote": paid.get("cvr_quote") or found.get("cvr_quote")}
    return paid


def _risk_sentence(text: str) -> str | None:
    """The filing's own sentence saying its projections are risk-adjusted."""
    for sentence in re.split(r"(?<=[.;])\s+", text or ""):
        if closings._RISK_ADJUSTED.search(sentence) and len(sentence) < 600:
            return sentence.strip()
    return None


def _projection_choice(revenue: dict, linked: list[dict]) -> tuple:
    """(label, asset or None, one_to_one): which revenue row a product takes."""
    for label in revenue:
        for asset in linked:
            if _named(asset, label):
                return label, asset, True
    total = next((l for l in revenue if re.search(r"(?i)total|net revenue|^revenue", l)),
                 next(iter(revenue), None))
    named = [a for a in linked if a.get("named")]
    if not named and len(linked) == 1:
        return total, linked[0], True
    marketed = [a for a in (named or linked) if a["is_marketed"]]
    one = len(named) == 1
    lead = named[0] if one else (marketed[0] if marketed else None)
    return total, lead, one


def draft(conn, closing_id: int, edgar=None) -> dict:
    """Draft every row one closing supports. Returns {rows, note}."""
    closing = conn.execute("SELECT * FROM deal_closings WHERE id = ?",
                           (closing_id,)).fetchone()
    if closing is None:
        raise ValueError(f"no closing {closing_id}")
    context = json.loads(closing["context"] or "{}")
    company = conn.execute("SELECT id, ticker FROM companies WHERE id = ?",
                           (closing["company_id"],)).fetchone()
    trigger = (closing["trigger_accession"], closing["trigger_kind"])
    target = closing["target"]
    notes, rows = [], []
    date = closing["closing_date"] or ""

    # Who the target was: a filer of its own, or not.
    filers, proxy_html, proxy, facts = [], None, None, None
    if edgar is not None:
        phrase = re.sub(closings._LEGAL + r"\s*$", "", target).strip()
        year = int(date[:4]) if date[:4].isdigit() else dt.date.today().year
        end = (f"{date}-28" if len(date) == 7 else date) or dt.date.today().isoformat()
        filers = closings.target_filers(
            edgar.search(phrase, start=f"{year - 2}{end[4:]}", end=end), target)
    public = bool(filers)
    if public:
        cik, name = filers[0]["cik"], filers[0]["name"]
        proxies = [f for f in filers if f["root_form"] in ("DEFM14A", "SC 14D9")]
        proxies.sort(key=lambda f: (f["form"].endswith("/A"), f["root_form"] != "DEFM14A",
                                    f["file_date"] or ""))
        proxy = proxies[0] if proxies else None
        if proxy:
            proxy_html = edgar.document(cik, proxy["accession"], proxy["filename"])
        facts = edgar.companyfacts(cik)
    found = closings.projections(proxy_html) if proxy_html else None
    revenue = closings.revenue_rows(found)
    history = closings.annual_revenue(facts, before=(date + "-01")[:10] if date else None)
    texts = [closing["quote"] or ""] + ([found["section_text"]] if found else [])
    linked = _linked_assets(conn, company["id"], target, texts)
    for asset in linked:
        asset["loe"] = _loe(conn, asset["id"])
    if public and not linked and hasattr(edgar, "labels"):
        # The book holds none of the target's products: its approved labels name them,
        # and accepting a row for one adds it to the book under the buyer.
        phrase = re.sub(closings._LEGAL + r"\s*$", "", target).strip()
        try:
            labels = closings.marketed_labels(
                edgar.labels(closings.target_key(target).split(" ")[0].upper()), target)
        except Exception as exc:           # openFDA down is a gap, not a failed draft
            labels, context["labels_error"] = [], str(exc)
        linked = [_proposed(label, phrase, texts) for label in labels]

    blocked: list = []                  # why the rows drafted next cannot stand alone

    def add(destination, key, value=None, text_value=None, unit=None, year=None,
            asset=None, proposed=None, source=None, source_url=None, quote=None,
            grade=None, note=None, complete=True):
        existing = (_existing(conn, asset["id"], key, year)
                    if destination == "assumptions" and asset and asset["id"] else None)
        if existing is not None and (
                (value is not None and existing["value"] is not None
                 and abs(existing["value"] - value) < 1e-9)
                or (text_value is not None and existing["text_value"] == text_value)):
            notes.append(f"{_asset_name(asset)} already carries {key} at the drafted value")
            return
        status = "draft" if complete and source and quote else "incomplete"
        if status == "incomplete":
            why = (blocked[0] if blocked and not complete else
                   "no source or quote was found for it")
            note = f"Incomplete: {why}." + (f" {note}" if note else "")
        rows.append({"destination": destination, "key": key, "value": value,
                     "text_value": text_value, "unit": unit, "year": year,
                     "asset_id": asset["id"] if asset else None,
                     "proposed_asset": (json.dumps(asset["proposed"], sort_keys=True)
                                        if asset and asset.get("proposed") else proposed),
                     "source": source, "source_url": source_url, "quote": quote,
                     "evidence": grade, "note": note, "status": status,
                     "existing_value": existing["value"] if existing else None,
                     "existing_text": existing["text_value"] if existing else None,
                     "existing_source": existing["source"] if existing else None})

    if not public:
        notes.append(f"{target} filed no annual report, merger proxy or 14D-9 with the SEC "
                     "in the two years before the closing, so it is taken as private: no "
                     "free data on its revenue, and no value rows are proposed")
    else:
        proxy_url = None
        from fetchers.closings_edgar import document_url
        if proxy:
            proxy_url = document_url(cik, proxy["accession"], proxy["filename"])
        label, lead, one = _projection_choice(revenue, linked) if revenue else (None, None, False)
        marketed = [a for a in linked if a["is_marketed"]]
        if lead is None and len(marketed) == 1:
            lead, one = marketed[0], len(linked) == 1
        if lead is None and linked:
            notes.append(f"the book links {', '.join(_asset_name(a) for a in linked)} to "
                         f"{target}, none of them a marketed product one filed figure can "
                         "be put on, so no product row is drafted")
        elif lead is None:
            notes.append(f"none of the book's assets under {company['ticker']} links to "
                         f"{target}, so the target's figures are shown and no product row "
                         "is drafted")
        caveat = None
        if lead is not None and not one:
            others = [_asset_name(a) for a in linked if a["id"] != lead["id"]]
            caveat = (f"the filed figure is {name}'s whole business, not {_asset_name(lead)}"
                      f" alone: the book also links {', '.join(others) or 'other programmes'}"
                      " to the target, so it needs splitting before it can be accepted")
            blocked[:] = [caveat]

        # The anchor: the target's last full year, where the acquirer does not report the
        # product itself yet.
        base_year = None
        if lead is not None and history and lead["is_marketed"]:
            last = history[-1]
            reported = conn.execute(
                "SELECT MAX(fiscal_year) FROM asset_revenue WHERE asset_id = ?",
                (lead["id"],)).fetchone()[0]
            held = _existing(conn, lead["id"], "base_revenue")
            if held is not None and reported and reported >= int(date[:4] or 0):
                notes.append(f"{company['ticker']} reports {_asset_name(lead)} itself from "
                             f"FY{date[:4]}, so the book's anchor stands and the target's "
                             "pre-closing revenue is history only")
            else:
                if reported and reported >= int(date[:4] or 0):
                    notes.append(f"{company['ticker']} reports {_asset_name(lead)} from "
                                 f"FY{date[:4]}, a part year, so the anchor drafted is the "
                                 "target's last full year")
                prior = ", ".join(f"FY{h['fiscal_year']} {_money(h['value'] / 1e6)}mm"
                                  for h in history[-4:])
                base_year = last["fiscal_year"]
                add("assumptions", "base_revenue", value=round(last["value"] / 1e6, 3),
                    unit="mm USD", asset=lead,
                    source=(f"{name} 10-K, accession {last['accession']}, XBRL us-gaap:"
                            f"{last['tag']}, year ended {last['end']}"),
                    source_url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json",
                    quote=f"us-gaap:{last['tag']} {int(last['value'])} USD, "
                          f"{last['end']}", grade="filed",
                    note=f"the target's own filed revenue, the year before the closing; "
                         f"history {prior}", complete=caveat is None)
        if lead is not None and label and not lead["is_marketed"]:
            # A product in development takes the unadjusted case where the filing prints
            # one, so the engine's probability for its stage is the only risk applied.
            found = closings.with_case(found, closings.choose_case(found,
                                                                   prefer_unrisked=True))
            revenue = closings.revenue_rows(found)
            label = label if label in revenue else _projection_choice(revenue, [lead])[0]
        if lead is not None and label:
            series = revenue[label]
            years = sorted(series)
            peak_year = max(years, key=lambda y: series[y][0])
            peak, peak_cell = series[peak_year]
            fall = next((y for y in years if y > peak_year
                         and series[y][0] < 0.5 * series[years[years.index(y) - 1]][0]),
                        None)
            context["projection"] = {
                "label": label, "form": proxy["form"], "accession": proxy["accession"],
                "first_year": years[0], "last_year": years[-1], "peak_year": peak_year,
                "peak": peak, "falls_by_half_in": fall,
                "risk_adjusted": found["risk_adjusted"], "caption": found["caption"],
                "stated_unit": found["stated_unit"], "case": found.get("case"),
                "case_reason": found.get("case_reason"),
                "cases": [{"name": c["name"], "risk_adjusted": c["risk_adjusted"],
                           "relied": c["relied"]} for c in found.get("cases") or []],
                "values": {str(y): series[y][0] for y in years}}
            stated = found["stated_unit"]
            # Which case was read and why, with the filing's own words before its table.
            case = (f' Case taken: "{found.get("case") or "the projections"}", '
                    f'{found.get("case_reason") or "the only case the filing prints"}. '
                    f'The filing\'s caption: "{found["caption"][-160:]}".')

            source = (f"{name} {proxy['form']}, accession {proxy['accession']}, management "
                      f"projections")
            risk = (" Management's figures are risk-adjusted." if found["risk_adjusted"]
                    else " Management's figures are not risk-adjusted.") + case
            if one and not _named(lead, label):
                # A whole-company line taken as one product's: say so on the row.
                others = [a for a in linked if a["id"] != lead["id"]]
                why = (f"the only product of the target the book links to "
                       f"{company['ticker']}" if not others else
                       "the one product of the target the filing names")
                whole = (f" The line is {name}'s whole business, taken as "
                         f"{_asset_name(lead)}'s, {why}.")
                risk += whole
                notes.append(whole.strip().rstrip(".").replace("The line", "the projection line"))
            if lead["is_marketed"]:
                # Drafted whatever the row holds: add() drops it where the book already
                # says marketed, and shows the conflict where it says something else.
                add("assumptions", "therapy_mode", text_value="marketed", asset=lead,
                    source="approved and selling: an FDA approval is on file",
                    quote=(f"{_asset_name(lead)} is marketed in the book" if lead["id"]
                           else lead["proposed"]["source"]),
                    grade="convention")
                anchor = next((r["value"] for r in rows if r["key"] == "base_revenue"), None)
                held = _existing(conn, lead["id"], "base_revenue")
                anchor = anchor if anchor is not None else (held["value"] if held else None)
                below = anchor is not None and anchor > peak
                if below:
                    blocked[:] = [blocked[0] if blocked else
                                  f"management's peak of {_money(peak)}mm is below the "
                                  f"{_money(anchor)}mm base the book holds"]
                    notes.append(
                        f"management's peak of {_money(peak)}mm is below the "
                        f"{_money(anchor)}mm base the book holds for {_asset_name(lead)}, so "
                        f"the projection ({label}) is on another basis, a territory or a "
                        "share, and is drafted incomplete")
                add("assumptions", "revenue_ceiling_musd", value=peak, unit="mm USD",
                    asset=lead, source=source, source_url=proxy_url,
                    quote=f"{label}, {peak_year}: {peak_cell} (amounts in {stated})",
                    grade="filed",
                    note=f"management's peak, {peak_year}." + risk +
                         (f" Their revenue falls by more than half in {fall}." if fall
                          else ""), complete=caveat is None and not below)
                start_year, start_value, start_quote = years[0], series[years[0]][0], (
                    f"{label}, {years[0]}: {series[years[0]][1]}")
                rows_by_key = {r["key"]: r for r in rows}
                if base_year and "base_revenue" in rows_by_key:
                    start_year = base_year
                    start_value = rows_by_key["base_revenue"]["value"]
                    start_quote = rows_by_key["base_revenue"]["quote"]
                if start_value and start_value > 0 and peak_year > start_year:
                    growth = (peak / start_value) ** (1 / (peak_year - start_year)) - 1
                    add("assumptions", "revenue_growth_pct", value=round(growth, 6),
                        unit="annual, near term", asset=lead, source=source,
                        source_url=proxy_url,
                        quote=f"{start_quote}; {label}, {peak_year}: {peak_cell}",
                        grade="filed",
                        note=f"arithmetic on two filed figures: the annual rate from "
                             f"{start_year} to management's {peak_year} peak, held to the "
                             "ceiling", complete=caveat is None and not below)
            else:
                launch = next((y for y in years if series[y][0] > 0), years[0])
                add("assumptions", "therapy_mode", text_value="launch", asset=lead,
                    source=f"{source}: a filed peak for a product not yet selling",
                    quote=f"{label}, {peak_year}: {peak_cell}", grade="convention",
                    note="launch mode climbs to a stated peak on the measured average "
                         "launch", complete=caveat is None)
                add("assumptions", "peak_revenue_musd", value=peak, unit="mm USD",
                    asset=lead, source=source, source_url=proxy_url,
                    quote=f"{label}, {peak_year}: {peak_cell} (amounts in {stated})",
                    grade="filed", note=f"management's peak, {peak_year}." + risk + (
                        " Risk is applied once: by the target, inside these figures, so "
                        "the probability is drafted at 1." if found["risk_adjusted"] else
                        " Risk is applied once: by the engine, at the probability for the "
                        "product's own stage, whoever owns it."),
                    complete=caveat is None)
                add("assumptions", "years_to_peak", value=float(peak_year - launch),
                    unit="years", asset=lead, source=source, source_url=proxy_url,
                    quote=f'{label}: first revenue {launch}, peak {peak_year}',
                    grade="filed", complete=caveat is None)
                if found["risk_adjusted"]:
                    said = _risk_sentence(found["section_text"])
                    add("assumptions", "pos", value=1.0, asset=lead, source=source,
                        source_url=proxy_url, quote=said or found["caption"][-300:],
                        grade="filed",
                        note="the filing prints only a risk-adjusted case, so the target's "
                             "own risk adjustment is inside the peak drafted: the "
                             "probability is 1, and the product's risk is applied once, "
                             "not again by the engine", complete=caveat is None)
            if caveat:
                notes.append(caveat)
            unnamed = [_asset_name(a) for a in linked
                       if a["id"] != lead["id"] and not a.get("named")]
            if unnamed and one:
                notes.append(
                    f"{', '.join(unnamed)} {'is' if len(unnamed) == 1 else 'are'} linked by "
                    f"the target's registered trials but not named in its projections: "
                    f"check whether each is a programme of its own or a second row for "
                    f"{_asset_name(lead)}")
            notes.append(f'the projection case taken is "{found.get("case") or "the projections"}"'
                         f', {found.get("case_reason") or "the only case the filing prints"}')
        elif public and not proxy:
            notes.append(f"{name} filed no merger proxy or 14D-9 the search found, so there "
                         "are no management projections to draft from")
        elif public and proxy and found and found.get("unitless"):
            notes.append(f"{name}'s {proxy['form']} ({proxy['accession']}) prints its "
                         "projections without stating their unit, so no figure is read "
                         "off them")
        elif public and proxy and not revenue:
            notes.append(f"{name}'s {proxy['form']} ({proxy['accession']}) prints no "
                         "revenue projection the table reader could read with its unit")

        # The company-wide rows a product needs to value at all, where it has none.
        if lead is not None and rows:
            sibling = _sibling(conn, company["id"], lead.get("modality"), lead["id"])
            if sibling is None:
                notes.append(f"{company['ticker']} has no seeded marketed product to take "
                             "cost ratios and discount rate legs from, so those rows are "
                             "left to the analyst")
            if sibling is not None:
                sib_name = sibling["brand_name"] or sibling["generic_name"]
                for key in SIBLING_KEYS:
                    if _existing(conn, lead["id"], key) is not None:
                        continue
                    src = _existing(conn, sibling["id"], key)
                    if src is None:
                        continue
                    add("assumptions", key, value=src["value"], text_value=src["text_value"],
                        asset=lead, source=f"reused from {sib_name}: {src['source']}",
                        quote=f"{sib_name} {key} = {src['value']}", grade="analogue",
                        note=f"the acquirer's own ratio as {sib_name} carries it")
            if lead["is_marketed"] and _existing(conn, lead["id"], "pos") is None:
                add("assumptions", "pos", value=1.0, asset=lead,
                    source="approved and selling", quote=f"{_asset_name(lead)} is marketed",
                    grade="convention",
                    note="no development phase applies" + (
                        "; the target's own risk adjustment of its unapproved uses is "
                        "inside the projections, so risk is applied once"
                        if found and found.get("risk_adjusted") else ""))
        context["target"] = {"cik": cik, "name": name, "proxy": proxy,
                             "revenue_history": [{"fiscal_year": h["fiscal_year"],
                                                  "value": h["value"],
                                                  "accession": h["accession"]}
                                                 for h in history]}

    # What was paid, as a claim on equity until the filed balance sheet carries the deal.
    paid = _consideration(conn, closing, context)
    balance = _balance_date(conn, company["id"])
    closed_by = (date + "-28") if len(date) == 7 else date
    slug = _slug(closings.target_key(target))
    if paid.get("cash"):
        if balance and closed_by and balance >= closed_by:
            notes.append(f"the filed balance sheet at {balance} postdates the closing, so "
                         "the cash paid is already in net cash and no adjustment is drafted")
        else:
            add("other_claims", f"pending_acquisition_{slug}", value=round(paid["cash"] / 1e6, 3),
                text_value=f"cash paid for {target}", unit="mm USD",
                source=f"{paid.get('form')} {paid.get('accession')}",
                source_url=(closing["trigger_url"]
                            if paid.get("accession") == closing["trigger_accession"]
                            else None),
                quote=paid["cash_quote"], grade="filed",
                note=(f"carried as a liability from the closing on {date} until a filed "
                      f"balance sheet dated on or after it includes the deal (latest on "
                      f"file: {balance or 'none'}), when the valuation drops it"))
    else:
        notes.append("no filing read states the total cash paid, so no balance sheet "
                     "adjustment is drafted")
    if paid.get("cvr_quote") and not (balance and closed_by and balance >= closed_by):
        notes.append("a contingent value right is payable; its aggregate is not stated as "
                     "one figure in the filings read, so no claim is drafted: "
                     f"\"{paid['cvr_quote'][:300]}\"")

    context["linked_assets"] = [
        {k: a.get(k) for k in ("id", "brand_name", "generic_name", "is_marketed",
                               "linked_by", "named", "modelled_rows", "mode", "loe",
                               "proposed")}
        for a in linked]
    context["consideration"] = paid
    conn.execute("DELETE FROM input_drafts WHERE closing_id = ? AND status IN "
                 "('draft', 'incomplete')", (closing_id,))
    for row in rows:
        conn.execute(
            """INSERT OR IGNORE INTO input_drafts (company_id, closing_id, trigger_accession,
                   trigger_kind, destination, asset_id, proposed_asset, key, value,
                   text_value, unit, year, source, source_url, quote, evidence, note,
                   existing_value, existing_text, existing_source, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company["id"], closing_id, trigger[0], trigger[1], row["destination"],
             row["asset_id"], row["proposed_asset"], row["key"], row["value"],
             row["text_value"], row["unit"], row["year"], row["source"],
             row["source_url"], row["quote"], row["evidence"], row["note"],
             row["existing_value"], row["existing_text"], row["existing_source"],
             row["status"]))
    note = "; ".join(dict.fromkeys(notes)) or None
    conn.execute(
        """UPDATE deal_closings SET target_cik = ?, target_status = ?, context = ?,
               note = ?, drafted_at = datetime('now') WHERE id = ?""",
        (context.get("target", {}).get("cik"), "public" if public else "private",
         json.dumps(context, default=str), note, closing_id))
    conn.commit()
    return {"rows": rows, "note": note, "context": context}


# --- the queue ---------------------------------------------------------------------

def queue(conn, ticker: str) -> dict | None:
    """Every closing for one company, newest first, each with its drafted rows."""
    company = conn.execute("SELECT id, ticker FROM companies WHERE ticker = ?",
                           (ticker.upper(),)).fetchone()
    if company is None:
        return None
    out = []
    for closing in conn.execute(
            "SELECT * FROM deal_closings WHERE company_id = ?"
            " ORDER BY closing_date DESC, id DESC", (company["id"],)):
        rows = [dict(r) for r in conn.execute(
            """SELECT d.*, COALESCE(a.brand_name, a.generic_name) AS asset_name
                 FROM input_drafts d LEFT JOIN assets a ON a.id = d.asset_id
                WHERE d.closing_id = ? ORDER BY d.destination, d.asset_id, d.key""",
            (closing["id"],))]
        for r in rows:
            proposed = json.loads(r["proposed_asset"]) if r["proposed_asset"] else None
            r["new_product"] = bool(proposed) and r["status"] in ("draft", "incomplete")
            if proposed and not r["asset_name"]:
                r["asset_name"] = proposed.get("brand") or proposed.get("generic")
        entry = dict(closing)
        entry["context"] = json.loads(closing["context"] or "{}")
        entry["rows"] = rows
        entry["open"] = sum(1 for r in rows if r["status"] in ("draft", "incomplete"))
        out.append(entry)
    return {"ticker": company["ticker"], "closings": out,
            "open": sum(c["open"] for c in out)}


def summary(conn) -> list[dict]:
    """Per company: closings on file, rows still open, the latest closing and the
    targets, and each closing with its own open rows, so a story about one acquisition
    can say the model does not hold it yet without marking the company out."""
    out = [dict(r) for r in conn.execute(
        """SELECT c.ticker, COUNT(DISTINCT d.id) AS closings,
                  SUM(CASE WHEN i.status IN ('draft', 'incomplete') THEN 1 ELSE 0 END)
                      AS open_rows,
                  MAX(d.closing_date) AS latest_closing,
                  GROUP_CONCAT(DISTINCT d.target) AS targets
             FROM deal_closings d JOIN companies c ON c.id = d.company_id
             LEFT JOIN input_drafts i ON i.closing_id = d.id
            GROUP BY c.ticker ORDER BY latest_closing DESC""")]
    by_ticker = {r["ticker"]: r for r in out}
    for r in out:
        r["deals"] = []
    for d in conn.execute(
            """SELECT c.ticker, d.id, d.target, d.target_key, d.closing_date,
                      d.trigger_accession,
                      SUM(CASE WHEN i.status IN ('draft', 'incomplete') THEN 1 ELSE 0 END)
                          AS open_rows
                 FROM deal_closings d JOIN companies c ON c.id = d.company_id
                 LEFT JOIN input_drafts i ON i.closing_id = d.id
                GROUP BY d.id ORDER BY d.closing_date DESC, d.id DESC"""):
        by_ticker[d["ticker"]]["deals"].append(
            {k: d[k] for k in ("id", "target", "target_key", "closing_date",
                               "trigger_accession", "open_rows")})
    return out


def _seed_file(seed_dir: pathlib.Path, ticker: str, brand: str) -> pathlib.Path:
    for path in sorted(seed_dir.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(l for l in handle if not l.lstrip().startswith("#")):
                if ((row.get("ticker") or "").strip().upper() == ticker
                        and (row.get("brand") or "").strip().lower() == brand.lower()):
                    return path
                break
    return seed_dir / f"{ticker.lower()}_{_slug(brand)}.csv"


def _format(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def upsert_csv(path: pathlib.Path, header: list[str], match: tuple, row: dict,
               preamble: str = "") -> str:
    """Replace the line whose ``match`` fields equal the row's, or append one, leaving
    every other line, comment and line ending as it was. Returns 'updated' or 'added'."""
    lines = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            lines = handle.read().splitlines(keepends=True)
    ending = "\r\n" if any(l.endswith("\r\n") for l in lines) else "\n"
    if not lines:
        lines = [f"# {l}{ending}" for l in preamble.splitlines() if l] + [
            ",".join(header) + ending]
    file_header, out, done = None, [], False
    for line in lines:
        if line.lstrip().startswith("#") or not line.strip():
            out.append(line)
            continue
        cells = next(csv.reader([line]))
        if file_header is None:
            file_header = cells
            out.append(line)
            continue
        fields = dict(zip(file_header, cells))
        if not done and all((fields.get(k) or "").strip().lower() ==
                            _format(row.get(k)).strip().lower() for k in match):
            buf = io.StringIO()
            csv.writer(buf, lineterminator="").writerow(
                [_format(row.get(h, fields.get(h))) for h in file_header])
            out.append(buf.getvalue() + line[len(line.rstrip("\r\n")):])
            done = True
            continue
        out.append(line)
    if not done:
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] += ending
        buf = io.StringIO()
        csv.writer(buf, lineterminator="").writerow(
            [_format(row.get(h)) for h in (file_header or header)])
        out.append(buf.getvalue() + ending)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("".join(out))
    return "updated" if done else "added"


SEED_HEADER = ["ticker", "brand", "indication", "region", "scenario", "key", "year",
               "value", "text_value", "unit", "source", "note"]
CLAIMS_HEADER = ["ticker", "item", "label", "kind", "value", "as_of", "source", "note"]


def decide(conn, draft_id: int, action: str, edits: dict | None = None,
           seed_dir=None, claims_path=None, additions_path=None) -> dict:
    """Accept, edit then accept, or reject one drafted row.

    Accepting writes the book and the seed file, after a snapshot of what the book held,
    so the change can always be diffed. Raises ValueError with the reason a row cannot be
    accepted: decided already, incomplete without an edit, no source or quote, or an asset
    that is not the company's.
    """
    row = conn.execute(
        """SELECT d.*, c.ticker, cl.closing_date FROM input_drafts d
             JOIN companies c ON c.id = d.company_id
             LEFT JOIN deal_closings cl ON cl.id = d.closing_id WHERE d.id = ?""",
        (draft_id,)).fetchone()
    if row is None:
        raise LookupError(f"no drafted row {draft_id}")
    if row["status"] not in ("draft", "incomplete"):
        raise ValueError(f"row {draft_id} is {row['status']} already")
    if action == "reject":
        conn.execute("UPDATE input_drafts SET status = 'rejected',"
                     " decided_at = datetime('now') WHERE id = ?", (draft_id,))
        conn.commit()
        return {"id": draft_id, "status": "rejected"}
    if action != "accept":
        raise ValueError(f"unknown action {action}")
    edits = {k: v for k, v in (edits or {}).items() if k in EDITABLE}
    if row["status"] == "incomplete" and not edits:
        raise ValueError(f"row {draft_id} is incomplete and needs an edit before it can be "
                         f"accepted: {row['note'] or 'no source'}")
    merged = {**dict(row), **edits}
    if not (merged.get("source") or "").strip() or not (merged.get("quote") or "").strip():
        raise ValueError("a row needs its source and the quote it came from")
    if merged.get("value") is None and not (merged.get("text_value") or "").strip():
        raise ValueError("a row needs a value")
    grade = (merged.get("evidence") or "").strip().lower() or None
    status = "edited" if edits else "accepted"
    ticker = row["ticker"]

    created = None
    if row["destination"] == "assumptions":
        if merged.get("asset_id") is None and row["proposed_asset"]:
            # A product the book does not hold is added under the buyer as its first row
            # is accepted, book and seed file both, and its other drafted rows follow it.
            merged["asset_id"], created = _add_product(
                conn, row, json.loads(row["proposed_asset"]), additions_path)
            edits = {k: v for k, v in edits.items() if k != "asset_id"}
        asset = conn.execute(
            "SELECT id, brand_name, generic_name, owner_company_id FROM assets WHERE id = ?",
            (merged.get("asset_id"),)).fetchone()
        if asset is None or asset["owner_company_id"] != row["company_id"]:
            raise ValueError("an assumption row needs an asset the company owns")
        conn.execute(
            "INSERT INTO snapshots (source, entity_type, entity_key, payload)"
            " VALUES ('input_drafts', 'asset', ?, ?)",
            (str(asset["id"]), json.dumps({"draft_id": draft_id, "before":
                                           assumptions_module.rows(conn, asset["id"],
                                                                   merged["scenario"])},
                                          default=str)))
        source = f'{merged["source"].rstrip(". ")}: "{merged["quote"]}"'
        written = {"key": merged["key"], "year": merged.get("year"),
                   "value": merged.get("value"), "text_value": merged.get("text_value"),
                   "unit": merged.get("unit"), "source": source, "note": merged.get("note"),
                   "region": merged["region"], "scenario": merged["scenario"],
                   "evidence": grade}
        assumptions_module.save(conn, asset["id"], [written])
        brand = asset["brand_name"] or asset["generic_name"]
        path = _seed_file(pathlib.Path(seed_dir) if seed_dir else SEED_DIR, ticker, brand)
        seed = upsert_csv(
            path, SEED_HEADER, ("indication", "region", "scenario", "key", "year"),
            {"ticker": ticker, "brand": brand, "indication": "", **written},
            preamble=f"{brand} ({ticker}): rows accepted in the terminal's guided input "
                     "step, each with the filing it came from.")
    elif row["destination"] == "other_claims":
        before = [dict(r) for r in conn.execute(
            "SELECT * FROM other_claims WHERE company_id = ?", (row["company_id"],))]
        conn.execute(
            "INSERT INTO snapshots (source, entity_type, entity_key, payload)"
            " VALUES ('input_drafts', 'company', ?, ?)",
            (ticker, json.dumps({"draft_id": draft_id, "before": before}, default=str)))
        as_of = row["closing_date"] or dt.date.today().isoformat()
        source = f'{merged["source"].rstrip(". ")}: "{merged["quote"]}"'
        label = merged.get("text_value") or merged["key"]
        conn.execute(
            """INSERT INTO other_claims (company_id, item, label, value, sign, unit, as_of,
                   basis, source, note)
               VALUES (?, ?, ?, ?, -1, ?, ?, 'filed, curated', ?, ?)
               ON CONFLICT(company_id, item) DO UPDATE SET label = excluded.label,
                   value = excluded.value, sign = -1, unit = excluded.unit,
                   as_of = excluded.as_of, basis = excluded.basis,
                   source = excluded.source, note = excluded.note,
                   updated_at = datetime('now')""",
            (row["company_id"], merged["key"], label, merged["value"], "USD", as_of, source,
             merged.get("note")))
        path = pathlib.Path(claims_path) if claims_path else CLAIMS_PATH
        seed = upsert_csv(path, CLAIMS_HEADER, ("ticker", "item"),
                          {"ticker": ticker, "item": merged["key"], "label": label,
                           "kind": "liability", "value": merged["value"], "as_of": as_of,
                           "source": source, "note": merged.get("note")})
    else:
        raise ValueError(f"unknown destination {row['destination']}")
    if created is not None:
        edits["asset_id"] = created["asset_id"]
    assignments = ", ".join(["status = ?", "decided_at = datetime('now')"]
                            + [f"{k} = ?" for k in edits])
    conn.execute(f"UPDATE input_drafts SET {assignments} WHERE id = ?",
                 (status, *edits.values(), draft_id))
    conn.commit()
    out = {"id": draft_id, "status": status, "seed_file": str(path), "seed": seed}
    if created is not None:
        out["product"] = created
    return out


def _add_product(conn, row, proposed: dict, additions_path=None) -> tuple:
    """(asset_id, what was done): the product a drafted row proposes, under the buyer.

    The asset the book already holds under the buyer by the same application number,
    brand or ingredient is used, so a second accepted row, or a fetcher that has since
    caught up, never makes a second one. Otherwise the asset is written as the curated
    register writes an acquired product (``curated_register.py``): marketed, keyed by
    its application number, with the biologic floor where no exclusivity is on file, and
    the same row added to ``data/marketed_additions.csv`` so a rebuilt book has it too.
    The buyer's other drafted rows for the product are pointed at it."""
    import curated_register
    from assets_util import upsert_asset

    code = (proposed.get("internal_code") or "").strip()
    brand = (proposed.get("brand") or "").strip()
    generic = (proposed.get("generic") or "").strip() or None
    if not code or not brand or not proposed.get("is_marketed"):
        raise ValueError("a proposed product needs a brand and the application number of "
                         "its approval before it can be added")
    held = conn.execute(
        """SELECT id FROM assets WHERE owner_company_id = ?
              AND (internal_code = ? OR LOWER(TRIM(brand_name)) = LOWER(?))
            ORDER BY internal_code = ? DESC, id LIMIT 1""",
        (row["company_id"], code, brand, code)).fetchone()
    done = {"brand": brand, "internal_code": code}
    if held is not None:
        asset_id, done["action"] = held["id"], "found in the book"
    else:
        asset_id = upsert_asset(conn, row["company_id"], code, brand, generic,
                                proposed.get("modality"))
        done["action"] = "added to the book"
        conn.execute(
            "INSERT INTO snapshots (source, entity_type, entity_key, payload)"
            " VALUES ('input_drafts', 'asset', ?, ?)",
            (code, json.dumps({"asset_id": asset_id, "is_marketed": 1, "was": None,
                               "draft_id": row["id"], "source": proposed.get("source")})))
        expiry = (curated_register._floor(proposed.get("licensed_on") or "")
                  if code.upper().startswith("BLA") else None)
        if expiry and not conn.execute("SELECT 1 FROM exclusivities WHERE asset_id = ?"
                                       " LIMIT 1", (asset_id,)).fetchone():
            conn.execute(
                """INSERT INTO exclusivities
                       (asset_id, region, protection_type, identifier, expiry_date, source)
                   VALUES (?, 'US', ?, ?, ?, ?)""",
                (asset_id, curated_register.FLOOR_PROTECTION,
                 curated_register.FLOOR_IDENTIFIER, expiry, curated_register.SOURCE))
    done["asset_id"] = asset_id
    done["seed"] = upsert_csv(
        pathlib.Path(additions_path) if additions_path else ADDITIONS_PATH, ADDITIONS_HEADER,
        ("ticker", "internal_code"),
        {"ticker": row["ticker"], "brand": brand, "generic": generic or "",
         "internal_code": code, "modality": proposed.get("modality") or "",
         # The biologic floor is written from this date; a small molecule's exclusivity
         # comes from the Orange Book under its application number instead.
         "licensed_on": (proposed.get("licensed_on") or "")
         if code.upper().startswith("BLA") else "",
         "source": f"{proposed.get('source')}; acquired with the closing drafted as "
                   f"{row['trigger_kind']} {row['trigger_accession']}"})
    conn.execute(
        "UPDATE input_drafts SET asset_id = ? WHERE company_id = ? AND asset_id IS NULL"
        "   AND proposed_asset = ? AND id != ?",
        (asset_id, row["company_id"], row["proposed_asset"], row["id"]))
    return asset_id, done


# --- the refresh step --------------------------------------------------------------

def run(db_path=None, since: str = SINCE, limit: int | None = READS_PER_RUN, edgar=None,
        catch_up: bool = False) -> dict:
    """Detect new closings and draft each one not drafted yet. Idempotent: a filing read
    once is never read again and a closing drafted once is never drafted again. The
    refresh step calls this as it is; ``catch_up`` is the one-off first run."""
    if edgar is None:
        try:
            from fetchers.closings_edgar import Edgar
            edgar = Edgar()
        except RuntimeError:
            edgar = None                     # stored text only, and no drafting
    conn = db.get_connection(db_path)
    try:
        found = detect(conn, edgar, since, limit, catch_up=catch_up)
        drafted, errors = 0, list(found["errors"])
        if edgar is not None:
            for closing in conn.execute(
                    "SELECT id, target FROM deal_closings WHERE drafted_at IS NULL"
                    " ORDER BY id").fetchall():
                try:
                    draft(conn, closing["id"], edgar)
                    drafted += 1
                except Exception as exc:       # one target's filings never stop the rest
                    errors.append(f"{closing['target']}: {exc}")
        return {"read": sum(found["verdicts"].values()), "fetched": found["fetched"],
                "verdicts": found["verdicts"], "closings": len(found["closings"]),
                "drafted": drafted, "errors": errors}
    finally:
        conn.close()


def catch_up(db_path=None, edgar=None) -> dict:
    """The one-off run for when this goes live: every unread filing since ``SINCE`` is
    read, uncapped, so the queue starts complete and each refresh after it reads only new
    filings."""
    return run(db_path, edgar=edgar, catch_up=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--catch-up", action="store_true",
                        help="read every unread filing since %s, uncapped" % SINCE)
    args = parser.parse_args()
    import env
    env.load()
    print(json.dumps(catch_up() if args.catch_up else run(), indent=1, default=str))
