"""The Catalysts tab as a dated list: every readout in the next 24 months, soonest first.

The first view is one list under quarter headings, an Overdue group first: the date, the
drug, its phase, the indication, the disease area as a tag, the patients and, for a row
that decides a priced gate, the odds and one diverging bar (what a miss takes to the left,
what a pass adds to the right, dollars a share, both printed). A readout on no priced gate
reads muted, with no bar. A row opens its full card in a dialog: the gate's for a priced
gate, the trial's for the rest. Beside the list, the areas as a filter and an index of the
detail one click away.

The 24-month rule: the header's to gain and at risk sum only the priced gates landing
within 24 months of the payload's day, a due readout counting as landing now
(``gate_rows``' own "near" view). Each such gate is one row of the list, so the bars add up
to the header: on its own study's readout where the calendar carries it, else on a row of
its own at the gate's date (an FDA decision at the earliest the launch floor allows, a
registry date the calendar holds no row for, an overdue study under Overdue). A gate
later or undated is listed last, printed and never summed. To gain is the sum of (success
- now), at risk the sum of (now - failure), a share, against the close in the payload. A
readout on no priced gate adds to the count, not the value.

Pure functions of the payload of ``GET /companies/{t}/catalysts/view``. The shared
helpers, the fork and dates pictures, the risk cards and the dialog's blocks are
``catalysts_view``'s own; nothing here reads a network, a clock or Streamlit. A null is
never drawn as a zero: a gate without a leg prints "no free data" on that side.
"""

from __future__ import annotations

import datetime as dt
import json
import re

import catalysts_view as CV
from catalysts_view import MINUS, NO_DATA, esc, usd, pct, dm, dmy, mon

REVISION = 2

# --------------------------------------------------------------------------- layout
BAR_W = 300          # the bar column, drawn 1:1, its zero at the middle
BAR_H = 10
ROW_SVG_H = 18
LABEL_CHAR = 6.7     # a figure's character at the bars' 11px mono
WINDOW_DAYS = 731    # 24 months, the count window and the value window
NO_AREA = "No area on file"
AREA_SHORT = {"Immunology and inflammation": "Immunology", "Infectious disease": "Infectious",
              "Renal and hepatic": "Renal, hepatic"}
PHASE_TAG = {"p2": "Ph2", "p3": "Ph3", "filed": "FDA"}
GROUP_OVERDUE, GROUP_LATER = "Overdue", "Later or undated"

REASON_SHORT = {
    "no_gate_marketed": "marketed, label work",
    "no_gate": "outside the gate model",
    "other_indication": "indication not valued",
    "not_gate_phase": "not the gate's phase",
    "past_gate": "already at the FDA decision",
    "same_gate_later": "an earlier study decides the gate",
}
REASON_LONG = {
    "no_gate_marketed": "A marketed line: the readout is label work, outside the gate model.",
    "no_gate": "The line is outside the gate model.",
    "other_indication": "A study in an indication the forecast does not value.",
    "not_gate_phase": "A readout that does not decide the line's gate.",
    "past_gate": "The line is already at the FDA decision.",
    "same_gate_later": "An earlier study decides the same gate.",
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


def _ev_phase(e) -> str:
    return re.sub(r"Phase\s*", "Ph", str(e.get("phase") or ""))


def _month_end(d: dt.date) -> dt.date:
    return dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1) - dt.timedelta(days=1)


def _sort_key(d: dt.date, month) -> tuple:
    """(the month, the day): a readout the registry dates to the month alone sorts after
    the days of that month."""
    return (d.replace(day=1), 32 if month else d.day)


def _quarter(d: dt.date) -> tuple:
    return (d.year, (d.month - 1) // 3 + 1)


def _gate_nct(g):
    return (g.get("trial") or {}).get("nct_id")


def area_tag(area) -> str:
    return AREA_SHORT.get(area, area) if area else "no area"


# ------------------------------------------------------------------------ the gates
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


def _gate_tip(g) -> str:
    when, _ = CV.date_text(g)
    up = _sgn_usd(g["gain"])
    dn = _sgn_usd(-g["risk"]) if g["risk"] is not None else NO_DATA
    held = (f"; a lone miss is held at {usd(g['held_ps'])} while other Phase 3s run"
            if g["held_part"] > 0.004 else "")
    return (f"{g.get('name')} · {g['glabel']} · {when} · odds {pct(g.get('p_gate'))} · pass {up} "
            f"· miss {dn}{held}. Click for the full detail.")


# ------------------------------------------------------------------------- the rows
def _when_event(e, d, month) -> tuple:
    """(cell markup, hover) for a calendar readout's date: the month alone where the
    registry gives no day, "est." where the day is the registry's estimate."""
    if month:
        return f'<i>in</i> {CV.MON[d.month - 1]}', f"{mon(d)}: the registry gives the month, not the day"
    if e.get("confidence") in (None, "estimated", "anticipated"):
        return f'<i>est.</i> {dm(d)}', f"{dmy(d)}, the registry's estimate"
    return dm(d), f"{dmy(d)}, {e.get('confidence')}"


def _when_gate(g, today) -> tuple:
    """(cell markup, hover) for a gate's own row: an overdue study's passed date, an FDA
    decision's floor, or the gate study's registry date."""
    if g.get("due") and g.get("d"):
        return mon(g["d"]), f"{CV.day_text(g)}: past the registry date, no result on file"
    if g.get("fl"):
        fl = g["fl"]
        tip = (f"No earlier than {dmy(fl)}, the earliest approval the launch floor allows; "
               f"{g.get('why') or 'no decision date on file'}")
        if fl < today:
            return f'<i>≥</i> {mon(fl)}', tip + ". That floor is past, so it can come at any time"
        return f'<i>≥</i> {dm(fl)}', tip
    if g.get("d"):
        if g.get("dmonth"):
            return (f'<i>in</i> {CV.MON[g["d"].month - 1]}',
                    f"{CV.day_text(g)}: the registry gives the month, not the day")
        return f'<i>est.</i> {dm(g["d"])}', f"{dmy(g['d'])}, {g.get('date_basis') or 'the registry'}"
    return f'<span class="mu">{NO_DATA}</span>', "no date on file"


def _event_row(e, d, month, gate, today) -> dict:
    t = e.get("trial") or {}
    when, tip = _when_event(e, d, month)
    overdue = bool(gate and gate.get("due"))
    cond = (t.get("conditions") or [None])[0] if t.get("conditions") else None
    return {"kind": "event", "id": str(e.get("id")), "event": e, "gate": gate, "later": False,
            "group": GROUP_OVERDUE if overdue else _quarter(max(d, today)),
            "sort": _sort_key(max(d, today), month), "when": when, "when_tip": tip,
            "drug": e.get("asset") or "unmatched", "ph": CV.phase_class(e.get("phase")),
            "ph_txt": _ev_phase(e), "ind": cond, "area": e.get("area") or NO_AREA,
            "n": t.get("enrollment"), "nct": e.get("nct")}


def _gate_row(g, today) -> dict:
    t = g.get("trial") or {}
    later = not g["in24"]
    if later:
        when, tip = CV.date_text(g)[0], CV._when_long(g)
        key = g.get("fl") or g.get("d") or dt.date.max
        group, sort = GROUP_LATER, (key, 0)
    else:
        when, tip = _when_gate(g, today)
        key = g.get("fl") or g.get("d") or today
        if g.get("due"):
            group, sort = GROUP_OVERDUE, (key, 0)
        else:
            group = _quarter(max(key, today))
            sort = _sort_key(max(key, today), g.get("dmonth"))
    ind = t.get("indication") or (t.get("conditions") or t.get("indications") or [None])[0]
    return {"kind": "gate", "id": str(g["asset_id"]), "event": None, "gate": g, "later": later,
            "group": group, "sort": sort, "when": when, "when_tip": tip,
            "drug": g.get("name") or "unmatched", "ph": g["ph"], "ph_txt": PHASE_TAG.get(g["ph"], ""),
            "ind": ind, "area": g.get("area") or NO_AREA, "n": t.get("enrollment"),
            "nct": t.get("nct_id")}


def _group_order(group) -> tuple:
    if group == GROUP_OVERDUE:
        return (0, 0, 0)
    if group == GROUP_LATER:
        return (2, 0, 0)
    return (1,) + group


def readouts(p) -> list:
    """Every row of the list in order: the readouts dated within 24 months (a month the
    registry gives without a day counts from its first day to its last), each priced gate
    landing within 24 months on its own study's row or on one of its own, then the gates
    later or undated. A gate is on one row only."""
    today = CV._today(p)
    h24 = today + dt.timedelta(days=WINDOW_DAYS)
    gates = priced_gates(p)
    by_id = {g["asset_id"]: g for g in gates}
    rows, anchored = [], set()
    for e in p.get("events") or []:
        d, month = CV.day_or_month(e.get("date"))
        if d is None or d > h24 or (_month_end(d) if month else d) < today:
            continue
        g = by_id.get(e.get("gate_asset"))
        own = (g is not None and g["in24"] and g["asset_id"] not in anchored
               and _gate_nct(g) is not None and e.get("nct") == _gate_nct(g)
               and str(e.get("date")) == str(g.get("date")))
        if own:
            anchored.add(g["asset_id"])
        rows.append(_event_row(e, d, month, g if own else None, today))
    rows += [_gate_row(g, today) for g in gates if g["asset_id"] not in anchored]
    rows.sort(key=lambda r: (_group_order(r["group"]), r["sort"], r["drug"].lower()))
    return rows


def group_label(group) -> str:
    return group if isinstance(group, str) else f"Q{group[1]} {group[0]}"


def totals(rows, p) -> dict:
    """The header's figures, from the rows: the priced gates within 24 months summed, the
    rows within 24 months counted."""
    win = [r for r in rows if not r["later"]]
    gates = [r["gate"] for r in win if r["gate"]]
    return {"gain": sum(g["gain"] for g in gates if g["gain"] is not None),
            "risk": sum(g["risk"] for g in gates if g["risk"] is not None),
            "held": sum(g["held_part"] for g in gates),
            "n_gates": len(gates), "n_rows": len(win),
            "n_overdue": sum(1 for r in win if r["group"] == GROUP_OVERDUE),
            "n_fda": sum(1 for r in win if r["kind"] == "gate" and r["ph"] == "filed"),
            "n_later": sum(1 for r in rows if r["later"]),
            "missing": [g.get("name") for g in gates if g["gain"] is None or g["risk"] is None],
            "close": CV._close(p)}


def area_counts(rows) -> list:
    """(area, readouts, priced gates, to gain, at risk) for each area with a row within 24
    months, the busiest first."""
    out = {}
    for r in rows:
        if r["later"]:
            continue
        a = out.setdefault(r["area"], [r["area"], 0, 0, 0.0, 0.0])
        a[1] += 1
        g = r["gate"]
        if g:
            a[2] += 1
            a[3] += g["gain"] or 0
            a[4] += g["risk"] or 0
    return sorted((tuple(a) for a in out.values()), key=lambda a: (-a[1], a[0] == NO_AREA, a[0]))


# ------------------------------------------------------------------------- the bars
def scale(rows, w=BAR_W) -> dict:
    """One scale for every bar on the page, its zero at the middle of the column: dollars
    a share to pixels, room left at each end for the largest printed figure."""
    vals = [abs(v) for r in rows if r["gate"] and not r["later"]
            for v in (r["gate"]["gain"], r["gate"]["risk"]) if v is not None]
    vmax = max(vals + [0.01])
    pad = 8 + LABEL_CHAR * len(_sgn_usd(-vmax))
    x0 = w / 2
    return {"k": (x0 - pad) / vmax, "x0": x0, "w": w, "vmax": vmax}


def bar_svg(g, sc, h=BAR_H, height=ROW_SVG_H) -> str:
    """One gate's diverging bar: what a miss takes to the left of zero, hatched where a
    lone miss is held by other Phase 3s; what a pass adds to the right. Both printed, a
    missing leg as "no free data"."""
    W, x0, k = sc["w"], sc["x0"], sc["k"]
    y = (height - h) / 2
    ty = height / 2 + 4
    o = [f'<svg class="ca-bar cr-bar" viewBox="0 0 {W} {height}" width="{W}" height="{height}" '
         f'role="img" aria-label="A miss takes to the left, a pass adds to the right, dollars a share">',
         f'<line class="z" x1="{x0:.1f}" x2="{x0:.1f}" y1="0" y2="{height}"/>']
    gain, risk = g["gain"], g["risk"]
    if gain is not None:
        w = max(gain, 0) * k
        if w > 0:
            o.append(f'<rect class="up" x="{x0:.2f}" y="{y:.1f}" width="{max(w, 0.8):.2f}" height="{h}"/>')
        o.append(f'<text class="v up" x="{x0 + w + 4:.1f}" y="{ty:.1f}">{_sgn_usd(gain)}</text>')
    else:
        o.append(f'<text class="v mu" x="{x0 + 4:.1f}" y="{ty:.1f}">{NO_DATA}</text>')
    if risk is not None:
        w = max(risk, 0) * k
        wh = min(g["held_part"] * k, w)
        ws = w - wh
        if ws > 0.05:
            o.append(f'<rect class="dn" x="{x0 - ws:.2f}" y="{y:.1f}" width="{max(ws, 0.8):.2f}" height="{h}"/>')
        if wh > 0.05:
            o.append(f'<rect class="hd" x="{x0 - w:.2f}" y="{y:.1f}" width="{max(wh, 0.8):.2f}" height="{h}"/>')
        o.append(f'<text class="v dn" x="{x0 - w - 4:.1f}" y="{ty:.1f}" text-anchor="end">'
                 f'{_sgn_usd(-risk)}</text>')
    else:
        o.append(f'<text class="v mu" x="{x0 - 4:.1f}" y="{ty:.1f}" text-anchor="end">{NO_DATA}</text>')
    o.append("</svg>")
    return "".join(o)


def axis_svg(sc) -> str:
    """The bar column's head: a miss takes and a pass adds either side of zero."""
    W, H, x0 = sc["w"], 14, sc["x0"]
    return (f'<svg class="ca-axis" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
            f'aria-label="Bar key, dollars a share"><line class="z" x1="{x0:.1f}" x2="{x0:.1f}" '
            f'y1="0" y2="{H}"/><text class="hk dn" x="{x0 - 6:.1f}" y="10" text-anchor="end">'
            f'◂ A miss takes</text><text class="hk up" x="{x0 + 6:.1f}" y="10">A pass adds ▸</text>'
            f'</svg>')


# ------------------------------------------------------------------------ the header
def header_html(p, t) -> str:
    close = t["close"]
    kick = (f"$ a share against the {usd(close)} close on {dmy(p.get('close_date'))} · "
            f"click a row for its card" if close else "$ a share · click a row for its card")
    if t["n_gates"]:
        gp = f" · {pct(t['gain'] / close, 1)} of price" if close else ""
        lone = t["risk"] - t["held"]
        held = f" · a lone study miss takes {usd(lone)}" if t["held"] > 0.004 else ""
        figs = [("up", _sgn_usd(t["gain"]), "to gain",
                 f"if all {CV._plural(t['n_gates'], 'priced gate')} pass{gp}",
                 "Each priced gate landing within 24 months: its pass leg less today's value, "
                 "summed. The model's figures; each gate is one row of the list."),
                ("dn", _sgn_usd(-t["risk"]), "at risk", f"if every one fails{held}",
                 f"Today's value to the fail leg, nil by the model's convention, summed over the "
                 f"same gates. {usd(t['held'])} of it is held while other Phase 3s run: a lone "
                 f"study miss takes {usd(lone)}.")]
    else:
        later = (f"; {CV._plural(t['n_later'], 'priced gate')} later or undated"
                 if t["n_later"] else "")
        figs = [("mu nil", "none", "to gain", f"no priced gate within 24 months{later}",
                 "No priced gate lands within 24 months, so the readouts are counted, not valued."),
                ("mu nil", "none", "at risk", "nothing priced to lose in the window",
                 "No priced gate lands within 24 months.")]
    sub = f"next 24 months · {t['n_gates']} priced"
    sub += f" · {t['n_overdue']} overdue" if t["n_overdue"] else ""
    fda = (f" {CV._plural(t['n_fda'], 'FDA decision')} on a priced gate {'is' if t['n_fda'] == 1 else 'are'} "
           f"listed at the earliest date the launch floor allows." if t["n_fda"] else "")
    figs.append(("", str(t["n_rows"]), "readouts", sub,
                 "Every dated readout on the registry in the next 24 months, and each priced "
                 f"gate landing in them.{fda} A readout that decides no priced gate adds to the "
                 "count, not the value."))
    cells = "".join(f'<div class="ca-fig" title="{esc(tip)}"><span class="v m {tone}">{esc(v)}</span>'
                    f'<span class="k"><b>{esc(k)}</b> {esc(s)}</span></div>'
                    for tone, v, k, s, tip in figs)
    return (f'<div class="ca-hd cr-hd"><div class="ca-hd-l"><div class="cr-title">Upcoming readouts'
            f'<span>next 24 months, soonest first</span></div><div class="ca-kick">{esc(kick)}</div>'
            f'</div><div class="ca-figs">{cells}</div></div>')


# -------------------------------------------------------------------------- the list
def _row_tip(r) -> str:
    if r["gate"] is not None:
        return _gate_tip(r["gate"])
    e = r["event"] or {}
    why = REASON_SHORT.get(_reason_key(e), "not priced")
    return f"{e.get('nct') or ''} · no priced gate: {why}. Click for the trial's card."


def _status(r, sc) -> tuple:
    """(odds cell, bar cell) of a row."""
    g = r["gate"]
    if g is None:
        return "", '<span class="cr-np">no priced gate</span>'
    odds = CV._num(g.get("p_gate"))
    oc = (f'<span class="m">{pct(odds)}</span>' if odds is not None
          else f'<span class="mu" title="{NO_DATA}">n/a</span>')
    if r["later"]:
        dn = _sgn_usd(-g["risk"]) if g["risk"] is not None else NO_DATA
        return oc, (f'<span class="cr-lt m"><b class="up-t">{_sgn_usd(g["gain"])}</b> if it passes · '
                    f'<b class="dn-t">{dn}</b> if it fails</span>')
    return oc, bar_svg(g, sc)


def row_html(r, sc) -> str:
    g = r["gate"]
    hit = f'data-gate="{g["asset_id"]}"' if g is not None else f'data-ev="{esc(r["id"])}"'
    cls = "cr-row" + (" pr" if g is not None and not r["later"] else "") + (" lt" if r["later"] else "")
    n = r["n"]
    pts = f'{n:,}' if isinstance(n, (int, float)) and n else f'<span class="mu">{NO_DATA}</span>'
    ind = (f'<span class="c-ind" title="{esc(r["ind"])}">{esc(r["ind"])}</span>' if r["ind"]
           else f'<span class="c-ind mu">{NO_DATA}</span>')
    odds, bar = _status(r, sc)
    ph = (f'<i class="mk-ph {r["ph"]}">{esc(r["ph_txt"])}</i>' if r["ph_txt"]
          else f'<span class="mu">{NO_DATA}</span>')
    return (f'<div class="{cls}" {hit} data-area="{esc(r["area"])}" title="{esc(_row_tip(r))}">'
            f'<span class="c-date m" title="{esc(r["when_tip"])}">{r["when"]}</span>'
            f'<span class="c-drug" title="{esc(r["drug"])}">{esc(r["drug"])}</span>'
            f'<span class="c-ph">{ph}</span>{ind}'
            f'<span class="c-area"><em title="{esc(r["area"])}">{esc(area_tag(r["area"]) if r["area"] != NO_AREA else "no area")}</em></span>'
            f'<span class="c-n m">{pts}</span><span class="c-odds">{odds}</span>'
            f'<span class="c-bar">{bar}</span></div>')


def _group_stats(rows) -> dict:
    """For a group's heading: {area or "*": [readouts, priced, to gain, at risk]} printed."""
    out = {}
    for r in rows:
        for key in ("*", r["area"]):
            s = out.setdefault(key, [0, 0, 0.0, 0.0])
            s[0] += 1
            if r["gate"] is not None and not r["later"]:
                s[1] += 1
                s[2] += r["gate"]["gain"] or 0
                s[3] += r["gate"]["risk"] or 0
    return {k: [n, k_, _sgn_usd(gn) if k_ else "", _sgn_usd(-rk) if k_ else ""]
            for k, (n, k_, gn, rk) in out.items()}


def _group_head(group, rows) -> str:
    stats = _group_stats(rows)
    n, k, gn, rk = stats["*"]
    if group == GROUP_OVERDUE:
        sub = "past the registry date, no result on file"
    elif group == GROUP_LATER:
        sub = "priced gates past 24 months or undated, not in the totals"
    else:
        sub = f"{CV._plural(n, 'readout')}" + (f" · {k} priced" if k else "")
    sums = (f'<span class="s m"><b class="up-t">{esc(gn)}</b><b class="dn-t">{esc(rk)}</b></span>'
            if gn and group != GROUP_LATER else '<span class="s m"><b class="up-t"></b><b class="dn-t"></b></span>')
    kind = "later" if group == GROUP_LATER else "od" if group == GROUP_OVERDUE else "q"
    return (f'<div class="cr-gh {kind}" data-st="{esc(json.dumps(stats, ensure_ascii=False))}">'
            f'<span class="q">{esc(group_label(group))}</span><span class="sub">{esc(sub)}</span>'
            f'{sums}</div>')


def list_html(rows, sc, t) -> str:
    head = ('<div class="cr-th"><span class="c-date">Date</span><span class="c-drug">Drug</span>'
            '<span class="c-ph">Phase</span><span class="c-ind">Indication</span>'
            '<span class="c-area">Area</span><span class="c-n">Patients</span>'
            f'<span class="c-odds">Odds</span><span class="c-bar">{axis_svg(sc)}</span></div>')
    body, cur, chunk = [], None, []

    def flush():
        if chunk:
            body.append(_group_head(cur, chunk) + "".join(row_html(r, sc) for r in chunk))

    for r in rows:
        if r["group"] != cur:
            flush()
            cur, chunk = r["group"], []
        chunk.append(r)
    flush()
    if not rows:
        body.append('<div class="cx-empty cr-none">No dated readout on file for the next 24 months.</div>')
    foot = ('<div class="ca-foot cr-foot"><span class="key"><i class="k-up"></i>a pass adds</span>'
            '<span class="key"><i class="k-dn"></i>a miss takes</span>'
            '<span class="key"><i class="k-hd"></i>held while other Phase 3s run</span>'
            f'<span class="nt">{esc(footnote(t))}</span></div>')
    return (f'<div class="cr-list">{head}<div class="cr-rows">{"".join(body)}</div></div>{foot}')


def footnote(t) -> str:
    """What the bars count, said under the list: the 24-month rule, one row a gate, the
    later gates and the count-only readouts."""
    one = t["n_later"] == 1
    later = (f" {CV._plural(t['n_later'], 'later or undated gate')} {'is' if one else 'are'} "
             f"listed last, not in the totals." if t["n_later"] else "")
    if not t["n_gates"]:
        return (f"No priced gate lands within 24 months, so nothing is summed.{later} A readout "
                f"on no priced gate adds to the count, not the value.")
    return (f"Totals sum the {CV._plural(t['n_gates'], 'priced gate')} landing within 24 months, "
            f"one row each; an overdue readout counts as landing now.{later} A readout on no "
            f"priced gate adds to the count, not the value.")


# ------------------------------------------------------------------------- the rail
def chips_html(rows) -> str:
    counts = area_counts(rows)
    n = sum(c[1] for c in counts)
    out = [f'<a class="cr-chip on" data-af="*" title="Every area">All <b class="m">{n}</b></a>']
    for area, k, priced, gain, risk in counts:
        tip = (f"{area}: {CV._plural(k, 'readout')} in 24 months, {priced} priced"
               + (f", {_sgn_usd(gain)} to gain, {_sgn_usd(-risk)} at risk" if priced else ""))
        label = area_tag(area) if area != NO_AREA else "No area"
        out.append(f'<a class="cr-chip" data-af="{esc(area)}" title="{esc(tip)}">{esc(label)} '
                   f'<b class="m">{k}</b></a>')
    return (f'<div class="ca-sec"><span class="h">By area</span><span class="c">filter the list</span></div>'
            f'<div class="cr-chips">{"".join(out)}</div>')


def index_items(p, rows) -> list:
    """The index of what sits one click away: (key, label, figure, short line, tooltip). The
    figures are the risk cards' own, so the two never disagree; the line is cut to a few
    words and the card's full sentence rides as the tooltip."""
    cards = {c[0]: c for c in CV.risk_cards(p)}
    today = CV._today(p)
    plain = lambda x: re.sub(r"<[^>]+>", "", str(x or ""))  # noqa: E731
    items = []
    n_cal = len(calendar_rows(rows))
    items.append(("cal", "Calendar", str(n_cal),
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
                  "readouts the catalyst calendar leaves unpriced, by reason",
                  "The catalyst calendar's own count, every event it holds: marketed lines, "
                  "indications the forecast does not value, and studies that do not decide a "
                  "gate. The list counts by the gate model, so the two can differ."))
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
    """The whole first view: the header, the dated list and the rail."""
    rows = readouts(p)
    sc = scale(rows)
    t = totals(rows, p)
    return (f'<div class="cx ca-page cr-page">{HATCH}{header_html(p, t)}'
            f'<div class="ca-body"><div class="ca-main">{list_html(rows, sc, t)}</div>'
            f'<div class="ca-rail">{chips_html(rows)}{index_html(p, rows)}</div></div></div>')


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


def _event(p, ev_id):
    return next((e for e in p.get("events") or [] if str(e.get("id")) == str(ev_id)), None)


def readout_title(p, ev_id) -> str:
    e = _event(p, ev_id)
    if e is None:
        return "Readout"
    what = f"{e['phase']} readout" if e.get("phase") else "readout"
    return f"{e.get('asset') or 'unmatched'} · {what}"


def readout_card(p, ev_id) -> tuple:
    """A readout on no priced gate in full, as (markup, the line's gate id or None): the
    trial, its date and patients, why it carries no price, and the line's priced gate where
    it has one, which the caller offers to open."""
    e = _event(p, ev_id)
    if e is None:
        return '<div class="cx cx-dlg rd"><div class="cx-empty">This readout is not on file.</div></div>', None
    t = e.get("trial") or {}
    d, month = CV.day_or_month(e.get("date"))
    gates = {g["asset_id"]: g for g in priced_gates(p)}
    rows = readouts(p)
    g = gates.get(e.get("gate_asset"))
    here = next((r for r in rows if r["kind"] == "event" and r["id"] == str(e.get("id"))), None)
    if here and here["gate"] is not None:     # a gate's own row opens the gate's dialog
        g = here["gate"]
    when = (f"{mon(d)}, the registry gives the month" if month else
            f"{dmy(d)}, the registry's estimate" if d and e.get("confidence") in (None, "estimated", "anticipated")
            else dmy(d) if d else NO_DATA)
    url = e.get("url") or (f"https://clinicaltrials.gov/study/{e['nct']}" if e.get("nct") else "")
    reg = (f'<a href="{esc(url)}" target="_blank" rel="noopener" title="{esc(t.get("title") or e.get("title") or "")}">'
           f'{esc(e.get("nct") or "registry record")} ›</a>' if url else esc(e.get("nct") or NO_DATA))
    n = t.get("enrollment")
    conds = ", ".join(t.get("conditions") or []) or NO_DATA
    left = [CV._kv("Registry", reg), CV._kv("Status", esc(t.get("overall_status") or NO_DATA)),
            CV._kv("Patients", f"{n:,}" if n else NO_DATA), CV._kv("Conditions", esc(conds)),
            CV._kv("Started", dmy(t.get("start_date")) if CV._d(t.get("start_date")) else NO_DATA)]
    s = e.get("slip") or {}
    if s.get("old") and s.get("new") and s.get("days"):
        left.append(CV._kv("Date moved", f'{dmy(s["new"])} · was {dmy(s["old"])} · '
                                         f'<b class="{"dn-t" if s["days"] > 0 else "up-t"}">'
                                         f'{CV._plural(abs(s["days"]), "day")} '
                                         f'{"later" if s["days"] > 0 else "earlier"}</b>'
                                         + (f', seen {dmy(s.get("seen"))}' if s.get("seen") else "")))
    why = esc(e.get("why") or REASON_LONG.get(_reason_key(e), "No priced gate on file for this line."))
    right = [f'<div class="cx-p">{why}</div>']
    offer = None
    if g is not None:
        offer = g["asset_id"]
        whn = CV.date_text(g)[0]
        where = ("counted once, on its own row" if g["in24"]
                 else "past 24 months or undated, so not in the totals")
        legs = (f'odds {pct(g.get("p_gate"))} · <b class="up-t">{_sgn_usd(g["gain"])}</b> if it passes · '
                f'<b class="dn-t">{_sgn_usd(-g["risk"]) if g["risk"] is not None else NO_DATA}</b> if it fails')
        right.append(CV._kv("The line's gate", f'{esc(g["glabel"])}, {esc(whn)}: {where}'))
        right.append(CV._kv("Priced at", legs))
    if e.get("priced") and CV._num(e.get("per_share")) is not None:
        right.append(CV._kv("Calendar stake", f'{usd(e["per_share"])} a share, pass against miss; '
                                              f'not in the totals, which sum the gate model\'s gates'))
    lv = CV._num(e.get("line_value"))
    right.append(CV._kv("Line in the model", f"{usd(lv)} a share" if lv is not None else NO_DATA))
    if e.get("marketed"):
        right.append(CV._kv("On the market", "yes: the line already sells"))
    ph = (f'<i class="mk-ph {CV.phase_class(e.get("phase"))}">{esc(_ev_phase(e))}</i>'
          if e.get("phase") else "")
    head = (f'<div class="rd-hd"><span class="rd-a">{esc(e.get("area") or NO_AREA)}</span>{ph}'
            f'<span>{esc(when)}{", primary completion" if t else ""}</span>'
            f'<span class="rd-np">no priced gate</span></div>')
    return (f'<div class="cx cx-dlg rd">{head}<div class="gd-2">'
            f'<div><div class="cx-dh2">The trial</div>{"".join(left)}</div>'
            f'<div><div class="cx-dh2">Why it carries no price</div>{"".join(right)}</div></div></div>',
            offer)


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
    return f"{title} · {area}" if key == "cal" and area and area != "*" else title


def calendar_rows(rows) -> list:
    """The rows the calendar draws: every one within 24 months and not overdue."""
    return [r for r in rows if not r["later"] and r["group"] != GROUP_OVERDUE]


def calendar_html(p, area=None) -> str:
    """Every readout in the next 24 months, areas down the side and months across: a cell
    counts the readouts, a ring marks one on a priced gate. Under it, the list for the area
    asked for (or every area), month by month, each name linked to its registry record."""
    area = None if area in (None, "", "*") else area
    rows = calendar_rows(readouts(p))
    today = CV._today(p)
    months = []
    y, m = today.year, today.month
    for _ in range(25):
        months.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    by_area = {}
    for r in rows:
        by_area.setdefault(r["area"], []).append(r)
    areas = sorted(by_area, key=lambda a: (-len(by_area[a]), a == NO_AREA, a))
    W, lw, rh = 1040, 190, 24
    cw = (W - lw) / len(months)
    H = 22 + rh * len(areas) + 4
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
    for r in rows:
        d = r["sort"][0]
        k = (r["area"], d.year, d.month)
        cells.setdefault(k, []).append(r)
        big = max(big, len(cells[k]))
    for j, a in enumerate(areas):
        y0 = 20 + j * rh
        on = area == a
        o.append(f'<text class="an{" on" if on else ""}" x="0" y="{y0 + 15}">{esc(a)}</text>'
                 f'<line class="rl" x1="0" x2="{W}" y1="{y0 + rh}" y2="{y0 + rh}"/>')
        for i, (yy, mm) in enumerate(months):
            rs = cells.get((a, yy, mm)) or []
            if not rs:
                continue
            x = lw + i * cw
            n = len(rs)
            pr = any(r["gate"] is not None for r in rs)
            op = 0.25 + 0.75 * n / big
            tip = "; ".join(f'{re.sub("<[^>]+>", "", r["when"])} {r["drug"]} {r["ph_txt"]}' for r in rs)
            o.append(f'<g><title>{esc(tip)}</title><rect class="c{" pr" if pr else ""}" x="{x + 2:.1f}" '
                     f'y="{y0 + 3}" width="{cw - 4:.1f}" height="{rh - 6}" style="fill-opacity:{op:.2f}"/>'
                     f'<text class="cn" x="{x + cw / 2:.1f}" y="{y0 + 16}" text-anchor="middle">{n}</text></g>')
    o.append("</svg>")
    sel = [r for r in rows if area is None or r["area"] == area]
    lst, cur = [], None
    for r in sel:
        d = r["sort"][0]
        k = (d.year, d.month)
        if k != cur:
            cur = k
            lst.append(f'<div class="md-mo m">{CV.MON[d.month - 1]} {d.year}</div>')
        g = r["gate"]
        if g is not None:
            why = (f'<span class="up-t">priced · odds {pct(g.get("p_gate"))} · {_sgn_usd(g["gain"])} if it '
                   f'passes</span>')
        else:
            why = esc(REASON_SHORT.get(_reason_key(r["event"] or {}), "not priced"))
        name = f'<b>{esc(r["drug"])}</b>'
        url = (r["event"] or {}).get("url")
        if url:
            name = f'<a href="{esc(url)}" target="_blank" rel="noopener">{name}</a>'
        lst.append(f'<div class="md-ev"><span class="m">{re.sub("<[^>]+>", "", r["when"])}</span>'
                   f'<span>{name} <i class="mk-ph {r["ph"]}">{esc(r["ph_txt"])}</i></span>'
                   f'<span class="mu">{esc(r["area"])}</span>'
                   f'<span class="mu el">{esc(r["ind"] or "")}</span><span class="w">{why}</span></div>')
    who = esc(area) if area else "Every area"
    return (f'<div class="cx cx-dlg md ca-cal"><div class="md-k">Readouts a month, by area · the darker the cell, the '
            f'more readouts · <span class="pr-k"></span> one on a priced gate · the rule marks 12 months</div>'
            f'{"".join(o)}<div class="md-lh">{who}: {CV._plural(len(sel), "readout")}, every date an '
            f'estimate from the registry</div><div class="md-list">{"".join(lst)}</div></div>')
