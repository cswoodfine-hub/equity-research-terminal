"""The desk tools: the book's own reads, shaped for a language model to call.

The terminal's API answers the page. A payload built for a chart carries twenty years of
a series for every product a company sells, and a model handed 240KB of it to answer "what
is this asset worth if the readout passes" spends its attention on the wrong thing. These
are the same reads, asked the way an analyst asks them and cut to what the answer needs:
one tool to a question, the figures and their bases kept, the series dropped unless they
are the answer.

Every tool is a read of the API and adds no number of its own. That is the point of the
arrangement. A model working through these can connect things no single page connects,
a cash runway against a readout date against the move the options price, and every figure
it connects is one the book computed and can source. Where the book has nothing the
payload says so and the model is told, in the server's instructions, to say so too.

One tool writes: ``lens_log_thesis`` appends a dated, falsifiable claim to the thesis log
(``thesis_log.py``), which is how a read made through these tools gets a track record
instead of being taken on trust. Nothing here changes a value, an assumption or a
catalyst. The what-if tool computes a variation and saves nothing.

The module is plain standard library and imports nothing from the backend, on purpose.
It runs in two places: under the test suite on the backend's own interpreter, and inside
the MCP server process (``mcp_server/lens_mcp.py``), which needs a newer Python than the
backend's for the protocol SDK and so cannot import the backend itself. All either needs
is ``fetch``, a function that makes one request to the API:

    fetch(method, path, params, body) -> (status code, parsed JSON or None)

A tool that cannot answer raises ``ToolError`` with a sentence the caller can act on,
which the server returns as a tool error the model reads, not a protocol fault.
"""

from __future__ import annotations

import json

# A model's context is the budget. One answer over this is cut harder and marked, since
# an answer that crowds out the question it was asked for has failed however complete.
MAX_CHARS = 48_000
TEXT = 600            # a quoted sentence or a basis line survives; a filing section does not
ROWS = 40

INSTRUCTIONS = (
    "Novatalis Lens is a biopharma equity research book: about 75 companies, each asset "
    "forecast from patients and price to risk-adjusted value, each readout priced as a "
    "gate with odds and a per-share swing either way. These tools read that book. "
    "Rules for using them: (1) Every figure you state must come from a tool result; if "
    "the book has no figure, say it has none and do not estimate one. (2) Give the as-of "
    "date a result carries, since the book is only as fresh as its last refresh. "
    "(3) Start with lens_universe or lens_company to get tickers and asset ids; most "
    "other tools need them. (4) lens_whatif and lens_as_of are how to test an idea "
    "against the book's own arithmetic and its own past, which is better than reasoning "
    "about it in prose. (5) The book's edge is unproven: lens_track_record says how its "
    "calls have scored so far, and any read you give should say so where it matters. "
    "(6) This is research, not advice: do not tell the user to buy or sell. "
    "(7) Call lens_log_thesis only when the user asks for a read to be put on the "
    "record; it is append-only and is marked against XBI on its due date. "
    "(8) A list that says it shows fewer rows than its total is a sample: never add it "
    "up or count it. Use the totals and summaries the tool gives, and if the one you "
    "need is not there, say so."
)


class ToolError(Exception):
    """A tool that could not answer, with the reason in words."""


# --- shaping --------------------------------------------------------------------------
def _scalar(value) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _clip(text: str, limit: int = TEXT) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + " [cut]"


def _flat(row, text: int = TEXT, keep: tuple = ()) -> dict:
    """A row's scalar fields, long strings cut, plus any nested fields named in ``keep``.
    The nested series a chart needs are what makes a payload large, and a table row
    reads the same without them."""
    if not isinstance(row, dict):
        return row
    out = {}
    for key, value in row.items():
        if isinstance(value, str):
            out[key] = _clip(value, text)
        elif _scalar(value) or key in keep:
            out[key] = value
    return out


def _rows(rows, limit: int = ROWS, text: int = TEXT, keep: tuple = ()) -> dict:
    """{rows, shown, total}: the first ``limit`` rows flattened, and how many there were,
    so a cut list is never mistaken for a whole one."""
    rows = rows or []
    return {"rows": [_flat(r, text, keep) for r in rows[:limit]],
            "shown": min(len(rows), limit), "total": len(rows)}


def _pick(rows, keys: tuple, limit: int = ROWS, text: int = TEXT) -> dict:
    """{rows, shown, total} with only the named fields of each row, for a table whose
    rows carry far more than a reader of it needs (and, in the edit ledger, who made
    each edit, which is nobody's business outside the terminal)."""
    rows = rows or []
    out = []
    for row in rows[:limit]:
        kept = {k: row.get(k) for k in keys if row.get(k) is not None}
        out.append({k: _clip(v, text) if isinstance(v, str) else v for k, v in kept.items()})
    return {"rows": out, "shown": min(len(rows), limit), "total": len(rows)}


def _trim(value, rows: int = ROWS, text: int = TEXT, depth: int = 6):
    """The value with every list cut to ``rows`` (the cut marked) and every string to
    ``text``. The fallback shaping for a payload that is already about the right size."""
    if isinstance(value, str):
        return _clip(value, text)
    if depth <= 0:
        return value if _scalar(value) else "[nested data cut]"
    if isinstance(value, dict):
        return {k: _trim(v, rows, text, depth - 1) for k, v in value.items()}
    if isinstance(value, list):
        cut = [_trim(v, rows, text, depth - 1) for v in value[:rows]]
        if len(value) > rows:
            cut.append(f"[{len(value) - rows} more rows cut]")
        return cut
    return value


def _fit(payload):
    """The payload inside the budget, cut harder and marked where it was not."""
    for rows, text in ((ROWS, TEXT), (20, 300), (10, 160), (5, 100)):
        if len(json.dumps(payload, default=str)) <= MAX_CHARS:
            return payload
        payload = _trim(payload, rows, text)
        if isinstance(payload, dict):
            payload["cut_to_fit"] = ("This answer was larger than one reply should be and "
                                     "was cut. Narrow the question to see the rest.")
    return payload


# --- reading the API ------------------------------------------------------------------
def _detail(payload) -> str:
    if isinstance(payload, dict) and payload.get("detail"):
        detail = payload["detail"]
        return detail if isinstance(detail, str) else json.dumps(detail, default=str)
    return ""


def _get(fetch, path: str, **params):
    params = {k: v for k, v in params.items() if v is not None}
    try:
        status, payload = fetch("GET", path, params or None, None)
    except Exception as exc:
        raise ToolError(f"the terminal's API did not answer at {path}: {exc}. It serves "
                        "on port 8000; start it with ./run.sh and ask again.")
    if status == 404:
        raise ToolError(_detail(payload) or f"the book has nothing at {path}")
    if status >= 400:
        raise ToolError(f"the API refused {path} ({status}): {_detail(payload)}")
    return payload


def _soft(fetch, path: str, **params):
    """A part of an answer that may be absent: the payload, or {"absent": why}."""
    try:
        return _get(fetch, path, **params)
    except ToolError as exc:
        return {"absent": str(exc)}


def _ticker(args: dict) -> str:
    ticker = str(args.get("ticker") or "").strip().upper()
    if not ticker:
        raise ToolError("a ticker is needed; lens_universe lists them")
    return ticker


def _asset(args: dict) -> int:
    try:
        return int(args["asset_id"])
    except (KeyError, TypeError, ValueError):
        raise ToolError("an asset_id is needed; lens_company lists a company's assets "
                        "with their ids")


# --- the tools ------------------------------------------------------------------------
def universe(fetch, args):
    companies = _get(fetch, "/companies")
    screened = _soft(fetch, "/screen")
    screen = ({r.get("ticker"): r for r in screened if isinstance(r, dict)}
              if isinstance(screened, list) else {})
    engine = (args.get("engine") or "").strip().lower() or None
    rows = []
    for c in companies:
        if engine and (c.get("engine") or "") != engine:
            continue
        s = screen.get(c.get("ticker")) or {}
        rows.append({"ticker": c.get("ticker"), "name": c.get("name"),
                     "engine": c.get("engine"), "stage": c.get("stage"),
                     "currency": c.get("reporting_currency"),
                     "revenue": s.get("revenue"), "late_trials": s.get("late_trials"),
                     "catalysts_12m": s.get("catalysts_12m"),
                     "loe_share_5y": s.get("loe_share_5y"),
                     "price_change_12m": s.get("ttm_price_change")})
    return {"companies": rows, "count": len(rows),
            "engines": sorted({c.get("engine") for c in companies if c.get("engine")}),
            "note": "revenue is in USD; loe_share_5y is the share of revenue losing "
                    "exclusivity inside five years"}


def company(fetch, args):
    ticker = _ticker(args)
    value = _get(fetch, f"/companies/{ticker}/fair-value")
    forecast = _soft(fetch, f"/companies/{ticker}/forecast")
    lines = forecast.get("lines") if isinstance(forecast, dict) else None
    runway = _soft(fetch, f"/companies/{ticker}/runway")
    return {
        "ticker": ticker, "name": value.get("name"),
        "close": value.get("close"), "price_date": value.get("price_date"),
        "fair_value": _trim({k: value.get(k) for k in ("equity_per_share", "rating", "lenses")},
                            rows=8, text=300),
        "assets": _rows(lines, limit=60, text=200),
        "rnpv_per_share": forecast.get("rnpv_per_share") if isinstance(forecast, dict) else None,
        "refused": _rows(forecast.get("refused") if isinstance(forecast, dict) else None,
                         limit=20, text=240),
        "runway": (_flat(runway, text=240) if isinstance(runway, dict) else runway),
        "next": "lens_asset for one asset's forecast, lens_gates for its readouts, "
                "lens_calendar for every date ahead",
    }


ASSUMPTION_FIELDS = ("key", "year", "value", "text_value", "unit", "region", "indication",
                     "source", "evidence")
EDIT_FIELDS = ("changed_at", "asset_name", "indication_name", "key", "year", "op",
               "old_value", "new_value", "new_unit", "reason", "rationale", "new_source",
               "new_evidence", "rnpv_before", "rnpv_after")


def asset(fetch, args):
    ticker, asset_id = _ticker(args), _asset(args)
    scenario = args.get("scenario") or "base"
    verdict = _get(fetch, f"/companies/{ticker}/forecast/{asset_id}/verdict",
                   scenario=scenario)
    detail = _soft(fetch, f"/companies/{ticker}/forecast/{asset_id}", scenario=scenario)
    out = {"verdict": _trim(verdict, rows=12, text=400, depth=4)}
    if isinstance(detail, dict) and "absent" not in detail:
        result = detail.get("result") or {}
        years, revenue = result.get("years") or [], result.get("revenue") or []
        out["assumptions"] = _pick(detail.get("assumptions"), ASSUMPTION_FIELDS,
                                   limit=40, text=220)
        out["unsourced_assumptions"] = _pick(detail.get("unsourced"), ASSUMPTION_FIELDS,
                                             limit=20, text=160)
        out["revenue_by_year"] = dict(zip(years, [round(v) if v is not None else None
                                                  for v in revenue]))
        out["probability_placement"] = _trim(result.get("pos_placement"), rows=10, text=400)
        out["bases"] = {k: _clip(str(result.get(k))) for k in
                        ("wacc_basis", "pos_basis", "loe_basis", "erosion_basis", "curve_basis")
                        if result.get(k)}
    else:
        out["detail"] = detail
    return out


WHATIF_LEVERS = ("volume", "price", "wacc", "pos", "growth", "terminal_growth", "loe_year",
                 "erosion")


def whatif(fetch, args):
    ticker, asset_id = _ticker(args), _asset(args)
    levers = {k: args.get(k) for k in WHATIF_LEVERS if args.get(k) is not None}
    if not levers:
        raise ToolError("give at least one lever to vary: " + ", ".join(WHATIF_LEVERS))
    got = _get(fetch, f"/companies/{ticker}/forecast/{asset_id}/whatif",
               scenario=args.get("scenario") or "base", **levers)

    def side(block):
        if not isinstance(block, dict):
            return block
        out = _flat(block)
        years, revenue = block.get("years") or [], block.get("revenue") or []
        peak = max((v for v in revenue if v is not None), default=None)
        out["peak_revenue"] = peak
        out["peak_year"] = years[revenue.index(peak)] if peak is not None else None
        return out

    base, varied = side(got.get("base")), side(got.get("varied"))
    change = None
    if isinstance(base, dict) and isinstance(varied, dict) and base.get("rnpv"):
        change = round(varied.get("rnpv", 0) / base["rnpv"] - 1, 4)
    return {"ticker": ticker, "asset_id": asset_id, "ok": got.get("ok"),
            "overrides": levers, "ignored": got.get("ignored") or {},
            "base": base, "varied": varied, "rnpv_change": change,
            "note": "Computed for this answer only; nothing in the book was changed. "
                    "rnpv is the asset's risk-adjusted value in the company's currency. "
                    "A lever named in ignored is one this asset's build does not read, "
                    "with the reason."}


def sensitivity(fetch, args):
    ticker, asset_id = _ticker(args), _asset(args)
    return _get(fetch, f"/companies/{ticker}/forecast/{asset_id}/sensitivity",
                scenario=args.get("scenario") or "base", preset=args.get("preset") or "price")


def breakpoints(fetch, args):
    ticker = _ticker(args)
    return _trim(_get(fetch, f"/companies/{ticker}/breakpoints"), rows=20, text=TEXT)


def gates(fetch, args):
    ticker = str(args.get("ticker") or "").strip().upper()
    odds = _get(fetch, "/gate-odds")
    if not ticker:
        return {"as_of": odds.get("as_of"), "regimes": odds.get("regimes"),
                "single_gate_names": _rows(odds.get("rows"), limit=60, text=300),
                "reason": odds.get("reason"),
                "reading": "p_book is the book's odds, p_mkt the odds the price implies "
                           "once the rest of the company is taken out. A p_mkt outside 0 "
                           "to 1 is a disagreement about what the asset is worth, which "
                           "the readout cannot settle."}
    stakes = _get(fetch, f"/companies/{ticker}/catalysts/stakes")
    mine = [r for r in odds.get("rows") or [] if r.get("ticker") == ticker]
    return {"ticker": ticker, "diluted_shares": stakes.get("diluted_shares"),
            "priced": _rows(stakes.get("priced"), limit=40, text=300, keep=("held",)),
            "unpriced": _rows(stakes.get("unpriced"), limit=40, text=300),
            "market_implied": _rows(mine, limit=10, text=300),
            "gate_odds_as_of": odds.get("as_of")}


def as_of(fetch, args):
    ticker = _ticker(args)
    day = str(args.get("date") or "").strip()
    if len(day) != 10:
        raise ToolError("date must be an ISO day, for example 2026-10-20")
    calls = _soft(fetch, f"/calls/{ticker}")
    held = [c for c in calls if isinstance(c, dict) and (c.get("as_of") or "") <= day] \
        if isinstance(calls, list) else []
    state = _soft(fetch, "/as-of", date=day)
    out = {"ticker": ticker, "date": day,
           "call_on_or_before": _flat(held[-1]) if held else None,
           "first_call_on_file": calls[0].get("as_of") if isinstance(calls, list) and calls else None}
    if isinstance(state, dict) and "absent" not in state:
        out["history_begins"] = state.get("history_begins")
        out["before_history"] = state.get("before_history")
        out["financials"] = (state.get("financials") or {}).get(ticker)
        out["approvals"] = _trim((state.get("by_ticker") or {}).get(ticker), rows=15, text=200)
    else:
        out["state"] = state
    out["note"] = ("The call is what the book recorded that day and has not been "
                   "recomputed. A date before the first call has no valuation on record, "
                   "and none can be reconstructed without hindsight.")
    return out


def why_moved(fetch, args):
    ticker = _ticker(args)
    start, end = args.get("start"), args.get("end")
    if not start or not end:
        raise ToolError("start and end are needed, as ISO days")
    return _trim(_get(fetch, f"/companies/{ticker}/why-moved", start=start, end=end),
                 rows=25, text=TEXT)


def track_record(fetch, args):
    log = _soft(fetch, "/theses")
    return {
        "calls": _soft(fetch, "/calls/scores"),
        "valuation": _trim(_soft(fetch, "/valuation-backtest"), rows=20),
        "events_before_moves": _trim(_soft(fetch, "/event-signal"), rows=20, text=400),
        "events_and_readouts": _trim(_soft(fetch, "/backtest"), rows=20),
        "theses": log.get("summary") if isinstance(log, dict) else None,
        "reading": "ic is the rank correlation between the upside the book stated and the "
                   "return over XBI that followed; independent_days is how many "
                   "non-overlapping observations it rests on. Few of either means no "
                   "claim can be made yet.",
    }


def street(fetch, args):
    ticker = _ticker(args)
    return {"street": _trim(_soft(fetch, f"/companies/{ticker}/street"), rows=20),
            "relative": _soft(fetch, f"/companies/{ticker}/relative")}


def runway(fetch, args):
    ticker = _ticker(args)
    got = _soft(fetch, f"/companies/{ticker}/runway")
    return {"runway": _trim(got, rows=12, text=300), "ticker": ticker,
            "note": "funded_to_readout says whether the cash lasts to the next dated "
                    "catalyst at the trailing burn; expected_raise is the modelled chance "
                    "of a raise inside twelve months"}


def revenue_at_risk(fetch, args):
    ticker = _ticker(args)
    excl = _soft(fetch, f"/companies/{ticker}/exclusivities")
    keep = ("asset_id", "brand_name", "generic_name", "modality", "loe", "loe_basis",
            "valued_loe", "valued_loe_basis", "valued_loe_past", "challenged",
            "challenge_date", "area")
    assets = [{k: r.get(k) for k in keep} for r in (excl.get("assets") or [])] \
        if isinstance(excl, dict) else excl
    return {"ticker": ticker,
            "by_year": _trim(_soft(fetch, f"/companies/{ticker}/revenue-at-risk"), rows=15),
            "exclusivities": assets,
            "ira": _trim(_soft(fetch, f"/companies/{ticker}/ira"), rows=10, text=200)}


EVIDENCE = {
    "trials": ("/companies/{t}/trials", "trials"),
    "readouts": ("/companies/{t}/readouts", "readouts"),
    "readout_reports": ("/companies/{t}/readout-reports", None),
    "filings": ("/companies/{t}/filings", "filings"),
    "filing_text": ("/companies/{t}/filing-text", "sections"),
    "label_changes": ("/companies/{t}/label-changes", "changes"),
    "news": ("/companies/{t}/news", "news"),
    "deals": ("/companies/{t}/deals", "deals"),
    "programmes": ("/companies/{t}/programmes", "programmes"),
    "competitors": ("/companies/{t}/competitors", "products"),
}


def evidence(fetch, args):
    ticker = _ticker(args)
    kind = str(args.get("kind") or "").strip().lower()
    if kind not in EVIDENCE:
        raise ToolError("kind must be one of: " + ", ".join(sorted(EVIDENCE)))
    path, key = EVIDENCE[kind]
    params = {}
    if kind == "trials" and args.get("phase"):
        params["phase"] = args["phase"]
    got = _get(fetch, path.format(t=ticker), **params)
    if key is None:
        return {"ticker": ticker, "kind": kind, **_trim(got, rows=30, text=TEXT)}
    rows = got.get(key) or []
    wanted = str(args.get("contains") or "").strip().lower()
    if wanted:
        rows = [r for r in rows if wanted in json.dumps(r, default=str).lower()]
    text = 2400 if kind == "filing_text" else TEXT
    limit = 8 if kind == "filing_text" else int(args.get("limit") or ROWS)
    return {"ticker": ticker, "kind": kind, "filter": wanted or None,
            **_rows(rows, limit=min(limit, 100), text=text)}


def indication(fetch, args):
    wanted = str(args.get("query") or "").strip().lower()
    if args.get("indication_id") is not None:
        ident = int(args["indication_id"])
        return {"overview": _trim(_soft(fetch, f"/indications/{ident}/overview"),
                                  rows=25, text=300),
                "landscape": _trim(_soft(fetch, f"/indications/{ident}/landscape"),
                                   rows=30, text=300)}
    if not wanted:
        raise ToolError("give a query to find an indication by name, or an indication_id")
    found = [r for r in _get(fetch, "/indications") if wanted in (r.get("name") or "").lower()]
    return {"query": wanted, **_rows(found, limit=25, keep=("tickers",)),
            "next": "call again with indication_id for who is in it and at what stage"}


def changes(fetch, args):
    ticker = str(args.get("ticker") or "").strip().upper() or None
    days = int(args.get("days") or 30)
    feed = _get(fetch, "/changes", days=days, ticker=ticker)
    out = {"ticker": ticker, "days": days, "feed": _rows(feed, limit=50, text=240)}
    if ticker:
        model = _soft(fetch, "/model-changes", ticker=ticker, limit=40)
        if isinstance(model, dict) and "absent" not in model:
            out["assumption_edits"] = {"count": model.get("count"),
                                       **_pick(model.get("changes"), EDIT_FIELDS,
                                               limit=20, text=200)}
    return out


def calendar(fetch, args):
    return _trim(_get(fetch, f"/companies/{_ticker(args)}/calendar",
                      days=args.get("days")), rows=60, text=300)


def base_rates(fetch, args):
    if args.get("asset_id") is not None:
        return _trim(_get(fetch, f"/base-rates/asset/{_asset(args)}"), rows=20, text=TEXT)
    if args.get("record"):
        return _get(fetch, "/base-rates/record")
    got = _get(fetch, "/base-rates", transition=args.get("transition"),
               cut=args.get("cut"), group=args.get("group"))
    return _trim(got, rows=140, text=200)


def comparable_readouts(fetch, args):
    ticker = str(args.get("ticker") or "").strip().upper() or None
    got = _get(fetch, "/comparable-readouts", ticker=ticker, phase=args.get("phase"),
               outcome=args.get("outcome"), engine=args.get("engine"),
               limit=args.get("limit") or 15)
    return _trim(got, rows=25, text=400)


def positioning(fetch, args):
    parts = args.get("parts")
    if isinstance(parts, list):
        parts = ",".join(str(p) for p in parts)
    return _trim(_get(fetch, f"/companies/{_ticker(args)}/positioning", parts=parts),
                 rows=20, text=300, depth=9)


INSIDER_FIELDS = ("transaction_date", "filed_date", "owner", "role", "code", "security",
                  "derivative", "shares", "price", "value", "shares_owned_after",
                  "ownership", "ownership_nature", "plan_10b5_1", "superseded_by",
                  "footnotes")


def insiders(fetch, args):
    got = _get(fetch, f"/companies/{_ticker(args)}/insiders", days=args.get("days"))
    lines = got.pop("transactions", None) if isinstance(got, dict) else None
    out = _trim(got, rows=20, text=300, depth=9)
    if isinstance(out, dict):
        # The summary is over every line in the window; the list is the newest of them,
        # each cut to what says who did what, since a footnote can run to a paragraph.
        out["transactions"] = _pick(lines, INSIDER_FIELDS, limit=30, text=140)
    return out


def holders(fetch, args):
    return _trim(_get(fetch, f"/companies/{_ticker(args)}/holders", top=args.get("top")),
                 rows=50, text=400)


def portfolio(fetch, args):
    got = _get(fetch, "/portfolio/mine")
    if not got.get("ok", True):
        return _trim(got, rows=10)
    return {"currency": got.get("currency"), "source": got.get("source"),
            "positions": _rows(got.get("rows"), limit=60, text=160),
            "exposure": _trim(got.get("exposure"), rows=12),
            "note": "The user's own holdings, read only. State exposure; do not advise "
                    "on any position."}


def theses(fetch, args):
    ticker = str(args.get("ticker") or "").strip().upper() or None
    return _trim(_get(fetch, "/theses", ticker=ticker), rows=40, text=TEXT)


THESIS_FIELDS = ("ticker", "side", "horizon_days", "claim", "rests_on", "wrong_if",
                 "asset_id", "catalyst_id", "supersedes", "author")


def log_thesis(fetch, args):
    body = {k: args.get(k) for k in THESIS_FIELDS if args.get(k) is not None}
    missing = [k for k in THESIS_FIELDS[:6] if k not in body]
    if missing:
        raise ToolError("a thesis needs: " + ", ".join(missing))
    try:
        status, payload = fetch("POST", "/theses", None, body)
    except Exception as exc:
        raise ToolError(f"the terminal's API did not answer: {exc}")
    if status >= 400:
        raise ToolError(f"the thesis was not logged: {_detail(payload) or status}")
    return {"logged": payload,
            "note": "On the record and cannot be edited. It is marked against XBI on its "
                    "due date; lens_theses shows the log."}


# --- the catalogue --------------------------------------------------------------------
def _schema(properties: dict, required: tuple = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


_T = {"type": "string", "description": "Company ticker as the book lists it, e.g. LLY, "
                                       "DYN, AZN. lens_universe lists them."}
_A = {"type": "integer", "description": "Asset id, from lens_company's assets."}
_SCENARIO = {"type": "string", "enum": ["bear", "base", "bull"],
             "description": "Forecast scenario; base where omitted."}
_DAY = {"type": "string", "description": "ISO day, YYYY-MM-DD."}

TOOLS = [
    {"name": "lens_universe", "title": "The universe", "handler": universe,
     "description": "Every company the book covers, with its engine (pharma, biotech, "
                    "cellgene), stage, revenue, late-stage trial count, catalysts in the "
                    "next twelve months and share of revenue losing exclusivity. The "
                    "starting point for finding tickers and for screening.",
     "schema": _schema({"engine": {"type": "string", "enum": ["pharma", "biotech", "cellgene"],
                                   "description": "Narrow to one engine."}})},
    {"name": "lens_company", "title": "One company", "handler": company,
     "description": "A company's fair value per share and rating, the lenses behind it, "
                    "every modelled asset with its id and risk-adjusted value, what the "
                    "model refused to value and why, and the cash runway. Slow the first "
                    "time for a company (it values the peer set), then cached.",
     "schema": _schema({"ticker": _T}, ("ticker",))},
    {"name": "lens_asset", "title": "One asset's forecast", "handler": asset,
     "description": "One asset's forecast: value per share, peak revenue, probability of "
                    "success and how it was placed, loss of exclusivity, the revenue "
                    "path by year, and every assumption with its source.",
     "schema": _schema({"ticker": _T, "asset_id": _A, "scenario": _SCENARIO},
                       ("ticker", "asset_id"))},
    {"name": "lens_whatif", "title": "What if", "handler": whatif,
     "description": "Recompute one asset's value with assumptions changed, beside the "
                    "base. Use it to test a hypothesis against the book's arithmetic: "
                    "what the asset is worth at different odds, price, volume, discount "
                    "rate or exclusivity date. Saves nothing.",
     "schema": _schema({
         "ticker": _T, "asset_id": _A, "scenario": _SCENARIO,
         "pos": {"type": "number", "description": "Probability of success, 0 to 1; "
                                                  "replaces the book's."},
         "wacc": {"type": "number", "description": "Discount rate, e.g. 0.09; replaces "
                                                   "the book's."},
         "volume": {"type": "number", "description": "Multiplier on the patient curve, or "
                                                     "on the published peak for a launch; "
                                                     "1 is the base."},
         "price": {"type": "number", "description": "Net price per patient, an amount "
                                                    "and not a multiplier. Only a "
                                                    "patient-built forecast reads it."},
         "growth": {"type": "number", "description": "Near-term growth rate, e.g. 0.05, "
                                                     "for a product anchored on reported "
                                                     "revenue."},
         "terminal_growth": {"type": "number", "description": "The long-run rate growth "
                                                              "fades to, e.g. 0.0."},
         "loe_year": {"type": "integer", "description": "Year exclusivity ends."},
         "erosion": {"type": "number", "description": "Share of revenue lost in the year "
                                                      "after exclusivity ends, 0 to 1."}},
         ("ticker", "asset_id"))},
    {"name": "lens_sensitivity", "title": "Sensitivity grid", "handler": sensitivity,
     "description": "A five by five grid of one asset's value across the discount rate "
                    "and the input its revenue is built from, or across the exclusivity "
                    "year and erosion. Shows which assumption the value hangs on.",
     "schema": _schema({"ticker": _T, "asset_id": _A, "scenario": _SCENARIO,
                        "preset": {"type": "string", "enum": ["price", "loe"],
                                   "description": "price: rate against the revenue "
                                                  "input. loe: exclusivity year against "
                                                  "erosion."}},
                       ("ticker", "asset_id"))},
    {"name": "lens_breakpoints", "title": "What the price requires", "handler": breakpoints,
     "description": "For one company, how far each single assumption would have to move "
                    "for the book's value to equal the share price. Says what the market "
                    "would have to believe.",
     "schema": _schema({"ticker": _T}, ("ticker",))},
    {"name": "lens_gates", "title": "Readouts priced as gates", "handler": gates,
     "description": "With no ticker: every stock where one readout swings a fifth or more "
                    "of its value, with the book's odds beside the odds the share price "
                    "implies. With a ticker: each of that company's dated catalysts with "
                    "its odds and the value per share if it passes and if it fails.",
     "schema": _schema({"ticker": {**_T, "description": "Omit for the universe-wide table "
                                                        "of single-gate names."}})},
    {"name": "lens_as_of", "title": "The book on a past date", "handler": as_of,
     "description": "What the book said about a company on a past day: the fair value, "
                    "rating and upside it recorded then, and the financials and approvals "
                    "it knew. Use it to test an idea without hindsight.",
     "schema": _schema({"ticker": _T, "date": _DAY}, ("ticker", "date"))},
    {"name": "lens_why_moved", "title": "Why a value moved", "handler": why_moved,
     "description": "Why the book's value for a company changed between two days: the "
                    "market, the analyst's edits, the data underneath or the model, and "
                    "what held still.",
     "schema": _schema({"ticker": _T, "start": _DAY, "end": _DAY},
                       ("ticker", "start", "end"))},
    {"name": "lens_track_record", "title": "How the book has scored", "handler": track_record,
     "description": "How the book's recorded calls have done against XBI so far, beside "
                    "the street's targets; how its gate odds are calibrated; what price "
                    "did around past readouts and other events; and the thesis log's "
                    "record. Read this before leaning on any signal.",
     "schema": _schema({})},
    {"name": "lens_street", "title": "The street and relative price", "handler": street,
     "description": "Consensus estimates against the model's own figures for one "
                    "company, and its share price against the benchmark over one month, "
                    "three months and a year.",
     "schema": _schema({"ticker": _T}, ("ticker",))},
    {"name": "lens_runway", "title": "Cash runway", "handler": runway,
     "description": "Cash, burn, months of runway, the day the cash runs out, whether it "
                    "lasts to the next dated catalyst, and the modelled chance of a raise.",
     "schema": _schema({"ticker": _T}, ("ticker",))},
    {"name": "lens_revenue_at_risk", "title": "Revenue at risk", "handler": revenue_at_risk,
     "description": "Revenue losing exclusivity by year, each product's exclusivity date "
                    "with its basis and any patent challenge, and Medicare price "
                    "negotiation exposure.",
     "schema": _schema({"ticker": _T}, ("ticker",))},
    {"name": "lens_evidence", "title": "The record behind a figure", "handler": evidence,
     "description": "The primary record for one company: trials on the registry, "
                    "readouts read from filings, results reported in the last weeks, "
                    "filings, filing text, label changes, news, deals, development "
                    "programmes or competing products. Result sentences are verbatim "
                    "with their source.",
     "schema": _schema({
         "ticker": _T,
         "kind": {"type": "string", "enum": sorted(EVIDENCE),
                  "description": "Which record to read."},
         "phase": {"type": "string", "description": "For trials: a phase, e.g. Phase 3."},
         "contains": {"type": "string", "description": "Keep only rows mentioning this "
                                                       "text, e.g. a drug name or an NCT "
                                                       "number."},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                   "description": "Rows to return, 40 where omitted."}},
         ("ticker", "kind"))},
    {"name": "lens_indication", "title": "An indication's landscape", "handler": indication,
     "description": "Find an indication by name, or with an indication_id see every "
                    "asset in it across the universe: whose, at what stage, against "
                    "which comparators.",
     "schema": _schema({"query": {"type": "string", "description": "Part of an "
                                                                   "indication's name."},
                        "indication_id": {"type": "integer",
                                          "description": "From a previous query."}})},
    {"name": "lens_changes", "title": "What changed", "handler": changes,
     "description": "The change feed: what the book detected in the last days (trial "
                    "status and date changes, filings, approvals, label changes), for "
                    "one company or the universe, and for one company the edits made to "
                    "its assumptions.",
     "schema": _schema({"ticker": {**_T, "description": "Omit for the whole universe."},
                        "days": {"type": "integer", "minimum": 1, "maximum": 365,
                                 "description": "How far back; 30 where omitted."}})},
    {"name": "lens_calendar", "title": "Every date ahead", "handler": calendar,
     "description": "Every dated event ahead of one company in date order: readouts and "
                    "regulatory dates with the registry's date and the company's guided "
                    "date side by side, advisory committees, exclusivity losses and the "
                    "day the cash runs out.",
     "schema": _schema({"ticker": _T,
                        "days": {"type": "integer", "minimum": 1, "maximum": 1825,
                                 "description": "Window ahead; 365 where omitted."}},
                       ("ticker",))},
    {"name": "lens_base_rates", "title": "Base rates", "handler": base_rates,
     "description": "The published phase transition success rates the book's odds are "
                    "built from, by therapeutic area, modality and other cuts, each with "
                    "its sample size. With asset_id: how one asset was placed and the "
                    "odds either side of its next readout. With record: how the book's "
                    "own tracked catalysts resolved.",
     "schema": _schema({
         "transition": {"type": "string",
                        "enum": ["p1_to_p2", "p2_to_p3", "p3_to_nda", "nda_to_approval"],
                        "description": "One phase transition."},
         "cut": {"type": "string",
                 "enum": ["area", "modality", "oncology", "prevalence", "biomarker"],
                 "description": "One way the study cuts its rates."},
         "group": {"type": "string", "description": "Part of a group name, e.g. Oncology "
                                                    "or Peptide."},
         "asset_id": _A,
         "record": {"type": "boolean", "description": "True for the book's own record."}})},
    {"name": "lens_comparable_readouts", "title": "Comparable readouts",
     "handler": comparable_readouts,
     "description": "Past readouts one row each with the verbatim result and the share "
                    "price's move against XBI before and after, for companies on the same "
                    "engine, with a median by outcome. With a ticker, that company's own "
                    "past readouts are returned apart from its comparables.",
     "schema": _schema({
         "ticker": {**_T, "description": "Compare against this company's engine and list "
                                         "its own readouts apart."},
         "phase": {"type": "integer", "enum": [2, 3], "description": "Phase 2 or 3."},
         "outcome": {"type": "string", "enum": ["positive", "negative"],
                     "description": "Keep one outcome."},
         "engine": {"type": "string", "enum": ["pharma", "biotech", "cellgene"],
                    "description": "Compare against one engine's companies."},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                   "description": "Readouts to list; 15 where omitted. The summary "
                                  "covers all of them either way."}})},
    {"name": "lens_positioning", "title": "How the market is positioned",
     "handler": positioning,
     "description": "Four reads side by side for one stock: short interest, the move the "
                    "options chain prices against the move the model's legs imply for "
                    "each catalyst, insider dealing and institutional holders. Short "
                    "interest and options are read live and may be absent.",
     "schema": _schema({"ticker": _T,
                        "parts": {"type": "array",
                                  "items": {"type": "string",
                                            "enum": ["short", "options", "insiders",
                                                     "holders"]},
                                  "description": "A subset; all four where omitted."}},
                       ("ticker",))},
    {"name": "lens_insiders", "title": "Insider transactions", "handler": insiders,
     "description": "Form 4 transactions by a company's officers and directors: open "
                    "market purchases and sales apart from awards, exercises and tax "
                    "withholding, with sales under a pre-arranged plan flagged.",
     "schema": _schema({"ticker": _T,
                        "days": {"type": "integer", "minimum": 1, "maximum": 730,
                                 "description": "Window back; 180 where omitted."}},
                       ("ticker",))},
    {"name": "lens_holders", "title": "Institutional holders", "handler": holders,
     "description": "Who held the stock at the last 13F quarter end, the change from the "
                    "quarter before (new, added, cut, sold out) and how concentrated the "
                    "holding is. Long positions of large managers only, filed up to 45 "
                    "days after the quarter.",
     "schema": _schema({"ticker": _T,
                        "top": {"type": "integer", "minimum": 1, "maximum": 50,
                                "description": "Holders to list; 15 where omitted."}},
                       ("ticker",))},
    {"name": "lens_portfolio", "title": "The user's own holdings", "handler": portfolio,
     "description": "The user's own positions from their broker, read only, with "
                    "exposure by theme and concentration. For stating exposure to a "
                    "name or an event, never for advising on a position.",
     "schema": _schema({})},
    {"name": "lens_theses", "title": "The thesis log", "handler": theses,
     "description": "Every thesis on the record with how it was marked against XBI, and "
                    "the log's hit rate so far.",
     "schema": _schema({"ticker": {**_T, "description": "Omit for the whole log."}})},
    {"name": "lens_log_thesis", "title": "Put a thesis on the record",
     "handler": log_thesis, "writes": True,
     "description": "Append a dated, falsifiable thesis to the log so it can be marked "
                    "later. Append-only: it cannot be edited or removed. Use only when "
                    "the user asks for a read to be recorded. The starting price is "
                    "taken from the book, not from you.",
     "schema": _schema({
         "ticker": _T,
         "side": {"type": "string", "enum": ["outperform", "underperform"],
                  "description": "Against XBI over the horizon."},
         "horizon_days": {"type": "integer", "minimum": 5, "maximum": 730,
                          "description": "Days until it is marked."},
         "claim": {"type": "string", "description": "The claim, in a sentence."},
         "rests_on": {"type": "string", "description": "What in the book it rests on, "
                                                       "with the figures."},
         "wrong_if": {"type": "string", "description": "What would show it was wrong, "
                                                       "stated before the outcome."},
         "asset_id": _A,
         "catalyst_id": {"type": "integer", "description": "The catalyst it turns on, "
                                                           "from lens_gates."},
         "supersedes": {"type": "integer", "description": "The id of an earlier thesis "
                                                          "this replaces."},
         "author": {"type": "string", "description": "Who or what made the read, e.g. "
                                                     "the model's name."}},
         ("ticker", "side", "horizon_days", "claim", "rests_on", "wrong_if"))},
]

BY_NAME = {tool["name"]: tool for tool in TOOLS}


def catalogue() -> list:
    """The tools as a client lists them: no handlers, and whether each one writes."""
    return [{"name": t["name"], "title": t["title"], "description": t["description"],
             "input_schema": t["schema"], "read_only": not t.get("writes", False)}
            for t in TOOLS]


def call(name: str, arguments: dict | None, fetch) -> dict:
    """Run one tool. Raises ``ToolError`` with a sentence the caller can act on."""
    tool = BY_NAME.get(name)
    if tool is None:
        raise ToolError(f"there is no tool {name}; the tools are: "
                        + ", ".join(sorted(BY_NAME)))
    args = dict(arguments or {})
    unknown = sorted(set(args) - set(tool["schema"]["properties"]))
    if unknown:
        raise ToolError(f"{name} does not take {', '.join(unknown)}; it takes: "
                        + (", ".join(tool["schema"]["properties"]) or "no arguments"))
    missing = [k for k in tool["schema"]["required"] if args.get(k) in (None, "")]
    if missing:
        raise ToolError(f"{name} needs {', '.join(missing)}")
    return _fit(tool["handler"](fetch, args))
