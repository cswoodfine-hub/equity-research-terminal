"""What the book leaves unvalued, named so the next gap is reported by the book itself.

Lilly read 97% covered on 2026-11-27 while seven gaps sat under the figure: a Phase 3
with no forecast because the registry held it as three rows, a bought company whose
asset had no seed, five lines anchored on the first half of the year after the third
quarter was filed, and acquisition rows with no terms. None of them was in any summary;
each was found by reading. These reads put them in the run's health summary and on the
completeness board, so they are measured every day rather than found by chance.

Four reads, each pure over the database and each returning rows a person can act on:

  bought_unvalued        for each company, the companies it bought within five years
                         whose assets at Phase 2 or later carry no forecast, and its
                         acquisition rows with no terms
  late_stage_unmodelled  Phase 3, Phase 2/3 and filed assets with no forecast, with the
                         reason the engine gives (no seed, or the inputs it refuses on)
  stale_anchors          every marketed seed and company line whose run-rate anchor
                         cites a quarter earlier than the company's latest filed one
  guidance_gap           the companies whose modelled revenue for the guided year sits
                         outside the guided range by more than ``GUIDANCE_DISTANCE``
  arm names              every pipeline row whose name reads as a dose, a route, a
                         tracer label or an arm label (trial_mapping.reads_as_arm), the
                         queue data/programme_names.csv is fed from

Nothing here values anything: ``late_stage_unmodelled`` asks the engine whether it can
build and reports what it says. The threshold for the guidance gap was read off the
universe on 2026-11-27: eleven companies carried guidance, the median absolute gap was
1.5% of the midpoint and the upper quartile 2.9%, and the two beyond 3% both ran on
guidance older than the stale threshold. So 3% separates a model to look at from a
quarter's drift.
"""

from __future__ import annotations

import datetime as dt
import re

import acquisitions
import assumptions
import company_names
import db
import forecast
import trial_mapping

# How far back an acquisition counts, the window acquired_sponsors reads.
WITHIN_DAYS = 1825
LATE_PHASES = ("Phase 3", "Phase 2/3")
BOUGHT_PHASES = ("Phase 2", "Phase 2/3", "Phase 3")
DECISION_KINDS = ("PDUFA", "regulatory decision")
# Outside the guided range by more than this share of the midpoint, and the model wants
# a look. See the module docstring for where it comes from.
GUIDANCE_DISTANCE = 0.03

_PHASE_RANK = {"Phase 4": 6, "Phase 3": 5, "Phase 2/3": 4, "Phase 2": 3, "Phase 1/2": 2,
               "Phase 1": 1}


def _companies(conn, ticker=None) -> list:
    query = "SELECT id, ticker, name FROM companies"
    params: list = []
    if ticker:
        query += " WHERE ticker = ?"
        params.append(ticker.upper())
    return conn.execute(query + " ORDER BY ticker", params).fetchall()


def _phase(conn, asset_id: int) -> str | None:
    """The asset's furthest phase, by the rule assumptions.load and pos_granular use."""
    rows = [r["phase"] for r in conn.execute(
        "SELECT phase FROM asset_indications WHERE asset_id = ?", (asset_id,))
            if r["phase"]]
    return max(rows, key=lambda p: _PHASE_RANK.get(p, 0)) if rows else None


def _filed(conn, asset_id: int) -> bool:
    """Whether a pending FDA decision is on the calendar for the asset."""
    marks = ",".join("?" * len(DECISION_KINDS))
    return conn.execute(
        f"""SELECT 1 FROM catalysts WHERE asset_id = ? AND status = 'pending'
             AND catalyst_type IN ({marks}) LIMIT 1""",
        (asset_id, *DECISION_KINDS)).fetchone() is not None


def refusal(conn, asset_id: int) -> str | None:
    """Why the engine builds no forecast for the asset: "no seed" where it carries no
    assumption row, the inputs it refuses on where it carries some, None where it
    builds."""
    if conn.execute("SELECT 1 FROM assumptions WHERE asset_id = ? AND scenario = 'base'"
                    " LIMIT 1", (asset_id,)).fetchone() is None:
        return "no seed"
    try:
        forecast.build(assumptions.load(conn, asset_id))
    except forecast.ForecastError as err:
        return "refused: " + ", ".join(err.missing or ["unstated"])
    except Exception as exc:                                       # noqa: BLE001
        return f"failed: {type(exc).__name__}"
    return None


def _live_assets(conn, company_id: int) -> list:
    """Unmarketed, unretired assets of the company with their furthest phase."""
    return [dict(r) | {"phase": _phase(conn, r["id"])} for r in conn.execute(
        """SELECT a.id, COALESCE(a.brand_name, a.generic_name, a.internal_code) AS name
             FROM assets a
            WHERE a.owner_company_id = ? AND COALESCE(a.is_marketed, 0) = 0
              AND a.id NOT IN (SELECT asset_id FROM retired_programmes)
            ORDER BY a.id""", (company_id,))]


def late_stage_unmodelled(conn, ticker=None) -> list[dict]:
    """{ticker, asset_id, asset, phase, reason} for every Phase 3, Phase 2/3 or filed
    asset the engine builds no forecast for."""
    out = []
    for company in _companies(conn, ticker):
        for asset in _live_assets(conn, company["id"]):
            filed = _filed(conn, asset["id"])
            if asset["phase"] not in LATE_PHASES and not filed:
                continue
            why = refusal(conn, asset["id"])
            if why is None:
                continue
            out.append({"ticker": company["ticker"], "asset_id": asset["id"],
                        "asset": asset["name"],
                        "phase": "Filed" if filed else asset["phase"], "reason": why})
    return out


def _targets(conn, company, today) -> list[str]:
    """The names of the companies this one bought within the window, as the deals table
    and the acquisition ledger carry them, plus the names they register studies under."""
    cutoff = (today - dt.timedelta(days=WITHIN_DAYS)).isoformat()
    names = [r["counterparty"].strip() for r in conn.execute(
        """SELECT counterparty FROM deals WHERE company_id = ? AND deal_type = 'acquisition'
             AND counterparty IS NOT NULL AND COALESCE(event_date, '') >= ?""",
        (company["id"], cutoff))]
    names += acquisitions.sponsor_names(company["ticker"])
    return sorted({n for n in names if len(company_names.bare(n)) >= 4})


def _lead_starts(lead: str, name: str) -> bool:
    lead, core = (lead or "").lower().strip(), company_names.bare(name).lower()
    if not core or not lead.startswith(core):
        return False
    rest = lead[len(core):]
    return not rest or not rest[0].isalnum()


def _bought_assets(conn, company_id: int, targets: list[str]) -> dict:
    """{asset_id: target} for the company's assets whose studies the registry files
    under a bought company's name."""
    found: dict = {}
    for table in ("trials", "completed_trials"):
        for row in conn.execute(
                f"""SELECT t.asset_id, t.lead_sponsor FROM {table} t
                      JOIN assets a ON a.id = t.asset_id
                     WHERE a.owner_company_id = ? AND t.lead_sponsor IS NOT NULL""",
                (company_id,)):
            for target in targets:
                if _lead_starts(row["lead_sponsor"], target):
                    found.setdefault(row["asset_id"], target)
    return found


def bought_unvalued(conn, ticker=None, today=None) -> dict:
    """{"assets": [...], "deals_without_terms": [...]}.

    ``assets`` names, per company, each bought asset at Phase 2 or later with no
    forecast, with its target and the engine's reason. ``deals_without_terms`` is
    acquisitions.without_terms for the same window.
    """
    today = today or dt.date.today()
    assets = []
    for company in _companies(conn, ticker):
        targets = _targets(conn, company, today)
        if not targets:
            continue
        bought = _bought_assets(conn, company["id"], targets)
        for asset in _live_assets(conn, company["id"]):
            if asset["id"] not in bought or asset["phase"] not in BOUGHT_PHASES:
                continue
            why = refusal(conn, asset["id"])
            if why is None:
                continue
            assets.append({"ticker": company["ticker"], "target": bought[asset["id"]],
                           "asset_id": asset["id"], "asset": asset["name"],
                           "phase": asset["phase"], "reason": why})
    return {"assets": assets,
            "deals_without_terms": acquisitions.without_terms(
                conn, ticker, within_days=WITHIN_DAYS, today=today)}


# --- stale anchors ----------------------------------------------------------------------
_QUARTER = re.compile(r"\b(first|second|third|fourth)[- ]quarter(?: of)? (20\d\d)\b", re.I)
_Q = re.compile(r"\bQ([1-4])[ -](20\d\d)\b")
_HALF = re.compile(r"\b(first|second) half of (20\d\d)\b", re.I)
_NINE = re.compile(r"\bnine months(?: of| to| ended)?(?: September 30,?)? (20\d\d)\b", re.I)
_TO_DATE = re.compile(r"\bquarter (?:to|ended) (20\d\d)-(\d\d)-(\d\d)\b", re.I)
_ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_Q_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def cited_period(text: str) -> str | None:
    """The latest quarter end a run-rate anchor's text cites, as YYYY-MM-DD, or None
    where it cites no quarter, half or nine-month period (an annual anchor)."""
    ends = []
    for m in _QUARTER.finditer(text or ""):
        ends.append(f"{m.group(2)}-{_Q_END[_ORDINAL[m.group(1).lower()]]}")
    for m in _Q.finditer(text or ""):
        ends.append(f"{m.group(2)}-{_Q_END[int(m.group(1))]}")
    for m in _HALF.finditer(text or ""):
        ends.append(f"{m.group(2)}-{_Q_END[2 if m.group(1).lower() == 'first' else 4]}")
    for m in _NINE.finditer(text or ""):
        ends.append(f"{m.group(1)}-09-30")
    for m in _TO_DATE.finditer(text or ""):
        ends.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    return max(ends) if ends else None


def latest_filed_quarter(conn, company_id: int) -> str | None:
    row = conn.execute(
        """SELECT MAX(period_end) FROM financials WHERE company_id = ?
            AND metric = 'Revenues' AND period_type = 'Q'""", (company_id,)).fetchone()
    return row[0] if row and row[0] else None


REVIEWS = db.BACKEND_DIR.parent / "data" / "stale_anchor_reviews.csv"


def anchor_reviews(path=None) -> dict:
    """{(ticker, kind, name lower-cased): the quarter end the anchor was last read against}
    from data/stale_anchor_reviews.csv: anchors that cannot be re-struck on that quarter
    (the row is no longer printed, the line was restated, the figure carries a one-off),
    each with its reason. A later filed quarter brings the anchor back into the reading."""
    import csv
    source = REVIEWS if path is None else path
    out = {}
    try:
        with open(source, newline="", encoding="utf-8") as handle:
            for r in csv.DictReader(line for line in handle if not line.lstrip().startswith("#")):
                out[((r.get("ticker") or "").strip().upper(), (r.get("kind") or "").strip(),
                     (r.get("name") or "").strip().lower())] = (r.get("reviewed_quarter") or "").strip()
    except FileNotFoundError:
        pass
    return out


def stale_anchors(conn, ticker=None) -> list[dict]:
    """{ticker, kind, name, cited, latest} for every marketed seed and company line
    whose run-rate anchor cites a quarter earlier than the company's latest filed one.
    An anchor that cites no quarter (a reported full year) is not a run rate and is
    left out."""
    out = []
    reviewed = anchor_reviews()
    for company in _companies(conn, ticker):
        latest = latest_filed_quarter(conn, company["id"])
        if not latest:
            continue
        anchors = []
        for r in conn.execute(
                """SELECT a.id, COALESCE(a.brand_name, a.generic_name) AS name,
                          GROUP_CONCAT(COALESCE(s.source, '') || ' ' || COALESCE(s.note, ''),
                                       ' ') AS text
                     FROM assumptions s JOIN assets a ON a.id = s.asset_id
                    WHERE a.owner_company_id = ? AND s.scenario = 'base'
                      AND s.indication_id IS NULL
                      AND s.key IN ('base_revenue', 'revenue_growth_pct')
                    GROUP BY a.id""", (company["id"],)):
            anchors.append(("seed", r["name"], r["text"]))
        for r in conn.execute(
                """SELECT line, GROUP_CONCAT(COALESCE(source, '') || ' ' || COALESCE(note, ''),
                                             ' ') AS text
                     FROM company_lines WHERE company_id = ? AND scenario = 'base'
                      AND key IN ('base_revenue', 'revenue_growth_pct') GROUP BY line""",
                (company["id"],)):
            anchors.append(("line", r["line"], r["text"]))
        for kind, name, text in anchors:
            cited = cited_period(text)
            if reviewed.get((company["ticker"], kind, name.lower()), "") >= latest[:10]:
                continue            # read against this quarter and left, with a reason
            if cited and cited < latest[:10]:
                out.append({"ticker": company["ticker"], "kind": kind, "name": name,
                            "cited": cited, "latest": latest[:10]})
    return out


# --- the guidance gap -------------------------------------------------------------------
def outside_range(expected: float, low: float, high: float, mid: float) -> float:
    """How far the modelled figure sits outside the guided range, as a share of the
    midpoint; nought inside it."""
    if not mid:
        return 0.0
    if expected > high:
        return (expected - high) / mid
    if expected < low:
        return (low - expected) / mid
    return 0.0


def guidance_flag(split: dict | None) -> dict | None:
    """{outside_pct, flagged} from a fair_value.revenue_split payload, or None where the
    split holds no guidance."""
    if not split or not split.get("ok"):
        return None
    guided = split.get("guidance") or {}
    expected = split.get("expected")
    if expected is None or guided.get("mid") in (None, 0):
        return None
    away = outside_range(expected, guided.get("low", guided["mid"]),
                         guided.get("high", guided["mid"]), guided["mid"])
    return {"outside_pct": away, "flagged": away > GUIDANCE_DISTANCE}


# --- the summary a run writes -----------------------------------------------------------
def summary(db_path=None, today=None) -> dict:
    """The three database reads for the health summary, with a line. The guidance gap
    is not here: it needs the valuation, which the completeness board carries."""
    conn = db.get_connection(db_path)
    try:
        bought = bought_unvalued(conn, today=today)
        late = late_stage_unmodelled(conn)
        stale = stale_anchors(conn)
        arms = trial_mapping.arm_named_assets(conn)
    finally:
        conn.close()

    def by_ticker(rows):
        counts: dict = {}
        for r in rows:
            counts[r["ticker"]] = counts.get(r["ticker"], 0) + 1
        return dict(sorted(counts.items()))

    def said(label, rows):
        counts = by_ticker(rows)
        if not counts:
            return f"{label}: none"
        return f"{label}: " + ", ".join(f"{t} {n}" for t, n in counts.items())

    line = "; ".join([
        said("bought and unvalued", bought["assets"]),
        said("acquisitions with no terms", bought["deals_without_terms"]),
        said("late-stage and unmodelled", late),
        said("stale anchors", stale),
        said("arm names", arms),
    ])
    return {"line": line, "bought_unvalued": bought["assets"],
            "deals_without_terms": bought["deals_without_terms"],
            "late_stage_unmodelled": late, "stale_anchors": stale, "arm_names": arms}
