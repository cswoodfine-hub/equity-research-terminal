"""The Comps tab's Disease areas view: the builders, pure functions of the payload.

``GET /areas`` lists the areas the big pharma cohort is present in; ``GET /areas/{slug}``
is one area's page (backend/disease_areas.py states every rule). The page is laid out as
an indication's overview: a head line with the area and the two pop-outs, a row of the
area's figures, the area scorecard (a chart of value today against pipeline beside the
ranked table) and one row of finding cards, the last the selected company's position.

The markup reuses the indication overview's classes (``pos land-pos``, ``land
sc-table``, ``sc-cards``, ``vc``, ``sc-why``, ``how-read sc-how``), so the two views read
as one. Nothing here reads a network, a clock or Streamlit, and a missing figure prints
"no free data" or says why it is absent: it is never drawn as a zero.
"""

from __future__ import annotations

import html
import re

NO_DATA = "no free data"
PILLARS = (("value", "value today"), ("pipeline", "pipeline"),
           ("durability", "durability"), ("clinical", "clinical quality"))
# A card holds its text inside its box (theme.py, .sc-cards): the title on one line, a
# headline of two and a detail of three at the narrowest the row is drawn (1366 wide).
CARD_TITLE_MAX = 30
CARD_HEAD_MAX = 74
CARD_DETAIL_MAX = 132

_CO_SUFFIX = re.compile(r"\s*(,?\s*(PLC|plc|Inc\.?|AG|A/S|SA|S\.A\.|SE|N\.V\.|Ltd\.?|"
                        r"& Co\.?|Corporation|Corp\.?|Company|Holdings?|Co\.?))+$")


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def short_name(name: str | None, fallback: str = "") -> str:
    """The company without its legal suffix: "Eli Lilly and Company" is "Eli Lilly"."""
    text = re.sub(r"\s+(and|&)$", "", _CO_SUFFIX.sub("", name or "").strip())
    return text or fallback or (name or "")


def cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def money(bn) -> str:
    """$12.3bn, $0.45bn, or no free data. A negative value keeps its sign."""
    if bn is None:
        return NO_DATA
    sign = "−" if bn < 0 else ""
    v = abs(bn)
    return f"{sign}${v:,.1f}bn" if v >= 1 else f"{sign}${v:,.2f}bn"


def pct(share, digits: int = 0) -> str:
    return NO_DATA if share is None else f"{share * 100:.{digits}f}%"


def score(value) -> str:
    return NO_DATA if value is None else f"{value:.0f}"


def marketed_text(r: dict) -> str:
    """What a company markets in the area, in words: nothing marketed is a fact and is
    said, never printed as $0."""
    v = r.get("value") or {}
    if v.get("basis") == "none marketed":
        return "nothing marketed"
    if v.get("usd_bn") is None:
        return "marketed value no free data"
    return f'{money(v["usd_bn"])} marketed'


def pipeline_text(r: dict) -> str:
    p = r.get("pipeline") or {}
    if not p.get("assets"):
        return "no pipeline"
    if p.get("usd_bn") is None:
        return "pipeline value no free data"
    return f'{money(p["usd_bn"])} pipeline'


# --- the head ------------------------------------------------------------------------
def area_options(index: list, ticker: str) -> list:
    """The area slugs in selector order: the selected company's own areas first, where it
    has the most assets first, then the rest most companies first, as the index ranks
    them."""
    held = lambda a: (a.get("assets_by_ticker") or {}).get(ticker, 0)
    mine = [a["slug"] for a in sorted(
        (a for a in index if ticker in (a.get("tickers") or [])), key=lambda a: -held(a))]
    return mine + [a["slug"] for a in index if a["slug"] not in mine]


def figure_cells(page: dict, ticker: str) -> list:
    """The area's figures under the head line as (key, value, sub) triples."""
    t = page.get("totals") or {}
    present = any(r.get("ticker") == ticker for r in page.get("companies") or [])
    end = page.get("horizon_end")
    return [
        ("companies", str(t.get("companies", 0)), f'{ticker} {"in it" if present else "not in it"}'),
        ("marketed", str(t.get("marketed", 0)), "products, by brand"),
        ("phase 3 or filed", str(t.get("late", 0)), f'{t.get("filed", 0)} filed'),
        ("phase 2", str(t.get("phase2", 0)), "unmarketed assets"),
        ("risked value", money(t.get("risked_usd_bn")),
         f'{money(t.get("value_usd_bn"))} marketed, {money(t.get("pipeline_usd_bn"))} pipeline'),
        (f"loses exclusivity by {end}", money(t.get("at_risk_usd_bn")),
         f'{pct(t.get("at_risk_share"))} of revenue on file'),
        ("readouts in 24 months", str(t.get("readouts", 0)),
         f'{money(t.get("stake_usd_bn"))} at stake in {t.get("priced_readouts", 0)} priced'
         if t.get("stake_usd_bn") is not None else "none priced"),
    ]


def figures_html(cells: list) -> str:
    return ('<div class="pos land-pos">' + "".join(
        f'<span><span class="k">{esc(k)}</span><span class="v">{esc(v)}</span>'
        f'<span class="sub">{esc(sub)}</span></span>' for k, v, sub in cells) + "</div>")


# --- the chart -----------------------------------------------------------------------
def tip(r: dict) -> str:
    """A bubble's hover: the company, its rank and overall, then each pillar."""
    s = r.get("scores") or {}
    parts = ", ".join(f"{label} {score(s.get(key))}" for key, label in PILLARS)
    head = (f'{short_name(r.get("name"), r["ticker"])} ({r["ticker"]}), rank {r["rank"]}, '
            f'overall {r["overall"]:.0f} on {r["pillars"]} of 4 pillars: '
            if r.get("overall") is not None else f'{r["ticker"]}: ')
    return head + parts + f". {cap(marketed_text(r))}, {pipeline_text(r)}."


def map_points(rows: list) -> list:
    """One bubble a company with a value today and a pipeline score: value across,
    pipeline up, sized by clinical quality, solid when all four pillars are scored."""
    out = []
    for r in rows:
        s = r.get("scores") or {}
        if s.get("value") is None or s.get("pipeline") is None:
            continue
        out.append({"ticker": r["ticker"], "x": s["value"], "y": s["pipeline"],
                    "size": s.get("clinical"), "rank": r.get("rank"),
                    "complete": r.get("pillars") == 4, "tip": tip(r)})
    return out


def off_chart(rows: list) -> list:
    """The companies the chart cannot place, each with the pillar it lacks."""
    out = []
    for r in rows:
        s = r.get("scores") or {}
        missing = [label for key, label in PILLARS[:2] if s.get(key) is None]
        if missing:
            out.append(f'{short_name(r.get("name"), r["ticker"])} ({r["ticker"]}): '
                       f'no {" or ".join(missing)} score')
    return out


# --- the table -----------------------------------------------------------------------
def _score_cell(value, focal: bool, why: str = "") -> str:
    if value is None:
        return f'<td class="n m ar-nd" title="{esc(why or NO_DATA)}">{NO_DATA}</td>'
    return (f'<td class="n"><span class="sc{" sc-f" if focal else ""}">'
            f'<i style="width:{max(0.0, min(100.0, value)):.0f}%"></i></span>{value:.0f}</td>')


def _raw_cell(text, why: str = "", plain: bool = False) -> str:
    if text in (None, ""):
        return f'<td class="n m ar-nd" title="{esc(why or NO_DATA)}">{NO_DATA}</td>'
    cls = "n m ar-nd" if plain else "n"
    hover = f' title="{esc(why)}"' if why else ""
    return f'<td class="{cls}"{hover}>{esc(text)}</td>'


def table_html(rows: list, ticker: str, horizon_end) -> str:
    """The ranked table: rank, company, overall with its pillar count, the four pillar
    scores, then the raw figures behind them, which the table scrolls sideways to."""
    body = ""
    for r in rows:
        focal = r["ticker"] == ticker
        s = r.get("scores") or {}
        v, p, d, c = (r.get(k) or {} for k in ("value", "pipeline", "durability", "clinical"))
        name = esc(short_name(r.get("name"), r["ticker"]))
        name = f"<b>{name}</b>" if focal else name
        ov = r.get("overall")
        overall = (f'<td class="n m ar-nd">{NO_DATA}</td>' if ov is None else
                   f'<td class="n"><span class="sc{" sc-f" if focal else ""}"><i style="width:'
                   f'{max(0.0, min(100.0, ov)):.0f}%"></i></span>{ov:.0f}'
                   f'<span class="ar-pc" title="pillars scored">{r.get("pillars", 0)}/4</span>'
                   f'</td>')
        # Value today: none marketed is a fact, not a zero to print.
        if v.get("basis") == "none marketed":
            value_raw = _raw_cell("none marketed", "nothing marketed in this area", plain=True)
        else:
            value_raw = _raw_cell(None if v.get("usd_bn") is None else money(v["usd_bn"]),
                                  v.get("basis") or "")
        if p.get("assets") == 0:
            pipe_raw = _raw_cell("none", "no unmarketed asset in this area", plain=True)
        else:
            pipe_raw = _raw_cell(None if p.get("usd_bn") is None else money(p["usd_bn"]),
                                 "no pipeline asset here carries a model value")
        late = p.get("late") or []
        filed = sum(1 for a in late if a.get("stage") == "Filed")
        risk_tip = "; ".join(f'{x["name"]} {x["loe"][:4]}' for x in d.get("products") or [])
        body += (
            f'<tr class="{"sc-mine" if focal else ""}">'
            f'<td class="n m sc-rk">{r.get("rank") or ""}</td>'
            f'<td title="{esc(r.get("name") or r["ticker"])}">{name} '
            f'<span class="m">{esc(r["ticker"])}</span></td>'
            + overall
            + _score_cell(s.get("value"), focal, v.get("basis") or "")
            + _score_cell(s.get("pipeline"), focal)
            + _score_cell(s.get("durability"), focal, "no revenue on file in this area")
            + _score_cell(s.get("clinical"), focal, "no drug scored on an indication here")
            + value_raw
            + _raw_cell(None if v.get("share") is None else pct(v["share"]),
                        "no modelled product in this area")
            + pipe_raw
            + _raw_cell(str(p.get("depth", 0)) + (f" ({filed} filed)" if filed else ""),
                        ", ".join(a["name"] for a in late))
            + _raw_cell(None if d.get("share") is None else pct(d["share"]),
                        risk_tip or ("no revenue on file in this area"
                                     if d.get("share") is None else
                                     f"nothing on file loses exclusivity by {horizon_end}"))
            + _raw_cell(str(len(c.get("drugs") or [])),
                        ", ".join(f'{x["name"]} {x["mean"]:.0f}' for x in c.get("drugs") or []))
            + "</tr>")
    head = ('<th>#</th><th>company</th>'
            '<th title="Mean of the pillars it has, and how many">overall</th>'
            '<th title="Risked value of its marketed products here">value today</th>'
            '<th title="Risked pipeline value and Phase 3 or filed depth">pipeline</th>'
            '<th title="Less revenue losing exclusivity within 5 years scores higher">'
            'durability</th>'
            '<th title="Mean indication score of its scored drugs here">clinical</th>'
            '<th class="sc-reg" title="Risked value of marketed products, USD">value</th>'
            '<th class="sc-reg" title="This area\'s share of the company\'s product value">'
            'of co.</th>'
            '<th class="sc-reg" title="Risked value of unmarketed assets, USD">pipeline</th>'
            '<th class="sc-reg" title="Unmarketed assets in Phase 3 or filed">P3, filed</th>'
            f'<th class="sc-reg" title="Share of its revenue here losing exclusivity by '
            f'{horizon_end}">at risk</th>'
            '<th class="sc-reg" title="Drugs scored on an indication scorecard here">scored</th>')
    return ('<div class="land-wrap"><table class="land sc-table ar-table"><thead><tr>'
            f'{head}</tr></thead><tbody>{body}</tbody></table></div>')


# --- the pop-outs --------------------------------------------------------------------
def method_html(method: dict, off: list) -> str:
    """How it is scored: one labelled line a pillar, the scale and the overall, how a
    product is placed, then who is not on the chart."""
    parts = [("Value today", method.get("value")), ("Pipeline", method.get("pipeline")),
             ("Durability", method.get("durability")),
             ("Clinical quality", method.get("clinical"))]
    body = "".join(f'<div><span class="k">{k}:</span> {esc(v)}</div>' for k, v in parts if v)
    rest = "".join(f"<div>{esc(method[k])}</div>" for k in
                   ("scale", "overall", "assignment", "currency", "readouts") if method.get(k))
    gone = (f'<div class="sc-terms"><div>Not on the chart, because a score is never '
            f'guessed.</div><div>{esc("; ".join(off))}.</div></div>' if off else "")
    return (f'<div class="how-read sc-how"><div>How it is scored, each pillar from 0 to '
            f'100 within the area.</div>{body}{rest}{gone}</div>')


def rests_on_html(rows: list, horizon_end) -> str:
    """What every score rests on: a company a block, ranked, each pillar its score and
    the figures and products behind it."""
    out = ""
    for r in rows:
        s = r.get("scores") or {}
        v, p, d, c, ro = (r.get(k) or {} for k in
                          ("value", "pipeline", "durability", "clinical", "readouts"))
        top = ", ".join(f'{x["name"]} {money(x["usd_bn"])}' for x in v.get("top") or [])
        if v.get("basis") == "none marketed":
            value = "nothing marketed here."
        elif v.get("usd_bn") is None:
            value = f'{NO_DATA}: {v.get("basis") or "no model value"}.'
        else:
            value = (f'{money(v["usd_bn"])} across {v.get("valued")} of {v.get("products")} '
                     f'marketed products valued' + (f", {top}" if top else "")
                     + f'; {pct(v.get("share"))} of its product value.')
        late = ", ".join(f'{a["name"]}' + (" (filed)" if a.get("stage") == "Filed" else "")
                         for a in p.get("late") or [])
        pipe = (f'{money(p.get("usd_bn"))} risked across {p.get("valued", 0)} valued assets'
                if p.get("usd_bn") is not None else
                ("no unmarketed asset" if p.get("assets") == 0 else
                 "no pipeline value modelled"))
        pipe += f'; {p.get("depth", 0)} in Phase 3 or filed' + (f": {late}." if late else ".")
        if d.get("share") is None:
            dur = f"{NO_DATA}: no revenue on file here."
        else:
            prods = ", ".join(f'{x["name"]} {x["loe"][:4]}' for x in d.get("products") or [])
            dur = (f'{pct(d["share"])} of {money(d.get("revenue_usd_bn"))} revenue loses '
                   f'exclusivity by {horizon_end}' + (f": {prods}." if prods else "."))
        drugs = ", ".join(f'{x["name"]} {x["mean"]:.0f}' for x in c.get("drugs") or [])
        clin = (f'mean {c["mean"]:.0f} over {len(c.get("drugs") or [])} scored drugs: '
                f'{drugs}.' if c.get("mean") is not None else
                f"{NO_DATA}: no drug scored on an indication here.")
        reads = (f'{ro.get("count", 0)} readouts in 24 months'
                 + (f', {ro.get("priced")} priced, {money(ro.get("stake_usd_bn"))} at stake.'
                    if ro.get("stake_usd_bn") is not None else ", none priced."))
        meta = (f'{r["ticker"]} · overall {r["overall"]:.0f} on {r["pillars"]} of 4 pillars'
                if r.get("overall") is not None else r["ticker"])
        lines = [(f'Value today {score(s.get("value"))}', value),
                 (f'Pipeline {score(s.get("pipeline"))}', pipe),
                 (f'Durability {score(s.get("durability"))}', dur),
                 (f'Clinical quality {score(s.get("clinical"))}', clin),
                 ("Readouts", reads)]
        body = "<br>".join(f"{esc(k)}: {esc(t)}" for k, t in lines)
        lead = f'{r["rank"]}. ' if r.get("rank") else ""
        out += (f'<div class="sc-why"><b>{lead}{esc(short_name(r.get("name"), r["ticker"]))}'
                f'</b> <span class="m">{esc(meta)}</span><br>{body}</div>')
    return out


# --- the cards -----------------------------------------------------------------------
def company_card(page: dict, ticker: str, name: str | None = None) -> dict:
    """The selected company's position in the area as a card."""
    rows = page.get("companies") or []
    mine = next((r for r in rows if r["ticker"] == ticker), None)
    who = short_name((mine or {}).get("name") or name, ticker)
    title = f"{possessive(who)} position"
    if len(title) > CARD_TITLE_MAX:          # one line: a long name gives way to the ticker
        title = f"{possessive(ticker)} position"
    if mine is None:
        return {"kind": "company", "title": title,
                "headline": f"{who} has nothing placed in this area",
                "detail": "No marketed product, Phase 2 or later asset or modelled line "
                          "of its sits here."}
    s = mine.get("scores") or {}
    ranked = sum(1 for r in rows if r.get("rank"))
    head = (f'Ranks {mine["rank"]} of {ranked} at {mine["overall"]:.0f}, on '
            f'{mine["pillars"]} of 4 pillars' if mine.get("rank") else
            f"{who} is present with no pillar scored")
    d = mine.get("durability") or {}
    detail = (f'Value today {score(s.get("value"))}, pipeline {score(s.get("pipeline"))}, '
              f'durability {score(s.get("durability"))}, clinical {score(s.get("clinical"))}. '
              + cap(marketed_text(mine))
              + (f', {pct(d["share"])} at risk.' if d.get("share") is not None else "."))
    return {"kind": "company", "title": title, "headline": head, "detail": detail}


def card_html(card: dict, lead: bool = False) -> str:
    """One finding as the indication overview's compact card: the whole on hover."""
    whole = " ".join(x for x in (card.get("headline"), card.get("detail")) if x)
    detail = (f'<div class="vc-detail">{esc(card["detail"])}</div>'
              if card.get("detail") else "")
    return (f'<div class="vc{" vc-lead" if lead else ""} vc-compact vc-{esc(card["kind"])}" '
            f'title="{esc(whole)}"><div class="vc-title">{esc(card["title"])}</div>'
            f'<div class="vc-head">{esc(card["headline"])}</div>{detail}</div>')


def cards_html(cards: list) -> str:
    """One row of equal cards, the area leader first."""
    return ('<div class="sc-cards ar-cards">'
            + "".join(card_html(c, lead=c.get("kind") == "leader") for c in cards)
            + "</div>")
