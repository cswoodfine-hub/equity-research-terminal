"""The Catalysts tab by therapy area: one table, one row per area, one click for the rest.

The first view is the area table: one row per therapy area, sorted by the value its priced
gates put at stake within 24 months, with the readouts due in the next 12 and 24 months,
one diverging bar (what misses would take to the left, what passes would add to the right,
in dollars a share, both printed) and the area's next event. Beside it, the next five
dated readouts and an index of everything else. A row opens in place to its gates; a gate
opens its full detail in a dialog; an index row opens its own dialog.

The 24-month rule: an area's figures count only the priced gates that land within 24
months of the payload's day, a due readout counting as landing now (``gate_rows``' own
"near" view). A gate later or undated is listed in its open area under "Later or
undated" and is never in a sum. To gain is the sum of (success - now), at risk the sum of
(now - failure), a share, against the close in the payload. A readout on no priced gate
adds to the count, not the value.

Pure functions of the payload of ``GET /companies/{t}/catalysts/view``, ported from the
approved mockup (design_ui/cat2/b, direction B). The shared helpers, the fork and dates
pictures, the risk cards and the dialog's blocks are ``catalysts_view``'s own; nothing
here reads a network, a clock or Streamlit. A null is never drawn as a zero: a gate
without a leg is left out of the sum and named.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter

import catalysts_view as CV
from catalysts_view import MINUS, NO_DATA, esc, usd, pct, dm, dmy, mon

REVISION = 1

# --------------------------------------------------------------------------- layout
BAR_W = 380          # the diverging bar column, drawn 1:1
BAR_PAD = 60         # room each side of the bars for the printed figure
ROW_BAR_H = 16
GATE_BAR_H = 8
NEXT_N = 5
WINDOW_DAYS = 731    # 24 months, the count window and the value window

REASON_SHORT = {
    "no_gate_marketed": "marketed, label work",
    "no_gate": "outside the gate model",
    "other_indication": "indication not valued",
    "not_gate_phase": "not the gate's phase",
    "past_gate": "already at the FDA decision",
    "same_gate_later": "an earlier study decides the gate",
}
PANES = ("Legs and odds", "Cost to reach", "Studies and dates", "Market and evidence")
MORE_TITLES = {"cal": "Calendar, 24 months", "slip": "Date slips", "loe": "Exclusivity",
               "rec": "Results on file", "reg": "Undated regulatory", "pool": "Crowding",
               "unp": "Why readouts carry no price"}
RECORD_WHERE = "Record the outcome under the tabs"


def _reason_key(e) -> str:
    r = e.get("reason") or "no_gate"
    if r == "no_gate" and e.get("marketed"):
        return "no_gate_marketed"
    return r


def _sgn_usd(v, dp=2) -> str:
    """"+$4.97", "−$8.00"; "no free data" for none."""
    v = CV._num(v)
    if v is None:
        return NO_DATA
    s = f"${abs(v):,.{dp}f}"
    if not round(abs(v), dp):
        return s
    return ("+" if v > 0 else MINUS) + s


def _phase_tag(ph) -> str:
    return {"p2": "Ph 2", "p3": "Ph 3", "filed": "FDA"}.get(ph, "")


def _ev_phase(e) -> str:
    return str(e.get("phase") or "").replace("Phase ", "Ph ")


# ------------------------------------------------------------------------ the areas
def priced_gates(p) -> list:
    """Every priced gate with its own to gain, at risk and held part, and whether it lands
    within 24 months (``in24``): ``gate_rows``' near view, so a due readout counts now."""
    out = []
    for g in CV.gate_rows(p):
        now, s, f = g["now"], g["success"], g["failure"]
        g = dict(g)
        g["gain"] = (s - now) if None not in (s, now) else None
        g["risk"] = (now - f) if None not in (now, f) else None
        # the part of the risk a lone miss of the gate study leaves standing: other Phase 3s
        # hold the line until they read out, so it goes only if the programme fails
        if g["risk"] is not None and g.get("held_ps") is not None:
            g["held_part"] = max(0.0, min(g["held_ps"] - f, g["risk"]))
        else:
            g["held_part"] = 0.0
        g["in24"] = g["view"] == "near"
        out.append(g)
    return out


def area_rows(p) -> list:
    """One dict per therapy area: its priced gates within 24 months and their sums, its
    later or undated gates (listed, never summed), its readouts in 12 and 24 months, why
    the unpriced ones carry no price, and its next event. Sorted by value at stake (to
    gain plus at risk), then by readouts."""
    today = CV._today(p)
    h12, h24 = today + dt.timedelta(days=365), today + dt.timedelta(days=WINDOW_DAYS)
    areas = {}

    def slot(name):
        name = name or "No area on file"
        if name not in areas:
            areas[name] = {"area": name, "gates": [], "later": [], "events": [], "gain": 0.0,
                           "risk": 0.0, "held": 0.0, "missing": [], "n12": 0, "n24": 0,
                           "priced12": 0, "priced24": 0, "label24": 0,
                           "reasons": Counter(), "overdue": []}
        return areas[name]

    for g in priced_gates(p):
        a = slot(g.get("area"))
        if not g["in24"]:
            a["later"].append(g)
            continue
        a["gates"].append(g)
        if g["gain"] is not None:
            a["gain"] += g["gain"]
        if g["risk"] is not None:
            a["risk"] += g["risk"]
            a["held"] += g["held_part"]
        if g["gain"] is None or g["risk"] is None:
            a["missing"].append(g.get("name"))
        if g.get("due"):
            a["overdue"].append(g)
    for e in p.get("events") or []:
        d = CV._d(e.get("date"))
        if not d or d < today or d > h24:
            continue
        a = slot(e.get("area"))
        a["events"].append(e)
        a["n24"] += 1
        a["priced24"] += 1 if e.get("priced") else 0
        if d <= h12:
            a["n12"] += 1
            a["priced12"] += 1 if e.get("priced") else 0
        if not e.get("priced"):
            a["reasons"][_reason_key(e)] += 1
            a["label24"] += 1 if _reason_key(e) == "no_gate_marketed" else 0
    out = []
    for a in areas.values():
        a["gates"].sort(key=lambda g: -((g["gain"] or 0) + (g["risk"] or 0)))
        a["later"].sort(key=lambda g: (g.get("fl") or g.get("d") or dt.date.max, g.get("name") or ""))
        a["events"].sort(key=lambda e: (e["date"], e.get("id") or 0))
        a["next"] = a["events"][0] if a["events"] else None
        # the first gate to decide: an FDA floor or a registry date, never an overdue one
        dated = [g for g in a["gates"] if not g.get("due") and (g.get("fl") or g.get("d"))]
        a["first_gate"] = min(dated, key=lambda g: g.get("fl") or g.get("d")) if dated else None
        a["stake"] = a["gain"] + a["risk"]
        out.append(a)
    out.sort(key=lambda a: (-a["stake"], -a["n24"], a["area"]))
    return out


def scale(rows) -> dict:
    """One scale for every bar on the page: dollars a share to pixels, the zero placed so
    the largest risk and the largest gain both fit."""
    lmax = max([a["risk"] for a in rows] + [0.01])
    rmax = max([a["gain"] for a in rows] + [0.01])
    k = (BAR_W - 2 * BAR_PAD) / (lmax + rmax)
    return {"k": k, "x0": BAR_PAD + lmax * k, "lmax": lmax, "rmax": rmax}


def totals(rows, p) -> dict:
    t = {"gain": sum(a["gain"] for a in rows), "risk": sum(a["risk"] for a in rows),
         "held": sum(a["held"] for a in rows),
         "n_gates": sum(len(a["gates"]) for a in rows),
         "n_later": sum(len(a["later"]) for a in rows),
         "n12": sum(a["n12"] for a in rows), "n24": sum(a["n24"] for a in rows),
         "priced24": sum(a["priced24"] for a in rows),
         "missing": [m for a in rows for m in a["missing"]]}
    t["close"] = CV._close(p)
    return t


# ------------------------------------------------------------------------- the bars
def _gate_tip(g) -> str:
    when, _ = CV.date_text(g)
    up = _sgn_usd(g["gain"])
    dn = _sgn_usd(-g["risk"]) if g["risk"] is not None else NO_DATA
    held = (f"; a lone miss is held at {usd(g['held_ps'])} while other Phase 3s run"
            if g["held_part"] > 0.004 else "")
    return (f"{g.get('name')} · {g['glabel']} · {when} · pass {up} · fail {dn}{held}. "
            f"Click for the full detail.")


def bar_svg(items, sc, h=ROW_BAR_H, height=26, labels=True, cls="ar", held_word=False) -> str:
    """A diverging bar: ``items`` are the gates (each a segment, a click target), risk to
    the left of zero, gain to the right. Hatched where a lone miss is held by other
    Phase 3s. Figures printed at the ends."""
    W = BAR_W
    x0, k = sc["x0"], sc["k"]
    y = (height - h) / 2
    o = [f'<svg class="ca-bar {cls}" viewBox="0 0 {W} {height}" width="{W}" height="{height}" '
         f'role="img" aria-label="At risk to the left, to gain to the right, dollars a share">']
    o.append(f'<line class="z" x1="{x0:.1f}" x2="{x0:.1f}" y1="0" y2="{height}"/>')
    gain = sum(g["gain"] or 0 for g in items)
    risk = sum(g["risk"] or 0 for g in items)
    held = sum(g["held_part"] for g in items)
    x = x0
    for g in sorted(items, key=lambda g: -(g["gain"] or 0)):
        w = (g["gain"] or 0) * k
        if w <= 0:
            continue
        gap = 1 if w >= 4 else 0
        o.append(f'<a data-gate="{g["asset_id"]}"><title>{esc(_gate_tip(g))}</title>'
                 f'<rect class="up" x="{x:.2f}" y="{y:.1f}" width="{max(w - gap, 0.8):.2f}" '
                 f'height="{h}"/></a>')
        x += w
    xr = x
    x = x0
    for g in sorted(items, key=lambda g: -(g["risk"] or 0)):
        w = (g["risk"] or 0) * k
        if w <= 0:
            continue
        gap = 1 if w >= 4 else 0
        wh = g["held_part"] * k
        ws = w - wh
        parts = []
        if ws > 0.05:
            parts.append(f'<rect class="dn" x="{x - ws:.2f}" y="{y:.1f}" width="{max(ws, 0.8):.2f}" '
                         f'height="{h}"/>')
        if wh > 0.05:
            parts.append(f'<rect class="hd" x="{x - w + gap:.2f}" y="{y:.1f}" '
                         f'width="{max(wh - gap, 0.8):.2f}" height="{h}"/>')
        o.append(f'<a data-gate="{g["asset_id"]}"><title>{esc(_gate_tip(g))}</title>'
                 f'{"".join(parts)}</a>')
        x -= w
    xl = x
    if labels:
        ty = height / 2 + 4
        if gain > 0.0049:
            o.append(f'<text class="v up" x="{xr + 5:.1f}" y="{ty:.1f}">{_sgn_usd(gain)}</text>')
        elif items:
            o.append(f'<text class="v mu" x="{xr + 5:.1f}" y="{ty:.1f}">$0.00</text>')
        if risk > 0.0049:
            word = ""
            if held_word and held >= risk - 0.005:
                word = '<tspan class="hw">held </tspan>'
            o.append(f'<text class="v dn" x="{xl - 5:.1f}" y="{ty:.1f}" text-anchor="end">'
                     f'{word}{_sgn_usd(-risk)}</text>')
    o.append("</svg>")
    return "".join(o)


def axis_svg(sc, close) -> str:
    """The bar column's head: a miss takes and a pass adds either side of zero, and under
    it a scale bar from zero the width of 1% of the share price."""
    W, H = BAR_W, 30
    x0, k = sc["x0"], sc["k"]
    o = [f'<svg class="ca-axis" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
         f'aria-label="Bar scale, dollars a share">']
    o.append(f'<text class="hk dn" x="{x0 - 7:.1f}" y="10" text-anchor="end">◂ A miss takes</text>'
             f'<text class="hk up" x="{x0 + 7:.1f}" y="10">A pass adds ▸</text>'
             f'<line class="z" x1="{x0:.1f}" x2="{x0:.1f}" y1="0" y2="{H}"/>')
    if close:
        w = close * 0.01 * k
        o.append(f'<path class="br" d="M{x0:.1f} 18 v5 h{w:.1f} v-5"/>'
                 f'<text class="tk" x="{x0 + w + 5:.1f}" y="25">1% of price, {usd(close * 0.01)}</text>')
    o.append("</svg>")
    return "".join(o)


# ------------------------------------------------------------------------ the header
def lead_sentence(rows, t, p) -> str:
    """Where the value within 24 months sits and where the readouts are, from the areas."""
    if not rows or not t["gain"]:
        later = (f" {CV._plural(t['n_later'], 'priced gate')} land later or carry no date."
                 if t.get("n_later") else "")
        return (f"No pipeline line of {esc(CV._ticker(p))} carries a priced gate landing within "
                f"24 months on this book, so the areas are counted, not valued.{later}")
    top = rows[0]
    share = top["gain"] / t["gain"] if t["gain"] else 0
    gs = sorted([g for g in top["gates"] if g["gain"]], key=lambda g: -g["gain"])
    lead, acc = [], 0.0
    for g in gs:
        lead.append(g)
        acc += g["gain"]
        if acc >= 0.8 * top["gain"] or len(lead) == 2:
            break
    names = " and ".join(esc(g["name"]) for g in lead)
    labels = [g["glabel"] for g in lead]
    years = sorted({(g.get("fl") or g.get("d")).year for g in lead if g.get("d") or g.get("fl")})
    if len(lead) > 1 and len(set(labels)) == 1:
        what = labels[0].replace("readout", "readouts").replace("decision", "decisions")
        tail = "if both pass"
    elif len(lead) > 1:
        what = " and ".join(labels)
        tail = "if both pass"
    else:
        what = labels[0]
        tail = "if it passes"
    when = f" in {years[0]}" if len(years) == 1 else ""
    s1 = (f"{esc(top['area'])} holds {pct(share)} of the value to gain within 24 months: {names}, "
          f"{esc(what)}{when}, would add <b class=\"up\">{_sgn_usd(acc)}</b> a share {tail}.")
    busiest = max(rows, key=lambda a: a["n24"])
    s2 = ""
    if busiest is not top and busiest["n24"]:
        s2 = (f" {esc(busiest['area'])} has the most readouts, <b>{busiest['n24']}</b> in 24 "
              f"months, for <b class=\"up\">{_sgn_usd(busiest['gain'])}</b> across "
              f"{CV._plural(len(busiest['gates']), 'priced gate')}.")
    return s1 + s2


def header_html(p, rows, t) -> str:
    close = t["close"]
    kick = (f"Catalysts by therapy area · next 24 months · $ a share against the {usd(close)} "
            f"close on {dmy(p.get('close_date'))}" if close else
            "Catalysts by therapy area · next 24 months · $ a share")
    gp = f" · {pct(t['gain'] / close, 1)} of price" if close else ""
    lone = t["risk"] - t["held"]
    held = (f" · a lone study miss takes {usd(lone)}" if t["held"] > 0.004 else "")
    figs = [("up", _sgn_usd(t["gain"]), "to gain",
             f"if all {t['n_gates']} priced gates pass{gp}",
             "Each priced gate landing within 24 months: its pass leg less today's value, "
             "summed. The model's figures."),
            ("dn", _sgn_usd(-t["risk"]), "at risk", f"if every one fails{held}",
             f"Today's value to the fail leg, nil by the model's convention, summed over the "
             f"same gates. {usd(t['held'])} of it is held while other Phase 3s run: a lone "
             f"study miss takes {usd(lone)}."),
            ("", str(t["n24"]), "readouts",
             f"in 24 months · {t['n12']} in 12 · {t['priced24']} priced",
             "Dated readouts on the registry, every date an estimate. A readout that "
             "decides no priced gate adds to the count, not the value.")]
    cells = "".join(f'<div class="ca-fig" title="{esc(tip)}"><span class="v m {tone}">{esc(v)}</span>'
                    f'<span class="k"><b>{esc(k)}</b> {esc(s)}</span></div>'
                    for tone, v, k, s, tip in figs)
    return (f'<div class="ca-hd"><div class="ca-hd-l"><div class="ca-kick">{esc(kick)}</div>'
            f'<p class="ca-lead">{lead_sentence(rows, t, p)}</p></div>'
            f'<div class="ca-figs">{cells}</div></div>')


# ------------------------------------------------------------------------ the table
def _count_cell(a, nmax) -> str:
    W = 96
    w24 = W * a["n24"] / nmax if nmax else 0
    w12 = W * a["n12"] / nmax if nmax else 0
    pr = (f' · <span class="pr">{a["priced24"]} priced</span>' if a["priced24"]
          else ' · <span class="pr none">none priced</span>')
    tip = (f"{a['n24']} dated readouts in 24 months, {a['n12']} in 12; {a['priced24']} on a "
           f"priced gate; {a['label24']} on marketed lines, label work")
    return (f'<div class="c-cnt" title="{esc(tip)}"><div class="nums"><b class="m">{a["n24"]}</b></div>'
            f'<div class="cbar"><i class="b24" style="width:{w24:.1f}px"></i>'
            f'<i class="b12" style="width:{w12:.1f}px"></i></div>'
            f'<div class="sub"><span class="m">{a["n12"]}</span> in 12 months{pr}</div></div>')


def _next_cell(a) -> str:
    e = a["next"]
    if e:
        tip = f'{dmy(e["date"])} · {e.get("asset") or "unmatched"} · {e.get("phase") or ""}'
        l1 = (f'<span class="d m">{dmy(e["date"])}</span>'
              f'<b>{esc(e.get("asset") or "unmatched")}</b>'
              f'<i class="mk-ph {CV.phase_class(e.get("phase"))}">{esc(_ev_phase(e))}</i>')
    else:
        tip = ""
        l1 = '<span class="mu">no dated readout in 24 months</span>'
    g = a["first_gate"]
    if g:
        when = f"≥ {mon(g['fl'])}" if g.get("fl") else f"est. {mon(g['d'])}"
        l2 = f'first gate: {esc(g["name"])} {esc(_phase_tag(g["ph"]))}, {esc(when)}'
    elif a["gates"]:
        l2 = "first gate: overdue, no result on file"
    elif a["later"]:
        l2 = "no priced gate within 24 months"
    else:
        l2 = ""
    return (f'<div class="c-next"><div class="l1" title="{esc(tip)}">{l1}</div>'
            f'<div class="l2" title="{esc(re.sub("<[^>]+>", "", l2))}">{l2}</div></div>')


def _name_cell(a) -> str:
    n, m = len(a["gates"]), len(a["later"])
    sub = f"{n} priced" if n else "none priced"
    sub += f" · {m} later" if m else ""
    flag = (f'<span class="fl" title="{esc(", ".join(g["name"] for g in a["overdue"]))}: past the '
            f'registry date with no result on file">{len(a["overdue"])} overdue</span>'
            if a["overdue"] else "")
    miss = (f'<span class="fl" title="{esc(", ".join(a["missing"]))}">'
            f'{len(a["missing"])} {NO_DATA}</span>' if a["missing"] else "")
    return (f'<div class="c-name"><b>{esc(a["area"])}</b>'
            f'<span class="s">{sub}{flag}{miss}</span></div>')


def _bar_cell(a, sc) -> str:
    if not a["gates"]:
        word = ("no priced gate within 24 months" if a["later"]
                else "no priced gate · count only")
        return (f'<div class="c-bar"><svg class="ca-bar ar" viewBox="0 0 {BAR_W} 26" width="{BAR_W}" '
                f'height="26"><line class="z" x1="{sc["x0"]:.1f}" x2="{sc["x0"]:.1f}" y1="0" y2="26"/>'
                f'<text class="v mu nb" x="{sc["x0"] + 6:.1f}" y="17">{word}</text>'
                f'</svg></div>')
    return f'<div class="c-bar">{bar_svg(a["gates"], sc)}</div>'


def _gate_when(g) -> str:
    when, _flag = CV.date_text(g)
    tag = ""
    mv = g.get("move") or {}
    if g.get("due"):
        tag = '<span class="tg fl">overdue</span>'
    elif mv.get("days") and mv["days"] > 0:
        tag = (f'<span class="tg dn" title="was {esc(dmy(mv.get("old")))}, seen '
               f'{esc(dmy(mv.get("seen")))}">{mv["days"]} days later</span>')
    elif g.get("fl"):
        tag = '<span class="tg">earliest</span>'
    return f'<span class="m">{esc(when.replace("est. ", ""))}</span>{tag}'


def _record_flag(p, g) -> str:
    """A signed Phase 3 result on file the book does not carry yet: the record card's own
    rule, said on the gate's line."""
    for r in p.get("readouts") or []:
        if (r.get("asset_id") == g["asset_id"] and r.get("outcome") == "negative"
                and CV._d(r.get("event_date"))):
            return (f'<span class="tg dn" title="Phase 3 read out negative {esc(dmy(r["event_date"]))}; '
                    f'the book still holds the line at today\'s odds. {esc(r.get("quote") or "")}">'
                    f'negative {dm(r["event_date"])}, not on book</span>')
    return ""


def _gate_line(p, g, sc, later=False) -> str:
    odds = CV._num(g.get("p_gate"))
    ow = 40 * odds if odds is not None else 0
    chance = (f'<span class="od"><i style="width:{ow:.1f}px"></i></span>'
              f'<span class="m">{pct(odds)}</span>'
              if odds is not None else f'<span class="mu">{NO_DATA}</span>')
    if later:
        dn = _sgn_usd(-g["risk"]) if g["risk"] is not None else NO_DATA
        bar = (f'<span class="lt m"><b class="up-t">{_sgn_usd(g["gain"])}</b> if it passes · '
               f'<b class="dn-t">{dn}</b> if it fails</span>')
    else:
        bar = bar_svg([g], sc, h=GATE_BAR_H, height=20, cls="gl", held_word=True)
    return (f'<div class="ca-gl{" lt" if later else ""}" data-gate="{g["asset_id"]}" role="button" '
            f'tabindex="0" title="{esc(_gate_tip(g))}">'
            f'<div class="g-name"><b>{esc(g.get("name"))}</b>'
            f'<i class="mk-ph {g["ph"]}">{esc(_phase_tag(g["ph"]))}</i></div>'
            f'<div class="g-when">{_gate_when(g)}</div>'
            f'<div class="g-bar">{bar}</div>'
            f'<div class="g-odds">{chance}{_record_flag(p, g)}</div>'
            f'<div class="c-chev g"><i></i></div></div>')


def gates_html(p, a, sc) -> str:
    """The area's gates, one line each on the area's bar scale, then the later or undated
    ones, printed but not summed: each line opens the gate dialog."""
    lines = []
    if a["gates"]:
        lines.append('<div class="ca-gh"><span>Priced gate, within 24 months</span><span>Decides</span>'
                     '<span>On the same scale</span><span>Chance to pass</span><span></span></div>')
        lines += [_gate_line(p, g, sc) for g in a["gates"]]
    else:
        lines.append('<div class="ca-gnone">No priced gate in this area lands within 24 months.</div>')
    if a["later"]:
        lines.append('<div class="ca-gh lt"><span>Later or undated</span><span></span>'
                     '<span>not in the area\'s figures</span><span></span><span></span></div>')
        lines += [_gate_line(p, g, sc, later=True) for g in a["later"]]
    rs = a["reasons"]
    parts = [f"{n} {REASON_SHORT.get(k, k.replace('_', ' '))}" for k, n in rs.most_common()]
    unpriced = a["n24"] - a["priced24"]
    why = ", ".join(parts)
    foot = (f'<div class="ca-gfoot"><span class="tx" title="{esc(why)}">{a["n24"]} readouts in 24 months, '
            f'{a["priced24"]} on a priced gate; {unpriced} count only'
            + (f' ({esc(why)})' if why else "") + '</span>'
            + (f'<a class="lk" data-more="cal" data-area="{esc(a["area"])}">all {a["n24"]} in the '
               f'calendar ›</a>' if a["n24"] else "") + '</div>')
    return '<div class="ca-gates">' + "".join(lines) + foot + "</div>"


def footnote(t) -> str:
    """What the bars count, said under the table: the 24-month rule and the count-only
    readouts."""
    one = t["n_later"] == 1
    later = (f" {CV._plural(t['n_later'], 'later or undated gate')} "
             f"{'is' if one else 'are'} listed in {'its' if one else 'their'} area, not in the "
             f"figures." if t["n_later"] else "")
    return (f"Bars sum the {CV._plural(t['n_gates'], 'priced gate')} landing within 24 months; "
            f"a due readout counts as landing now.{later} A readout on no priced gate adds to "
            f"the count, not the value.")


def table_html(p, rows, sc, t) -> str:
    nmax = max([a["n24"] for a in rows] + [1])
    head = ('<div class="ca-th"><div class="c-name">Therapy area<span>by value at stake</span></div>'
            '<div class="c-cnt">Readouts<span>next 24 months</span></div>'
            f'<div class="c-bar">{axis_svg(sc, t["close"])}</div>'
            '<div class="c-next">Next readout<span>and the first priced gate</span></div>'
            '<div class="c-chev"></div></div>')
    body = []
    for a in rows:
        body.append(f'<div class="ca-row" data-area="{esc(a["area"])}">'
                    f'<div class="ca-ar" role="button" tabindex="0" aria-expanded="false" '
                    f'title="Open {esc(a["area"])}: its gates, dates and odds">'
                    f'{_name_cell(a)}{_count_cell(a, nmax)}{_bar_cell(a, sc)}{_next_cell(a)}'
                    f'<div class="c-chev"><i></i></div></div>'
                    f'{gates_html(p, a, sc)}</div>')
    foot = ('<div class="ca-foot"><span class="key"><i class="k-up"></i>a pass adds</span>'
            '<span class="key"><i class="k-dn"></i>a miss takes</span>'
            '<span class="key"><i class="k-hd"></i>held while other Phase 3s run</span>'
            f'<span class="nt">{esc(footnote(t))}</span></div>')
    return f'<div class="ca-tbl">{head}<div class="ca-rows">{"".join(body)}</div>{foot}</div>'


# ------------------------------------------------------------------------- the rail
def next_html(p, n=NEXT_N) -> str:
    rows = CV.next_rows(p, n)
    today = CV._today(p)
    in12 = sum(1 for e in p.get("events") or [] if CV._d(e.get("date"))
               and today <= CV._d(e["date"]) <= today + dt.timedelta(days=365))
    out = []
    for e in rows:
        t = e.get("trial") or {}
        cond = (t.get("conditions") or [""])[0] if t.get("conditions") else ""
        why = (f'<span class="up-t">priced · {_sgn_usd(e.get("per_share"))} if it passes</span>'
               if e.get("priced") else esc(REASON_SHORT.get(_reason_key(e), "not priced")))
        gate = f' data-gate="{e["gate_asset"]}"' if e.get("priced") and e.get("gate_asset") else ""
        url = e.get("url") or ""
        n_ = t.get("enrollment")
        d = CV._d(e["date"])
        out.append(f'<a class="ca-nx"{gate} href="{esc(url)}" target="_blank" rel="noopener" '
                   f'title="{esc(e.get("nct") or "")} · {esc(e.get("title") or "")}">'
                   f'<span class="d m"><b>{d.day}</b>{CV.MON[d.month - 1]}'
                   f'{"<em>" + str(d.year) + "</em>" if d.year != today.year else ""}</span>'
                   f'<span class="b"><span class="t"><b>{esc(e.get("asset") or "unmatched")}</b>'
                   f'<i class="mk-ph {CV.phase_class(e.get("phase"))}">{esc(_ev_phase(e))}</i>'
                   f'<span class="ar">{esc(e.get("area") or "")}</span></span>'
                   f'<span class="w">{esc(cond)}{" · " if cond else ""}{why}</span></span>'
                   f'<span class="n m">{f"{n_:,}" if n_ else NO_DATA}<em>patients</em></span></a>')
    if not out:
        out.append('<div class="cx-empty">No dated readout on file.</div>')
    return (f'<div class="ca-sec"><span class="h">Next up</span>'
            f'<span class="c m">{len(rows)} of {in12} in 12 months · est. dates</span></div>'
            f'<div class="ca-next">{"".join(out)}</div>')


def index_items(p, rows) -> list:
    """The index of what sits one click away: (key, label, figure, short line, tooltip). The
    figures are the risk cards' own, so the two never disagree; the line is cut to a few
    words and the card's full sentence rides as the tooltip."""
    cards = {c[0]: c for c in CV.risk_cards(p)}
    today = CV._today(p)
    plain = lambda x: re.sub(r"<[^>]+>", "", str(x or ""))  # noqa: E731
    items = []
    n24 = sum(a["n24"] for a in rows)
    items.append(("cal", "Calendar", str(n24),
                  f"every readout to {mon(today + dt.timedelta(days=WINDOW_DAYS))}, by area and month",
                  "Areas down the side, months across; the list under it."))
    slips = p.get("slips") or []
    gates = {g["asset_id"] for g in CV.gate_rows(p)}
    short = {}
    if slips:
        top = slips[0]
        who = esc(top.get("asset") or top.get("nct"))
        short["slip"] = (f"{who}'s gate study now {mon(top['new'])} · {len(slips)} in 30 days"
                         if top.get("gate_asset") else f"{who} now {mon(top['new'])} · {len(slips)} in 30 days")
    w = CV.wall(p, today.year + 1)
    if w:
        short["loe"] = f"a share on lines losing exclusivity {w[0]} to {w[1]}"
    ro = p.get("readouts") or []
    if ro:
        first = min((CV._d(r.get("event_date")) for r in ro if CV._d(r.get("event_date"))), default=None)
        off = [r for r in ro if r.get("outcome") == "negative" and r.get("asset_id") in gates]
        short["rec"] = ((f"positive since {mon(first)}" if first else "results on file")
                        + (f' · <b class="fl-t">{len(off)} negative not on book</b>' if off else ""))
    short["reg"] = "FDA decisions and filings with no date on file"
    c = p.get("crowding") or {}
    lead = ((c.get("company_pool") or {}).get("leader") or {}).get("ticker")
    if c.get("indication"):
        short["pool"] = (f"{esc(CV._ticker(p))} in {esc(str(c['indication']).lower())} claims"
                         + (f", {esc(lead)} leads" if lead else ""))
    for key, label in (("slip", "Date slips"), ("loe", "Exclusivity"), ("rec", "Results on file"),
                       ("reg", "Undated regulatory"), ("pool", "Crowding")):
        card = cards.get(key)
        if not card:
            continue
        items.append((key, label, card[2], short.get(key) or card[3], plain(card[3])))
    unp = sum(1 for e in p.get("events") or [] if not e.get("priced"))
    items.append(("unp", "Why no price", f'{unp}<span class="u">of {len(p.get("events") or [])}</span>',
                  "readouts on no priced gate, by reason",
                  "Marketed lines, indications the forecast does not value, and studies that do "
                  "not decide a gate."))
    return items


def index_html(p, rows) -> str:
    out = []
    for key, label, fig, sub, tip in index_items(p, rows):
        out.append(f'<a class="ca-ix k-{key}" data-more="{key}" role="button" tabindex="0" '
                   f'title="{esc(tip)}">'
                   f'<span class="l">{esc(label)}</span><span class="f m">{fig}</span>'
                   f'<span class="s">{sub}</span><i class="ch"></i></a>')
    return (f'<div class="ca-sec"><span class="h">More detail</span>'
            f'<span class="c">one click each</span></div><div class="ca-ixs">{"".join(out)}</div>')


HATCH = ('<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>'
         '<pattern id="ca-hd" width="4" height="4" patternUnits="userSpaceOnUse" '
         'patternTransform="rotate(45)"><rect class="hd-bg" width="4" height="4"/>'
         '<rect class="hd-ln" width="1.4" height="4"/></pattern></defs></svg>')


def page_html(p) -> str:
    """The whole first view: the header, the area table and the rail."""
    rows = area_rows(p)
    sc = scale(rows)
    t = totals(rows, p)
    return (f'<div class="cx ca-page">{HATCH}{header_html(p, rows, t)}'
            f'<div class="ca-body"><div class="ca-main">{table_html(p, rows, sc, t)}</div>'
            f'<div class="ca-rail">{next_html(p)}{index_html(p, rows)}</div></div></div>')


# ------------------------------------------------------------------------- dialogs
def _facts(rows) -> str:
    """The Next gate facts as figures: the label, the value and its few words, the Forecast
    tab's longer sentence as the tooltip."""
    out = []
    for x in rows:
        v = x.get("v")
        v = NO_DATA if v in (None, "") else (v if x.get("html") else esc(v))
        tone = {"down": " dn-t", "muted": " mu", "none": " mu"}.get(x.get("tone") or "", "")
        out.append(f'<div class="gd-fx" title="{esc(x.get("tip") or "")}"><span>{esc(x.get("k"))}</span>'
                   f'<b class="m{tone}">{v}</b><em>{esc(x.get("note") or "")}</em></div>')
    return "".join(out)


def gate_dialog(p, gid, facts_rows=None, cost_html="", ladder_html="", studies_html="",
                can_record=None) -> tuple:
    """The gate's full detail as (top, panes): the head and a band of three pictures (the
    legs as a fork, the dates, the Next gate facts), then four panes, each (label, markup):
    legs and odds, cost to reach, studies and dates, market and evidence. ``facts_rows``
    are the Forecast tab's gate rows; the tables are its builders' markup."""
    d = CV.dialog_parts(p, gid, cost_html, ladder_html, studies_html, can_record,
                        record_where=RECORD_WHERE)
    if d is None:
        return CV.DIALOG_NONE, []
    r = CV._gate(p, gid)
    close, today = CV._close(p), CV._today(p)
    facts = _facts(facts_rows) if facts_rows else (
        CV._kv("Chance", pct(r.get("p_gate"))) + CV._kv("Today", usd(r["now"]))
        + CV._kv("If it passes", usd(r["success"])))
    band = (f'<div class="gd-band"><div class="gd-p"><div class="gd-h">If it passes, if it misses '
            f'<span>$ a share</span></div>{CV.fork_svg(r, close)}</div>'
            f'<div class="gd-p"><div class="gd-h">Dates <span>studies sized by patients</span></div>'
            f'{CV.dates_svg(r, today)}</div>'
            f'<div class="gd-p gd-f"><div class="gd-h">The gate <span>Forecast tab figures</span></div>'
            f'{facts}</div></div>')
    top = f'<div class="cx cx-dlg gd">{d["head"]}{band}</div>'
    two = lambda a, b: f'<div class="cx cx-dlg gd"><div class="gd-2"><div>{a}</div><div>{b}</div></div></div>'  # noqa: E731
    sources = f'<div class="cx-dh2">Sources</div><div class="cx-p mut">{esc(CV.notes_text(p))}</div>'
    panes = [(PANES[0], two(d["legs"], d["odds"])),
             (PANES[1], two(d["cost"], d["record"])),
             (PANES[2], two(d["gantt"] or f'<div class="cx-dh2">Studies behind the gate</div>'
                                          f'<div class="cx-none">{NO_DATA}</div>', d["dates"])),
             (PANES[3], two(d["market"], d["evidence"] + sources))]
    return top, panes


def more_dialog_html(p, key, area=None) -> str:
    """One index row's detail: the calendar, a risk card's picture and rows, or why the
    readouts carry no price."""
    if key == "cal":
        return calendar_html(p, area)
    if key == "unp":
        return f'<div class="cx cx-dlg md">{CV.unpriced_html(p)}</div>'
    for k, _kicker, fig, sub, vis, body in CV.risk_cards(p):
        if k == key:
            return (f'<div class="cx cx-dlg md"><div class="md-hd"><span class="f m">{fig}</span>'
                    f'<span class="s">{sub}</span></div><div class="md-b">{vis}{body}</div></div>')
    return '<div class="cx cx-dlg md"><div class="cx-empty">Nothing on file.</div></div>'


def more_title(key, area=None) -> str:
    title = MORE_TITLES.get(key, "More detail")
    return f"{title} · {area}" if key == "cal" and area else title


def calendar_html(p, area=None) -> str:
    """Every dated readout in the next 24 months, areas down the side and months across:
    a cell counts the readouts, a ring marks one on a priced gate. Under it, the list for
    the area asked for (or every area), month by month, each name linked to its registry
    record."""
    rows = area_rows(p)
    today = CV._today(p)
    months = []
    y, m = today.year, today.month
    for _ in range(25):
        months.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    W, lw, rh = 1040, 190, 24
    cw = (W - lw) / len(months)
    H = 22 + rh * len(rows) + 4
    o = [f'<svg class="md-cal" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
         f'aria-label="Readouts by area and month">']
    for i, (yy, mm) in enumerate(months):
        x = lw + i * cw
        lab = CV.MON[mm - 1][:3] if mm != 1 else str(yy)
        o.append(f'<text class="tk{" yr" if mm == 1 else ""}" x="{x + cw / 2:.1f}" y="12" '
                 f'text-anchor="middle">{lab}</text>')
        if mm == 1:
            o.append(f'<line class="yr" x1="{x:.1f}" x2="{x:.1f}" y1="16" y2="{H}"/>')
    x12 = lw + 12 * cw
    o.append(f'<line class="m12" x1="{x12:.1f}" x2="{x12:.1f}" y1="16" y2="{H}"/>')
    big, cells = 1, {}
    for a in rows:
        for e in a["events"]:
            d = CV._d(e["date"])
            k = (a["area"], d.year, d.month)
            cells.setdefault(k, []).append(e)
            big = max(big, len(cells[k]))
    for j, a in enumerate(rows):
        y0 = 20 + j * rh
        on = area == a["area"]
        o.append(f'<text class="an{" on" if on else ""}" x="0" y="{y0 + 15}">{esc(a["area"])}</text>'
                 f'<line class="rl" x1="0" x2="{W}" y1="{y0 + rh}" y2="{y0 + rh}"/>')
        for i, (yy, mm) in enumerate(months):
            es = cells.get((a["area"], yy, mm)) or []
            if not es:
                continue
            x = lw + i * cw
            n = len(es)
            pr = sum(1 for e in es if e.get("priced"))
            op = 0.25 + 0.75 * n / big
            tip = "; ".join(f'{dm(e["date"])} {e.get("asset") or "unmatched"} {_ev_phase(e)}' for e in es)
            o.append(f'<g><title>{esc(tip)}</title><rect class="c{" pr" if pr else ""}" x="{x + 2:.1f}" '
                     f'y="{y0 + 3}" width="{cw - 4:.1f}" height="{rh - 6}" style="fill-opacity:{op:.2f}"/>'
                     f'<text class="cn" x="{x + cw / 2:.1f}" y="{y0 + 16}" text-anchor="middle">{n}</text></g>')
    o.append("</svg>")
    sel = [a for a in rows if (area is None or a["area"] == area)]
    evs = sorted([e for a in sel for e in a["events"]], key=lambda e: e["date"])
    lst, cur = [], None
    for e in evs:
        d = CV._d(e["date"])
        k = (d.year, d.month)
        if k != cur:
            cur = k
            lst.append(f'<div class="md-mo m">{CV.MON[d.month - 1]} {d.year}</div>')
        t = e.get("trial") or {}
        cond = (t.get("conditions") or [""])[0] if t.get("conditions") else ""
        why = (f'<span class="up-t">priced · {_sgn_usd(e.get("per_share"))} if it passes</span>'
               if e.get("priced") else esc(REASON_SHORT.get(_reason_key(e), "not priced")))
        name = f'<b>{esc(e.get("asset") or "unmatched")}</b>'
        if e.get("url"):
            name = f'<a href="{esc(e["url"])}" target="_blank" rel="noopener">{name}</a>'
        lst.append(f'<div class="md-ev"><span class="m">{dm(e["date"])}</span>'
                   f'<span>{name} '
                   f'<i class="mk-ph {CV.phase_class(e.get("phase"))}">{esc(_ev_phase(e))}</i></span>'
                   f'<span class="mu">{esc(e.get("area") or "")}</span>'
                   f'<span class="mu el">{esc(cond)}</span><span class="w">{why}</span></div>')
    who = esc(area) if area else "Every area"
    return (f'<div class="cx cx-dlg md ca-cal"><div class="md-k">Readouts a month, by area · the darker the cell, the '
            f'more readouts · <span class="pr-k"></span> one on a priced gate · the rule marks 12 months</div>'
            f'{"".join(o)}<div class="md-lh">{who}: {CV._plural(len(evs), "readout")}, every date an '
            f'estimate from the registry</div><div class="md-list">{"".join(lst)}</div></div>')
