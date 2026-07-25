"""One-page company tearsheet, print-styled to A4, written to exports/.

This is the artefact that gets pasted into a real note, so it is self-contained:
the SVG charts are the same pure primitives the terminal renders, inlined, and the
stylesheet ships in the file. It carries the price line, the financial snapshot, the
next five catalysts, the LOE cliff, the current note with the change ids behind it,
and the source caveats, under a generated timestamp.

Nothing here is imputed. A field with no data prints "no free data", exactly as the
terminal shows it, because a tearsheet that rounds a gap to zero is worse than one
that admits the gap.
"""

from __future__ import annotations

import datetime as dt
import html
import sys
from pathlib import Path

import asset_revenue
import catalysts as catalysts_module
import comps as comps_module
import db
import financials_view
import insights
import loe as loe_module
import whatchanged

# The chart primitives and tokens are pure (no Streamlit), shared with the frontend.
_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if str(_FRONTEND) not in sys.path:
    sys.path.insert(0, str(_FRONTEND))
from components import charts as CH  # noqa: E402
from components import tokens as TK  # noqa: E402

EXPORTS_DIR = Path(__file__).resolve().parent.parent / "exports"


def _num(value, decimals=1, dash="—"):
    if value is None or value != value:
        return dash
    text = f"{abs(value):,.{decimals}f}"
    return f"{'−' if value < 0 else ''}{text}"


def _company(conn, ticker):
    return conn.execute(
        "SELECT id, name, is_sec_filer, is_foreign_private_issuer FROM companies"
        " WHERE ticker = ?", (ticker,)).fetchone()


def _price_line(conn, company_id, ticker):
    rows = conn.execute(
        "SELECT close FROM prices WHERE company_id = ? AND interval = '1d'"
        " AND as_of >= date('now', '-365 days') ORDER BY as_of", (company_id,)
    ).fetchall()
    closes = [r["close"] for r in rows]
    if len(closes) > 180:
        step = len(closes) / 180
        closes = [closes[int(i * step)] for i in range(180)]
    if len(closes) < 2:
        return "<p class='empty'>No price history on file.</p>"
    return CH.line_chart([{"name": ticker, "values": closes, "colour": TK.UP}],
                         [""] * len(closes), 760, 200,
                         y_fmt=lambda v: _num(v, 0), hover=False)


def _snapshot_block(ticker, db_path=None) -> str:
    built = financials_view.build_statements(db_path, ticker, basis="quarterly")
    if not built or not built.get("snapshot"):
        built = financials_view.build_statements(db_path, ticker, basis="annual")
    snap = built.get("snapshot") if built else None
    if not snap:
        return "<p class='empty'>No SEC financials on file.</p>"
    currency = snap.get("currency") or ""

    def money(v):
        return _num(v / 1e9, 2) if v is not None else "no free data"

    cells = [
        ("Revenue", f"{money(snap['revenue'])} {currency}bn"),
        ("Net income", f"{money(snap['net_income'])} {currency}bn"),
        ("EPS diluted", _num(snap["eps_diluted"], 2)),
        ("R&D intensity", (f"{_num(snap['rd_intensity'] * 100, 1)}%"
                           if snap.get("rd_intensity") is not None else "no free data")),
    ]
    label = html.escape(snap.get("label") or "")
    tiles = "".join(
        f'<div class="tile"><span class="k">{html.escape(k)}</span>'
        f'<span class="v">{html.escape(v)}</span></div>' for k, v in cells)
    return f'<div class="tiles">{tiles}</div><p class="sub">Latest reported: {label}</p>'


def _catalysts_block(ticker, db_path=None) -> str:
    rows = catalysts_module.list_catalysts(db_path, within_days=540, ticker=ticker)[:5]
    if not rows:
        return "<p class='empty'>No dated catalysts inside 18 months.</p>"
    items = "".join(
        f'<li><span class="d">{html.escape(c["expected_date"])}</span> '
        f'<span class="ty">{html.escape(c["catalyst_type"])}</span> '
        f'{html.escape((c.get("title") or "")[:88])}'
        f'{"" if c.get("is_curated") else " <span class=flag>uncurated</span>"}</li>'
        for c in rows)
    return f'<ul class="cat">{items}</ul>'


def _loe_block(ticker, db_path=None) -> str:
    data = loe_module.build_loe(db_path)
    mine = next((r for r in data["rows"] if r["ticker"] == ticker), None)
    if not mine:
        return "<p class='empty'>No US exclusivity on file.</p>"
    year_cols = [str(y) for y in data["years"]] + [data["later_label"]]
    counts = {str(y): mine["years"].get(str(y), 0) for y in data["years"]}
    counts[data["later_label"]] = mine["later"]
    if sum(counts.values()) == 0:
        return "<p class='empty'>No US products lose exclusivity in the window.</p>"
    return CH.bar_chart([{"label": c, "value": counts[c], "show_value": counts[c] > 0}
                         for c in year_cols], 760, 190,
                        value_fmt=lambda v: f"{v:.0f}")


def _note_block(ticker, db_path=None) -> str:
    note = insights.latest_note(db_path, ticker)
    if not note or not note.get("body"):
        return ("<p class='empty'>No note generated yet. The rules layer builds one "
                "from the feed on demand.</p>", [])
    body = html.escape(note["body"]).replace("\n", "<br>")
    ids = note.get("source_change_ids") or []
    return f'<div class="note">{body}</div>', ids


_CSS = """
:root { --ink:#12201f; --muted:#5b6b6a; --rule:#d5ddda; --up:#3f7f63;
        --down:#b4472f; --flag:#a67c22; --panel:#f4f6f4; }
* { box-sizing:border-box; }
body { font-family:'Archivo',system-ui,sans-serif; color:var(--ink);
       margin:0; padding:0; background:#fff; font-size:11px; }
.sheet { width:210mm; min-height:297mm; padding:14mm 14mm 12mm; margin:0 auto; }
.head { display:flex; justify-content:space-between; align-items:baseline;
        border-bottom:2px solid var(--ink); padding-bottom:6px; }
.head .nm { font-size:19px; font-weight:700; letter-spacing:-0.02em; }
.head .tk { font-family:'IBM Plex Mono',monospace; font-size:13px; color:var(--muted); }
.head .meta { font-size:10px; color:var(--muted); text-align:right; }
h2 { font-size:10px; text-transform:uppercase; letter-spacing:0.09em;
     color:var(--muted); border-bottom:1px solid var(--rule); padding-bottom:3px;
     margin:14px 0 7px; }
.row { display:flex; gap:14px; }
.col { flex:1; min-width:0; }
.tiles { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }
.tile { border:1px solid var(--rule); padding:6px 8px; }
.tile .k { display:block; font-size:8.5px; text-transform:uppercase;
           letter-spacing:0.06em; color:var(--muted); }
.tile .v { font-family:'IBM Plex Mono',monospace; font-size:14px; font-weight:600; }
.sub { font-size:9px; color:var(--muted); margin:5px 0 0; }
.cat { list-style:none; margin:0; padding:0; }
.cat li { padding:3px 0; border-bottom:1px solid var(--rule); line-height:1.35; }
.cat .d { font-family:'IBM Plex Mono',monospace; color:var(--muted);
          margin-right:6px; }
.cat .ty { text-transform:uppercase; font-size:8.5px; letter-spacing:0.05em;
           color:var(--up); margin-right:5px; }
.flag { color:var(--flag); font-weight:600; text-transform:uppercase;
        font-size:8px; }
.note { font-family:'Newsreader',Georgia,serif; font-size:12.5px; line-height:1.55;
        max-width:64ch; }
.ids { font-family:'IBM Plex Mono',monospace; font-size:8.5px; color:var(--muted);
       margin-top:5px; }
.empty { color:var(--muted); font-style:italic; font-size:10px; }
.caveats { margin-top:14px; border-top:1px solid var(--rule); padding-top:6px;
           font-size:8.5px; color:var(--muted); line-height:1.5; }
svg { max-width:100%; height:auto; }
@page { size:A4; margin:0; }
@media print { .sheet { margin:0; } }
"""


def build(ticker: str, out_dir: Path | None = None, db_path=None) -> Path:
    """Write one company's tearsheet and return the path."""
    ticker = ticker.upper()
    out_dir = out_dir or EXPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection(db_path)
    try:
        company = _company(conn, ticker)
        if company is None:
            raise ValueError(f"unknown ticker {ticker}")
        comp = next((c for c in comps_module.build_comps(db_path)
                     if c["ticker"] == ticker), {})
        price_svg = _price_line(conn, company["id"], ticker)
    finally:
        conn.close()

    at_risk = asset_revenue.build_revenue_at_risk(db_path, ticker)
    note_html, change_ids = _note_block(ticker, db_path)
    filer = ("not an SEC filer" if not company["is_sec_filer"]
             else "20-F filer" if company["is_foreign_private_issuer"] else "10-K filer")
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    share_5y = (f"{_num(at_risk['share_5y'] * 100, 1)}% of tagged revenue"
                if at_risk and at_risk.get("share_5y") is not None else "no free data")

    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{html.escape(ticker)} tearsheet</title><style>{_CSS}</style></head>
<body><div class="sheet">
  <div class="head">
    <div><span class="nm">{html.escape(comp.get('name') or company['name'])}</span>
      &nbsp;<span class="tk">{html.escape(ticker)}</span></div>
    <div class="meta">{filer} · generated {generated}<br>
      equity research terminal, free-data build</div>
  </div>

  <h2>Price, last 12 months</h2>
  {price_svg}

  <div class="row">
    <div class="col">
      <h2>Financial snapshot</h2>
      {_snapshot_block(ticker, db_path)}
    </div>
    <div class="col">
      <h2>Loss of exclusivity, US products per year</h2>
      {_loe_block(ticker, db_path)}
      <p class="sub">At risk inside 5y: {share_5y}. US only.</p>
    </div>
  </div>

  <h2>Next five catalysts</h2>
  {_catalysts_block(ticker, db_path)}

  <h2>Current note</h2>
  {note_html}
  <div class="ids">Evidence: {('changes ' + ', '.join(str(i) for i in change_ids))
                              if change_ids else 'rules layer, no change ids'}</div>

  <div class="caveats">
    Loss-of-exclusivity dates are US only, from the FDA Orange and Purple Books;
    a product protected in the US can face a generic abroad years earlier.
    Biologics carry regulatory exclusivity, not patents. Product revenue is only
    what the filing tags; a dash or "no free data" is an absent figure, never zero.
    Nothing on this sheet is estimated.
  </div>
</div></body></html>"""

    path = out_dir / f"{ticker}_tearsheet.html"
    path.write_text(doc, encoding="utf-8")
    return path


def build_all(out_dir: Path | None = None, db_path=None) -> dict:
    """Write a tearsheet for every company. Returns paths written and any that
    failed, so a batch run reports honestly rather than aborting on one bad name."""
    conn = db.get_connection(db_path)
    try:
        tickers = [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM companies ORDER BY ticker")]
    finally:
        conn.close()
    written, failed = [], []
    for ticker in tickers:
        try:
            written.append(str(build(ticker, out_dir, db_path)))
        except Exception as exc:                    # one bad sheet never stops the run
            failed.append({"ticker": ticker, "error": f"{type(exc).__name__}: {exc}"})
    return {"written": written, "failed": failed, "count": len(written)}


if __name__ == "__main__":
    import json as _json
    result = build_all()
    print(_json.dumps({"count": result["count"],
                       "failed": result["failed"]}, indent=2))
