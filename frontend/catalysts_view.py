"""The redesigned Catalysts tab: what can move the share, on one screen (AstraZeneca first).

Pure builders over the payload of ``GET /companies/{t}/catalysts/view``
(backend/catalysts_command.py). Every function takes the payload, or a slice of it, and
returns a markup string: HTML for ``st.markdown`` and the ``catnav`` frame, with complete
``<svg>`` elements inside. None of them touches Streamlit, the network or a clock, so the
tests run them on a saved payload.

Ported from the approved mockups (design_ui/catalysts_b/build_catalysts_b.py, the base:
the header, the range chart, the gate card, next up, the risk register and why events
carry no price; design_ui/catalysts_a/build_mockup.py, the grafts: the timeline by therapy
area and the full-detail dialog), refitted to one 1440 x 900 screen: the timeline and the
range chart share one frame on the left, the selected gate and the secondary panels share
one tabbed rail on the right. Hand-placed parts are replaced by rules: marks are swarmed
and labels placed by a greedy collision search, and every figure is computed here from
the payload. Colour comes from catalysts.css through classes, so the SVGs carry no colour
literal. A null is never drawn as a zero: it is left off the chart and named, or printed
as "no free data".

The gate card and the dialog take the Next gate block's facts and the development tables
as markup the page builds with the Forecast tab's own builders (streamlit_app ``_gate_*``),
so the cost to reach, the net and the launch floor read the same on both tabs.
"""

from __future__ import annotations

import datetime as dt
import html
import math
import re

REVISION = 1
MINUS = "−"
NO_DATA = "no free data"
MON = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

# gate -> (phase class, label, short tag)
GATES = {
    "p2_to_p3": ("p2", "Phase 2 readout", "Ph 2"),
    "p3_to_nda": ("p3", "Phase 3 readout", "Ph 3"),
    "nda_to_approval": ("filed", "FDA decision", "FDA"),
}
GROUPS = (("Next 12 months", "near"), ("12 to 24 months", "near"), ("Later", "far"),
          ("No date on file", "far"))
VIEWS = (("near", "Next 24 months"), ("far", "Later or undated"))
# The rows a view of the range chart draws before it names the rest in one line.
VIEW_ROWS = 15
# The card's facts, taken from the Next gate block's rows (streamlit_app._gate_rows): the
# legs are drawn as the fork above them, so only what the fork does not show.
CARD_FACTS = ("chance", "cost to reach", "net", "at DiMasi's level", "earliest approval")
# Why an event carries no price, in a few words (stakes unpriced[].reason).
WHY_SHORT = {"no_gate": "outside the gate model", "other_indication": "indication not valued",
             "not_gate_phase": "not the gate's phase", "past_gate": "past its gate",
             "same_gate_later": "an earlier study decides the gate"}
REASONS = (
    ("no_gate", "marketed or outside the gate model"),
    ("other_indication", "a study in an indication the forecast does not value"),
    ("not_gate_phase", "a readout that does not decide the gate"),
    ("past_gate", "an asset already at the FDA decision"),
    ("same_gate_later", "an earlier study decides the same gate"),
)
REASON_CLASS = {"no_gate": "u0", "other_indication": "u1", "not_gate_phase": "u2",
                "past_gate": "u3", "same_gate_later": "u4"}
EVIDENCE = {"published": "published", "convention": "convention", "implied": "implied",
            "stated": "stated"}


# ------------------------------------------------------------------------------ helpers
def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v if math.isfinite(v) else None


def usd(v, dp=2) -> str:
    """A figure a share: "$6.60", "−$1.14"; "no free data" where there is none."""
    v = _num(v)
    if v is None:
        return NO_DATA
    s = f"${abs(v):,.{dp}f}"
    return (MINUS + s) if v < 0 and round(abs(v), dp) else s


def sgn(v, dp=2) -> str:
    """A signed move: "+2.54", "−1.14", "0.00"."""
    v = _num(v)
    if v is None:
        return NO_DATA
    s = f"{abs(v):,.{dp}f}"
    if not round(abs(v), dp):
        return s
    return ("+" if v > 0 else MINUS) + s


def pct(v, dp=0) -> str:
    v = _num(v)
    return NO_DATA if v is None else f"{v * 100:.{dp}f}%"


def _d(iso):
    try:
        return dt.date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return None


def mon(x) -> str:
    """ "Apr 2028" from a date or an ISO string."""
    x = x if isinstance(x, dt.date) else _d(x)
    return f"{MON[x.month - 1]} {x.year}" if x else NO_DATA


def dmy(x) -> str:
    x = x if isinstance(x, dt.date) else _d(x)
    return f"{x.day} {MON[x.month - 1]} {x.year}" if x else NO_DATA


def dm(x) -> str:
    x = x if isinstance(x, dt.date) else _d(x)
    return f"{x.day} {MON[x.month - 1]}" if x else NO_DATA


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }".replace(" ", "")


def _plural(n, word, many=None):
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _today(p) -> dt.date:
    return _d(p.get("today")) or dt.date(1970, 1, 1)


def _close(p):
    return _num(p.get("close"))


def _ticker(p) -> str:
    return str(p.get("ticker") or "")


def section_html(label, basis="", count="", extra="") -> str:
    """The house section rule as one string."""
    chip = f'<span class="sec-basis">{esc(basis)}</span>' if basis else ""
    tail = f'<span class="sec-count">{esc(count)}</span>' if count else ""
    return f'<div class="sec"><span class="sec-label">{esc(label)}</span>{chip}{extra}{tail}</div>'


def phase_class(phase) -> str:
    """The phase ramp class of an event: seamless studies sit at the phase they reach."""
    s = str(phase or "")
    if "3" in s:
        return "p3"
    if "2" in s:
        return "p2"
    if "1" in s:
        return "p1"
    if "4" in s:
        return "p4"
    return "p3"


def _tw(s, size=10.0, mono=False, bold=False) -> float:
    """A rough width for a label, for the collision checks."""
    return len(s) * size * (0.6 if mono else (0.58 if bold else 0.54))


# ------------------------------------------------------------------------- the gates
def gate_rows(p) -> list:
    """Every line with a priced next gate, shaped for the page: its group by when the gate
    lands, the legs a share, what a miss takes and the date as the page prints it. Ranked
    by swing within each group."""
    today = _today(p)
    h12, h24 = today + dt.timedelta(days=365), today + dt.timedelta(days=731)
    rows = []
    for g in p.get("gates") or []:
        ph, label, short = GATES.get(g.get("gate"), ("p3", g.get("label") or "next gate", "gate"))
        date, floor = _d(g.get("date")), _d(g.get("floor"))
        key = floor or date
        if g.get("due") or (key and key <= h12):
            grp = 0
        elif key is None:
            grp = 3
        elif key <= h24:
            grp = 1
        else:
            grp = 2
        now, success, failure = _num(g.get("now")), _num(g.get("success")), _num(g.get("failure"))
        held = g.get("held") if isinstance(g.get("held"), dict) else {}
        held_ps = _num(held.get("per_share"))
        swing = (success - failure) if None not in (success, failure) else None
        rows.append({**g, "ph": ph, "glabel": g.get("label") or label, "short": short,
                     "d": date, "fl": floor, "grp": grp, "view": GROUPS[grp][1],
                     "now": now, "success": success, "failure": failure, "swing": swing,
                     "held_ps": held_ps, "up": (success - now) if None not in (success, now) else None,
                     "priced": bool(g.get("stake"))})
    rows.sort(key=lambda r: (r["grp"], -(r["swing"] or 0), r.get("name") or ""))
    by_swing = sorted(rows, key=lambda r: -(r["swing"] or 0))
    for i, r in enumerate(by_swing):
        r["rank"] = i + 1
    return rows


def default_gate(p):
    """The gate the page opens on: the largest swing."""
    rows = gate_rows(p)
    return max(rows, key=lambda r: r["swing"] or 0)["asset_id"] if rows else None


def selected_gate(p, wanted):
    """``wanted`` where the payload has that gate, else the largest swing."""
    ids = {r["asset_id"] for r in gate_rows(p)}
    try:
        wanted = int(wanted)
    except (TypeError, ValueError):
        wanted = None
    return wanted if wanted in ids else default_gate(p)


def date_text(r) -> tuple:
    """The date cell and its flag: an estimated registry date, an FDA floor, a due
    readout, or none on file."""
    if r.get("due") and r.get("d"):
        return mon(r["d"]), "due"
    if r.get("fl"):
        return f"≥ {mon(r['fl'])}", ""
    if r.get("d"):
        return f"est. {mon(r['d'])}", ""
    return "no date", ""


def miss_move(r) -> tuple:
    """(text, value) for what a miss of the gate study takes off today's value: "held"
    where other Phase 3s keep the line at today's value until they read out."""
    now, failure = r.get("now"), r.get("failure")
    if r.get("held_ps") is not None and now is not None:
        m = now - r["held_ps"]
        return ("held", 0.0) if m < 0.005 else (sgn(-m), -m)
    if None in (now, failure):
        return NO_DATA, None
    return sgn(-(now - failure)), -(now - failure)


def _when_long(r) -> str:
    if r.get("due") and r.get("d"):
        return f"due {dmy(r['d'])}, no result on file"
    if r.get("fl"):
        return f"no date on file, earliest {dmy(r['fl'])}"
    if r.get("d"):
        return f"est. {dmy(r['d'])}"
    return "no date on file"


# ---------------------------------------------------------------------------- header
def totals(p) -> dict:
    """The sums the header prints, each over the gates on the payload."""
    rows = gate_rows(p)
    today = _today(p)
    out = {"n": len(rows),
           "now": sum(r["now"] for r in rows if r["now"] is not None),
           "success": sum(r["success"] for r in rows if r["success"] is not None),
           "failure": sum(r["failure"] for r in rows if r["failure"] is not None),
           "swing": sum(r["swing"] for r in rows if r["swing"] is not None)}
    g12 = [r for r in rows if r["grp"] == 0]
    out["n12"], out["swing12"] = len(g12), sum(r["swing"] or 0 for r in g12)
    out["top12"] = max(g12, key=lambda r: r["swing"] or 0) if g12 else None
    priced = [r for r in rows if r["priced"]]
    out["n_priced"], out["swing_priced"] = len(priced), sum(r["swing"] or 0 for r in priced)
    costed = [((r.get("development") or {}).get("gate") or {}) for r in rows
              if (r.get("development") or {}).get("ok")]
    costs = [_num(g.get("cost_per_share")) for g in costed]
    out["cost"] = sum(c for c in costs if c is not None) if any(
        c is not None for c in costs) else None
    out["n_costed"] = sum(1 for c in costs if c is not None)
    slips = [s for s in p.get("slips") or [] if s.get("days")]
    on_gate = [s for s in slips if s.get("gate_asset")]
    out["slip"] = (max(on_gate, key=lambda s: s["days"]) if on_gate
                   else max(slips, key=lambda s: s["days"]) if slips else None)
    out["today"] = today
    return out


def lead_sentence(p) -> str:
    """One sentence on where the value at stake sits and when, from the gates alone. No
    sentence where there is no gate to price."""
    rows = gate_rows(p)
    t = totals(p)
    if not rows or not t["swing"]:
        return ""
    who = _ticker(p)
    top = sorted(rows, key=lambda r: -(r["swing"] or 0))
    a = top[0]
    first = ""
    if len(top) >= 2 and (top[0]["swing"] + top[1]["swing"]) >= 0.5 * t["swing"]:
        b = top[1]
        pair = top[0]["swing"] + top[1]["swing"]
        same_label = a["glabel"] == b["glabel"]
        ya, yb = (a["d"] or a["fl"]), (b["d"] or b["fl"])
        same_year = ya and yb and ya.year == yb.year
        ind_a = ((a.get("trial") or {}).get("indication") or "")
        ind_b = ((b.get("trial") or {}).get("indication") or "")
        if same_label and same_year and ind_a and ind_a == ind_b and "," not in ind_a:
            first = (f"Two {esc(ind_a.lower())} {esc(a['glabel'].replace('readout', 'readouts'))} "
                     f"in {ya.year} decide <b class=\"up\">{usd(pair)}</b> of the "
                     f"<b>{usd(t['swing'])}</b> a share riding on {esc(who)}'s next "
                     f"gates.")
        else:
            first = (f"{esc(a['name'])} and {esc(b['name'])} decide "
                     f"<b class=\"up\">{usd(pair)}</b> of the <b>{usd(t['swing'])}</b> a share "
                     f"riding on {esc(who)}'s next gates.")
    else:
        first = (f"{esc(a['name'])}'s {esc(a['glabel'])} is the largest piece, "
                 f"<b class=\"up\">{usd(a['swing'])}</b> of the <b>{usd(t['swing'])}</b> a "
                 f"share riding on {esc(who)}'s next gates.")
    if t["n12"]:
        top12 = t["top12"]
        second = (f" The next 12 months carry <b>{usd(t['swing12'])}</b> across "
                  f"{_plural(t['n12'], 'gate')}")
        if top12 and not top12["d"]:
            second += (f", and the largest, {esc(top12['name'])}'s {esc(top12['glabel'])}, "
                       f"has no date on file.")
        elif top12 and top12.get("due"):
            second += (f", and the largest, {esc(top12['name'])}'s {esc(top12['glabel'])}, "
                       f"was due {mon(top12['d'])} with no result on file.")
        elif top12:
            second += (f"; the largest is {esc(top12['name'])}'s {esc(top12['glabel'])}, "
                       f"est. {mon(top12['d'])}.")
        else:
            second += "."
    else:
        second = " No gate lands in the next 12 months."
    return first + second


def header_html(p) -> str:
    """The header row: the kicker and the sentence, and five figures."""
    t = totals(p)
    close = _close(p)
    kick = (f"Value at stake · model, $ a share · against the {usd(close)} close on "
            f"{dmy(p.get('close_date'))}" if close else "Value at stake · model, $ a share")
    sentence = lead_sentence(p)
    if not sentence:
        sentence = (f"No pipeline line of {esc(_ticker(p))} carries a priced next gate on "
                    f"this book, so nothing here is sized by value at stake.")
    figs = []
    if t["n"]:
        share = f" · {pct(t['now'] / close, 1)} of price" if close else ""
        figs.append((usd(t["now"]), f"today on {_plural(t['n'], 'gate')}{share}",
                     "", "the model's risked value a share on every line with a priced next "
                         "gate"))
        fail = ("nil if all fail" if not t["failure"]
                else f"{usd(t['failure'])} if all fail")
        figs.append((usd(t["success"]), f"if every gate passes · {fail}", "",
                     "each line's success leg, summed; a failure is nil by the model's "
                     "convention unless a stated leg is on file"))
        figs.append((usd(t["swing12"]), f"at stake in 12 months · "
                                         f"{_plural(t['n12'], 'gate')}", "",
                     "pass leg less fail leg, summed over the gates due by "
                     f"{dmy(t['today'] + dt.timedelta(days=365))}"))
        if t["cost"] is not None:
            figs.append((usd(t["cost"]), f"cost to reach them · {t['n_costed']} of "
                                         f"{t['n']} costed", "",
                         "the development view: published trial costs after tax at the "
                         "company's share, 2018 prices, not restated"))
        else:
            figs.append((NO_DATA, "cost to reach the next gates", "none", ""))
    else:
        figs += [(NO_DATA, "carried on gated lines", "none", ""),
                 (NO_DATA, "if every gate passes", "none", ""),
                 (NO_DATA, "at stake in 12 months", "none", ""),
                 (NO_DATA, "cost to reach the next gates", "none", "")]
    s = t["slip"]
    if s:
        who = s.get("asset") or s.get("nct")
        where = "gate slip" if s.get("gate_asset") else "study slip"
        figs.append((_plural(s['days'], 'day'), f"{who} {where} · seen {dm(s.get('seen'))}", "down",
                     f"{s.get('nct') or ''} primary completion {dmy(s.get('old'))} to "
                     f"{dmy(s.get('new'))}, the largest slip in the 30-day change feed"))
    else:
        figs.append(("none", "slips seen in 30 days", "none", ""))
    cells = "".join(f'<div class="ki-f"{f" title={chr(34)}{esc(tip)}{chr(34)}" if tip else ""}>'
                    f'<span class="v {tone}">{esc(v)}</span>'
                    f'<span class="k">{esc(k)}</span></div>' for v, k, tone, tip in figs)
    return (f'<div class="cx cx-hd"><div class="cx-hd-l"><div class="cx-kick">{esc(kick)}</div>'
            f'<p class="cx-lead">{sentence}</p></div>'
            f'<div class="ki-figs cx-figs">{cells}</div></div>')


# ------------------------------------------------------------------------- placement
class Occ:
    """What is already drawn in a lane, so a mark or a label never lands on another."""

    def __init__(self):
        self.c, self.r = [], []

    def hit_circle(self, x, y, r, pad=1.0):
        for cx, cy, cr in self.c:
            if (cx - x) ** 2 + (cy - y) ** 2 < (cr + r + pad) ** 2:
                return True
        for a0, b0, a1, b1 in self.r:
            nx, ny = min(max(x, a0), a1), min(max(y, b0), b1)
            if (nx - x) ** 2 + (ny - y) ** 2 < (r + pad) ** 2:
                return True
        return False

    def overlap(self, x, y, r) -> float:
        """How deep a circle at (x, y) sits in what is drawn: the sum of the overlaps."""
        out = 0.0
        for cx, cy, cr in self.c:
            d = math.hypot(cx - x, cy - y)
            out += max(0.0, cr + r - d)
        for a0, b0, a1, b1 in self.r:
            nx, ny = min(max(x, a0), a1), min(max(y, b0), b1)
            out += max(0.0, r - math.hypot(nx - x, ny - y))
        return out

    def hit_rect(self, x0, y0, x1, y1, pad=1.5):
        for cx, cy, cr in self.c:
            nx, ny = min(max(cx, x0), x1), min(max(cy, y0), y1)
            if (nx - cx) ** 2 + (ny - cy) ** 2 < (cr + pad) ** 2:
                return True
        for a0, b0, a1, b1 in self.r:
            if x0 < a1 + pad and x1 > a0 - pad and y0 < b1 + pad and y1 > b0 - pad:
                return True
        return False


def swarm(items, ymid, ylo, yhi, occ):
    """Each mark at its date, nudged up or down until it clears the marks before it; where
    nothing clears, at the height that overlaps least."""
    for it in sorted(items, key=lambda i: (-i["r"], i["x"])):
        best, y = None, None
        for k in range(0, 80):
            off = 0 if k == 0 else ((k + 1) // 2) * 2.0 * (1 if k % 2 else -1)
            yy = ymid + off
            if yy - it["r"] < ylo or yy + it["r"] > yhi:
                continue
            if not occ.hit_circle(it["x"], yy, it["r"]):
                y = yy
                break
            hits = occ.overlap(it["x"], yy, it["r"])
            if best is None or hits < best[0]:
                best = (hits, yy)
        if y is None:
            y = best[1] if best else ymid
        it["y"] = y
        occ.c.append((it["x"], y, it["r"]))


def place_label(lines, x, y, r, occ, box, prefer=("r", "l", "t", "b", "tr", "br"),
                soft=None):
    """``lines`` [(text, cls, size, mono, bold)] beside a mark, at the first side that
    clears everything drawn and stays in ``box`` (x0, y0, x1, y1). '' where none does.
    ``soft`` holds marks still to be placed: a side that clears them too is taken first."""
    if soft is not None:
        both = Occ()
        both.c, both.r = occ.c + soft.c, occ.r + soft.r
        got = place_label(lines, x, y, r, both, box, prefer)
        if got:
            occ.r.append(both.r[-1])
            return got
    lh = 10.5
    w = max(_tw(t, s, m, b) for t, _c, s, m, b in lines)
    h = lh * len(lines)
    bx0, by0, bx1, by1 = box
    for side in prefer:
        if side == "r":
            x0, y0, anchor = x + r + 4, y - h / 2, "start"
        elif side == "l":
            x0, y0, anchor = x - r - 4 - w, y - h / 2, "end"
        elif side == "t":
            x0, y0, anchor = x - w / 2, y - r - 2 - h, "middle"
        elif side == "b":
            x0, y0, anchor = x - w / 2, y + r + 2, "middle"
        elif side == "tr":
            x0, y0, anchor = x + r * 0.6, y - r - 1 - h, "start"
        else:
            x0, y0, anchor = x + r * 0.6, y + r + 1, "start"
        x1, y1 = x0 + w, y0 + h
        if x0 < bx0 or x1 > bx1 or y0 < by0 or y1 > by1:
            continue
        if occ.hit_rect(x0, y0, x1, y1):
            continue
        occ.r.append((x0, y0, x1, y1))
        tx = {"start": x0, "end": x1, "middle": (x0 + x1) / 2}[anchor]
        return "".join(f'<text class="{c}" x="{tx:.1f}" y="{y0 + lh * i + 8.2:.1f}" '
                       f'text-anchor="{anchor}">{esc(t)}</text>'
                       for i, (t, c, _s, _m, _b) in enumerate(lines))
    return ""


def _circle_in_rect(x, y, r, rect, pad=0.5) -> bool:
    """True where a circle at (x, y) reaches into ``rect`` (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = rect
    nx, ny = min(max(x, x0), x1), min(max(y, y0), y1)
    return (nx - x) ** 2 + (ny - y) ** 2 < (r + pad) ** 2


def diamond(x, y, r) -> str:
    return f"M{x:.1f},{y - r:.1f}L{x + r:.1f},{y:.1f}L{x:.1f},{y + r:.1f}L{x - r:.1f},{y:.1f}Z"


# -------------------------------------------------------------------------- timeline
OTHER_LANE = "Other areas"
MAX_LANES = 5
# A readout due with no result: a dashed ring wide enough for its "?" at 9 px.
DUE_R = 5.6


def _event_tip(e) -> str:
    t = e.get("trial") or {}
    parts = [f"{e.get('asset') or 'Unmatched'} · {e.get('phase') or 'study'} readout · "
             f"est. {dmy(e.get('date'))}"]
    if t.get("title") or e.get("title"):
        parts.append(re.sub(r"\s+", " ", str(t.get("title") or e.get("title"))))
    meta = []
    if t.get("enrollment"):
        meta.append(f"{t['enrollment']:,} patients")
    if t.get("overall_status"):
        meta.append(str(t["overall_status"]).lower())
    if e.get("nct"):
        meta.append(e["nct"])
    if meta:
        parts.append(" · ".join(meta))
    if e.get("priced"):
        parts.append(f"{usd(e.get('per_share'))} a share at stake")
    elif e.get("why"):
        parts.append("Not priced: " + str(e["why"]))
    s = e.get("slip")
    if s:
        parts.append(f"Slipped {s['days']} days, {dmy(s['old'])} to {dmy(s['new'])}, "
                     f"seen {dmy(s.get('seen'))}")
    return "\n".join(parts)


def _gate_tip(r) -> str:
    when, _ = date_text(r)
    parts = [f"{r.get('name')} · {r['glabel']} · {when}"
             + (" (readout due, no result on file)" if r.get("due") else "")]
    parts.append(f"Today {usd(r['now'])} a share, {usd(r['success'])} if it passes, "
                 f"{usd(r['failure'])} if the programme fails. Odds {pct(r.get('p_gate'))}.")
    held = r.get("held") or {}
    if held.get("note"):
        parts.append(str(held["note"]))
    if not r["priced"]:
        parts.append("No dated catalyst on the calendar.")
    return "\n".join(parts)


def lanes(p) -> list:
    """The therapy-area lanes, by value at stake in the next 24 months, then by events;
    the areas past the fifth, and anything with no area, share one last lane."""
    today = _today(p)
    end24 = today + dt.timedelta(days=731)
    stake, count = {}, {}
    for r in gate_rows(p):
        key = r["fl"] or r["d"]
        if r.get("due") or (key and key <= end24):
            stake[r.get("area")] = stake.get(r.get("area"), 0) + (r["swing"] or 0)
    for e in p.get("events") or []:
        d = _d(e.get("date"))
        if d and today <= d <= end24:
            count[e.get("area")] = count.get(e.get("area"), 0) + 1
    areas = [a for a in set(stake) | set(count) if a]
    areas.sort(key=lambda a: (-stake.get(a, 0), -count.get(a, 0), a))
    own = areas[:MAX_LANES - 1] if len(areas) > MAX_LANES else areas
    rest = [a for a in areas if a not in own]
    out = [(a, {a}) for a in own]
    if rest or None in stake or None in count:
        out.append((OTHER_LANE, set(rest) | {None}))
    return out


def _lane_name(name, lab) -> list:
    """A lane's name as the lines it is drawn on: one where it fits the label column, else
    split after "and" (or cut) onto two."""
    if _tw(name, 11, bold=True) <= lab - 4:
        return [name]
    if " and " in name:
        a, b = name.split(" and ", 1)
        return [a + " and", b]
    return [name[:16]]


def _segments(p, width):
    """The time axis: the record since the first signed result (compressed), the next 24
    months at full scale and the years after them (compressed), with x() for any date."""
    today = _today(p)
    end24 = today + dt.timedelta(days=731)
    past = [_d(r.get("event_date")) for r in p.get("readouts") or []]
    past += [r["d"] for r in gate_rows(p) if r.get("due") and r["d"]]
    past = [x for x in past if x and x < today]
    lo = max(min(past), today - dt.timedelta(days=365)) if past else None
    if lo:
        lo = min(dt.date(lo.year, lo.month, 1), today - dt.timedelta(days=60))
    far = [r["d"] for r in gate_rows(p) if r["d"] and r["d"] > end24]
    far += [dt.date(int(y), 7, 1) for y in (p.get("loe_by_year") or {}) if str(y).isdigit()
            and dt.date(int(y), 7, 1) > end24]
    hend_year = max([x.year for x in far] + [today.year + 5])
    hend_year = min(hend_year, today.year + 10)
    hend = dt.date(hend_year, 12, 31)
    lab = 112
    x0, xr = lab + 6, width - 6
    gap = 12
    wp = 58 if lo else 0
    wh = 150
    wm = xr - x0 - (wp + gap if lo else 0) - gap - wh
    xm0 = x0 + (wp + gap if lo else 0)
    xh0 = xm0 + wm + gap

    def x(day):
        if day < today:
            if not lo:
                return xm0
            day = max(day, lo)
            return x0 + wp * (day - lo).days / max((today - lo).days, 1)
        if day <= end24:
            return xm0 + wm * (day - today).days / (end24 - today).days
        day = min(day, hend)
        return xh0 + wh * (day - end24).days / max((hend - end24).days, 1)

    return {"x": x, "lo": lo, "today": today, "end24": end24, "hend": hend, "lab": lab,
            "x0": x0, "xr": xr, "wp": wp, "wm": wm, "wh": wh, "xm0": xm0, "xh0": xh0,
            "gap": gap}


def _labelled(it, smax) -> bool:
    """A gate disc or an FDA floor big enough to carry its name on the timeline."""
    g = it.get("g")
    if g is None:
        return False
    return it["kind"] == "fda" or (it["kind"] == "gate"
                                   and (g["swing"] or 0) >= max(0.3, 0.04 * smax))


def _label_options(it):
    """The label of a gate mark, longest first: name and figure on two lines, then one."""
    g = it["g"]
    if it["kind"] == "fda":
        return ([(f"{g['name']} FDA", "lbl", 10, False, True),
                 (f"{usd(g['swing'])} · from {mon(g['fl'])}", "lvm", 9, True, False)],
                [(f"{g['name']} FDA {usd(g['swing'])}", "lbl", 10, False, True)])
    return ([(g["name"], "lbl", 10, False, True),
             (f"{usd(g['swing'])} · {mon(g['d'])}", "lvm", 9, True, False)],
            [(f"{g['name']} {usd(g['swing'])}", "lbl", 10, False, True)])


def timeline_svg(p, selected=None, width=956, height=254) -> str:
    """The next 24 months by therapy area, with the record before them and the years
    after them compressed: every gate as a disc sized by its value at stake a share (a
    diamond at the earliest approval where an FDA decision has no date, a dashed ring
    where a readout is due with no result), every other dated readout as a ring, signed
    Phase 3 results in the record, slips of 90 days or more as dashed arrows, and the
    exclusivity losses hanging below. Each gate mark is a click target (data-gate).

    The large marks are placed and named first, so a name is never crowded out by the
    small rings, which then find room around them."""
    rows = gate_rows(p)
    seg = _segments(p, width)
    X, today, end24 = seg["x"], seg["today"], seg["end24"]
    lane_defs = lanes(p)
    lane_of = {}
    for name, areas in lane_defs:
        for a in areas:
            lane_of[a] = name
    gates_by_id = {r["asset_id"]: r for r in rows}
    drawn = [r for r in rows if r["d"] or r["fl"]]
    smax = max([r["swing"] or 0 for r in drawn] + [0.01])
    rmax = 15.0

    def radius(sw):
        return max(3.6, rmax * math.sqrt(max(sw or 0, 0) / smax))

    # marks per lane
    marks = {name: [] for name, _ in lane_defs}
    priced_ids = {((r.get("stake") or {}).get("id")) for r in rows if r.get("stake")}
    for r in drawn:
        ln = lane_of.get(r.get("area"), OTHER_LANE)
        if ln not in marks:
            continue
        if r["fl"]:
            marks[ln].append({"kind": "fda", "g": r, "x": X(r["fl"]),
                              "r": max(4.8, radius(r["swing"]))})
        elif r.get("due"):
            marks[ln].append({"kind": "due", "g": r, "x": X(r["d"]), "r": DUE_R})
        else:
            marks[ln].append({"kind": "gate", "g": r, "x": X(r["d"]), "r": radius(r["swing"])})
    for e in p.get("events") or []:
        d = _d(e.get("date"))
        if not d or d < today or d > end24 or e.get("id") in priced_ids:
            continue
        ln = lane_of.get(e.get("area"), OTHER_LANE)
        if ln in marks:
            marks[ln].append({"kind": "ev", "e": e, "x": X(d), "r": 3.2})
    if seg["lo"]:
        for ro in p.get("readouts") or []:
            d = _d(ro.get("event_date"))
            if not d or d >= today or d < seg["lo"]:
                continue
            ln = lane_of.get(ro.get("area"), OTHER_LANE)
            if ln in marks:
                marks[ln].append({"kind": "rec", "ro": ro, "x": X(d), "r": 4.4})

    # lane heights: room for the largest mark and, where a large one is named, a line of
    # text above or below it; the spare shared by weight
    head, loe_h, foot = 22, 48, 3
    lanes_h = height - head - loe_h - foot
    need, weight = {}, {}
    for name, _ in lane_defs:
        big = max([m["r"] for m in marks[name]] + [3.2])
        named = any(_labelled(m, smax) and m["r"] >= 9 for m in marks[name])
        need[name] = max(26.0, 2 * big + 8) + (14 if named else 0)
        if len(_lane_name(name, seg["lab"])) > 1:
            # two lines of name and the value line under them
            need[name] = max(need[name], 38.0)
        weight[name] = 1.0 + 1.4 * big / rmax + 0.18 * math.sqrt(len(marks[name]))
    spare = lanes_h - sum(need.values())
    if spare < 0:
        height -= spare
        spare = 0
    total_w = sum(weight.values()) or 1
    box, y = {}, head
    for name, _ in lane_defs:
        h = need[name] + spare * weight[name] / total_w
        box[name] = (y, y + h)
        y += h
    loe_y = y

    # labels are drawn after every mark, so a ring never sits on a name
    under, ticks, body, labels, over = [], [], [], [], []
    xm0, wm, xh0 = seg["xm0"], seg["wm"], seg["xh0"]
    # the next 90 days, the grid and the segment heads
    under.append(f'<rect class="b90" x="{xm0:.1f}" y="{head - 4}" '
                 f'width="{X(today + dt.timedelta(days=90)) - xm0:.1f}" '
                 f'height="{loe_y - head + 4:.1f}"><title>The next 90 days</title></rect>')
    q = dt.date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
    while q <= end24:
        if q > today:
            yr = q.month == 1
            under.append(f'<line class="grid{" y" if yr else ""}" x1="{X(q):.1f}" '
                         f'x2="{X(q):.1f}" y1="{head}" y2="{height - foot:.1f}"/>')
            if X(q) - xm0 > 34 and xm0 + wm - X(q) > 16:
                ticks.append(f'<text class="tk{" yr" if yr else ""}" x="{X(q):.1f}" y="19" '
                             f'text-anchor="middle">'
                             f'{MON[q.month - 1] + (" " + str(q.year) if yr else "")}</text>')
        q = dt.date(q.year + (q.month + 3 > 12), (q.month + 2) % 12 + 1, 1)
    for yr in range(end24.year + 1, seg["hend"].year + 1):
        q = dt.date(yr, 1, 1)
        under.append(f'<line class="grid" x1="{X(q):.1f}" x2="{X(q):.1f}" y1="{head}" '
                     f'y2="{height - foot:.1f}"/>')
        if (yr - end24.year) % 2 == 1:
            ticks.append(f'<text class="tk" x="{X(dt.date(yr, 7, 1)):.1f}" y="19" '
                         f'text-anchor="middle">{yr}</text>')
    if seg["lo"]:
        ticks.append(f'<text class="cap" x="{seg["x0"]}" y="9">Record</text>')
    ticks.append(f'<text class="cap now" x="{xm0 + 3:.1f}" y="9">Today {dm(today)}</text>')
    ticks.append(f'<text class="cap" x="{xm0 + wm:.1f}" y="9" text-anchor="end">'
                 f'24 months, to {dmy(end24)}</text>')
    ticks.append(f'<text class="cap" x="{xh0:.1f}" y="9">Later</text>')
    breaks = [xm0 + wm + seg["gap"] / 2] + ([seg["x0"] + seg["wp"] + seg["gap"] / 2]
                                            if seg["lo"] else [])
    for bx in breaks:
        under.append(f'<path class="brk" d="M{bx - 3:.1f},{head + 1}l3,-5l3,5"/>')
        under.append(f'<path class="brk" d="M{bx - 3:.1f},{height - foot - 1:.1f}l3,5l3,-5"/>')

    # lane labels: the area, its value at stake in 24 months and its readouts
    for name, _areas in lane_defs:
        y0, y1 = box[name]
        under.append(f'<line class="lane" x1="0" x2="{seg["xr"]:.1f}" y1="{y1:.1f}" '
                     f'y2="{y1:.1f}"/>')
        n = sum(1 for e in p.get("events") or []
                if lane_of.get(e.get("area"), OTHER_LANE) == name
                and _d(e.get("date")) and today <= _d(e["date"]) <= end24)
        st_ = sum((r["swing"] or 0) for r in rows
                  if lane_of.get(r.get("area"), OTHER_LANE) == name
                  and (r.get("due") or ((r["fl"] or r["d"]) and (r["fl"] or r["d"]) <= end24)))
        yt = y0 + 1
        for line in _lane_name(name, seg["lab"]):
            yt += 11
            body.append(f'<text class="ln" x="0" y="{yt:.1f}">{esc(line)}</text>')
        yt += 12
        if yt <= y1 - 2:
            body.append(f'<text class="lv" x="0" y="{yt:.1f}">{usd(st_)}<tspan class="lu"> · '
                        f'{_plural(n, "readout")}</tspan></text>')

    sel_ring = None
    for name, _areas in lane_defs:
        y0, y1 = box[name]
        occ = Occ()
        items = marks[name]
        named = [it for it in items if _labelled(it, smax)]
        # a lane whose large disc is named sits its marks a little low, the name above
        big_named = any(it["r"] >= 9 for it in named)
        ymid = (y0 + y1) / 2 + (6 if big_named else 1)
        lbox = (seg["x0"], y0 + 1, seg["xr"], y1 - 1)
        swarm(named, ymid, y0 + 3, y1 - 3, occ)
        # slips of 90 days or more on a named gate: the old date as a ghost, an arrow on
        slips = []
        for it in items:
            s = (it["g"].get("move") if it["kind"] in ("gate", "due") else
                 it["e"].get("slip") if it["kind"] == "ev" else None)
            if s and (s.get("days") or 0) >= 90 and _d(s.get("old")):
                slips.append((it, s))
        for it, s in slips:
            if "y" not in it:
                continue
            gx = X(_d(s["old"]))
            occ.c.append((gx, it["y"], 4.5))
            occ.r.append((min(gx, it["x"]) + 5, it["y"] - 1.5,
                          max(gx, it["x"]) - it["r"] - 1, it["y"] + 1.5))
        # the names, largest first, before anything small can take their room; a side
        # clear of the small marks still to come is taken where there is one
        soft = Occ()
        soft.c = [(it["x"], ymid, it["r"] + 1) for it in items
                  if "y" not in it and it["kind"] in ("gate", "due", "fda")]
        names = []
        for it in sorted(named, key=lambda i: -i["r"]):
            two, one = _label_options(it)
            prefer = (("t", "b", "tr", "br", "l", "r") if it["r"] >= 9
                      else ("r", "l", "tr", "br", "t", "b"))
            lab = ""
            for hard in (False, True):
                lab = (place_label(two, it["x"], it["y"], it["r"], occ, lbox, ("r", "l"),
                                   soft=None if hard else soft)
                       or place_label(one, it["x"], it["y"], it["r"], occ, lbox, prefer,
                                      soft=None if hard else soft))
                if lab:
                    break
            names.append([it, len(labels), occ.r[-1] if lab else None])
            labels.append(lab)
        # the slip on a named gate, said over its arrow
        for it, s in slips:
            if "y" not in it or it["kind"] not in ("gate", "due"):
                continue
            gx, ex = X(_d(s["old"])), it["x"] - it["r"] - 2
            if ex - gx >= 8:
                labels.append(place_label([(f"+{s['days']} days", "sl", 9, True, True)],
                                          (gx + ex) / 2, it["y"], 3, occ, lbox,
                                          prefer=("b", "t")))
        # the earliest approval after the two largest gates: a dotted arc to a diamond
        arcs = 0
        for it in sorted(named, key=lambda i: -i["r"]):
            if it["kind"] != "gate" or it["r"] < 9 or arcs >= 2:
                continue
            launch = it["g"].get("launch") or {}
            lg = launch.get("gate") if isinstance(launch.get("gate"), dict) else {}
            ad = _d(lg.get("decision_date") or launch.get("decision_date"))
            if not ad or ad <= it["g"]["d"]:
                continue
            ax, ay = X(ad), it["y"]
            tries = 0
            while occ.hit_circle(ax, ay, 4.0, pad=0.5) and tries < 12:
                ay += 7 if (tries % 2 == 0) else -14
                ay = min(max(ay, y0 + 5), y1 - 5)
                tries += 1
            x1_, y1_ = it["x"], it["y"] - it["r"]
            cy_ = max(min(y1_, ay) - 12, y0 + 2)
            status = str(launch.get("status") or "").replace("_", " ")
            body.append(f'<g><title>{esc(it["g"]["name"])}: earliest approval {dmy(ad)}, model '
                        f'launch {launch.get("seed_year") or NO_DATA}'
                        f'{(" (" + status + ")") if status else ""}. '
                        f'{esc(launch.get("message") or "")}</title>'
                        f'<path class="arc" d="M{x1_:.1f},{y1_:.1f}Q{(x1_ + ax) / 2:.1f},{cy_:.1f} '
                        f'{ax:.1f},{ay - 4.2:.1f}"/><path class="appr" d="{diamond(ax, ay, 4.0)}"/>'
                        f'</g>')
            occ.c.append((ax, ay, 4.0))
            arcs += 1
        # everything else finds room around the named marks
        rest = [it for it in items if "y" not in it]
        swarm(rest, ymid, y0 + 3, y1 - 3, occ)
        # a gate the lane had no clear room for must not sit hidden under a name: the
        # name moves to a side clear of every mark now drawn. Where none is clear, a name
        # in the 24 months stays and the small gate is drawn over it; a name after them
        # is left to its tooltip and the range chart's later view.
        for gm in rest:
            if gm["kind"] not in ("gate", "due", "fda"):
                continue
            for nm in names:
                rect, it = nm[2], nm[0]
                if rect is None or not _circle_in_rect(gm["x"], gm["y"], gm["r"], rect):
                    continue
                occ.r.remove(rect)
                two, one = _label_options(it)
                lab = (place_label(two, it["x"], it["y"], it["r"], occ, lbox,
                                   ("r", "l", "tr", "br"))
                       or place_label(one, it["x"], it["y"], it["r"], occ, lbox,
                                      ("r", "l", "tr", "br", "t", "b")))
                if lab:
                    nm[2], labels[nm[1]] = occ.r[-1], lab
                elif (it["g"].get("due") or (it["g"]["fl"] or it["g"]["d"]) <= end24):
                    occ.r.append(rect)
                    gm["lift"] = True
                else:
                    nm[2], labels[nm[1]] = None, ""
        swarm_slips = [(it, s) for it, s in slips if it in rest]
        for it, s in slips:
            gx, yy = X(_d(s["old"])), it["y"]
            ex = it["x"] - it["r"] - 2
            if ex - gx < 8:
                continue
            who = (it["g"]["name"] if it["kind"] in ("gate", "due")
                   else (it["e"].get("asset") or ""))
            under.append(f'<g class="slipg"><title>{esc(who)}: primary completion '
                         f'{dmy(s["old"])} to {dmy(s["new"])}, {s["days"]} days later, seen '
                         f'{dmy(s.get("seen"))}</title>'
                         f'<circle class="ghost" cx="{gx:.1f}" cy="{yy:.1f}" r="4.5"/>'
                         f'<line class="slip" x1="{gx + 4.5:.1f}" y1="{yy:.1f}" x2="{ex:.1f}" '
                         f'y2="{yy:.1f}"/><path class="slipa" d="M{ex - 4.5:.1f},{yy - 3:.1f}'
                         f'L{ex:.1f},{yy:.1f}L{ex - 4.5:.1f},{yy + 3:.1f}"/></g>')
            if it["kind"] in ("gate", "due") and (it, s) in swarm_slips:
                labels.append(place_label([(f"+{s['days']} days", "sl", 9, True, True)],
                                          (gx + ex) / 2, yy, 3, occ, lbox, prefer=("b", "t")))
        # the marks, largest first so a ring is never hidden under a disc
        for it in sorted(items, key=lambda i: -i["r"]):
            x, yy, r = it["x"], it["y"], it["r"]
            # a small gate with no clear room is drawn over the name it would sit under
            dest = over if it.get("lift") else body
            if it["kind"] == "gate":
                g = it["g"]
                dest.append(f'<a data-gate="{g["asset_id"]}"><title>{esc(_gate_tip(g))}</title>'
                            f'<circle class="pf {g["ph"]}" cx="{x:.1f}" cy="{yy:.1f}" '
                            f'r="{r:.1f}"/></a>')
            elif it["kind"] == "fda":
                g = it["g"]
                dest.append(f'<a data-gate="{g["asset_id"]}"><title>{esc(_gate_tip(g))}</title>'
                            f'<path class="rg" d="{diamond(x, yy, r + 1.5)}"/></a>')
            elif it["kind"] == "due":
                g = it["g"]
                dest.append(f'<a data-gate="{g["asset_id"]}"><title>{esc(_gate_tip(g))}</title>'
                            f'<circle class="due" cx="{x:.1f}" cy="{yy:.1f}" r="{r:.1f}"/>'
                            f'<text class="dueq" x="{x:.1f}" y="{yy + 3.1:.1f}" '
                            f'text-anchor="middle">?</text></a>')
            elif it["kind"] == "ev":
                e = it["e"]
                ring = (f'<circle class="ring {phase_class(e.get("phase"))}" cx="{x:.1f}" '
                        f'cy="{yy:.1f}" r="{r:.1f}"/>')
                if e.get("asset_id") in gates_by_id:
                    body.append(f'<a data-gate="{e["asset_id"]}"><title>{esc(_event_tip(e))}'
                                f'</title>{ring}</a>')
                else:
                    body.append(f'<g><title>{esc(_event_tip(e))}</title>{ring}</g>')
            elif it["kind"] == "rec":
                ro = it["ro"]
                good = ro.get("outcome") == "positive"
                glyph = (f"M{x - 2.1:.1f},{yy:.1f}l1.5,1.7l2.9,-3.4" if good else
                         f"M{x - 1.9:.1f},{yy - 1.9:.1f}l3.8,3.8m0,-3.8l-3.8,3.8")
                tip = (f"{ro.get('asset') or ro.get('drug')} · Phase {ro.get('phase')} "
                       f"{ro.get('outcome')} · {dmy(ro.get('event_date'))}\n"
                       f"{str(ro.get('quote') or '')[:220]}")
                body.append(f'<g><title>{esc(tip)}</title><circle class="{"ok" if good else "no"}" '
                            f'cx="{x:.1f}" cy="{yy:.1f}" r="{r:.1f}"/><path class="glyph" '
                            f'd="{glyph}"/></g>')
            g = it.get("g")
            if g is not None and g["asset_id"] == selected:
                sel_ring = (x, yy, r + (1.5 if it["kind"] == "fda" else 0))
                if not _labelled(it, smax):
                    labels.append(place_label([(g["name"], "lbl", 10, False, True)], x, yy, r,
                                              occ, lbox, prefer=("r", "l", "t", "b", "tr", "br")))
    if sel_ring:
        x, yy, r = sel_ring
        over.append(f'<circle class="sel" cx="{x:.1f}" cy="{yy:.1f}" r="{r + 3.5:.1f}"/>')

    body.append(_loe_lane(p, seg, loe_y, height - foot))
    return (f'<svg class="cx-tl" viewBox="0 0 {width} {height:.0f}" width="{width}" '
            f'height="{height:.0f}" role="img" aria-label="{esc(_ticker(p))} catalysts by '
            f'therapy area: the record, the next 24 months and the years after">'
            + "".join(under) + "".join(ticks)
            + f'<line class="today" x1="{xm0:.1f}" x2="{xm0:.1f}" y1="{head - 6}" '
              f'y2="{height - foot:.1f}"/>'
            + "".join(body) + "".join(labels) + "".join(over) + "</svg>")


def wall(p, after_year):
    """The three years after ``after_year`` whose lines carry the most model value: (first
    year, last year, value a share), or None where no year is on file."""
    by = {int(y): v.get("per_share") or 0 for y, v in (p.get("loe_by_year") or {}).items()
          if str(y).isdigit() and int(y) > after_year}
    if not by:
        return None
    best = None
    for y in sorted(by):
        s = sum(by.get(y + k, 0) for k in range(3))
        if best is None or s > best[2] + 1e-9:
            best = (y, y + 2, s)
    return best if best and best[2] > 0 else None


def _loe_lane(p, seg, top, bottom) -> str:
    """Exclusivity losses on the same axis, hanging from a baseline: depth is the model's
    value a share on the line, colour the modality. Dated losses inside the window from
    the exclusivities on file; after 24 months, one stacked bar a model LOE year."""
    X, today, end24 = seg["x"], seg["today"], seg["end24"]
    base = top + 13
    depth = bottom - base - 2
    cliffs = [c for c in p.get("cliffs") or [] if _d(c.get("loe"))]
    lo = seg["lo"] or today
    inside = [c for c in cliffs if lo <= _d(c["loe"]) <= end24]
    later = {int(y): v for y, v in (p.get("loe_by_year") or {}).items()
             if str(y).isdigit() and dt.date(int(y), 7, 1) > end24
             and int(y) <= seg["hend"].year}
    vmax = max([c.get("model_per_share") or 0 for c in inside]
               + [v.get("per_share") or 0 for v in later.values()] + [0.01])
    k = depth / vmax
    o = [f'<line class="lane" x1="0" x2="{seg["xr"]:.1f}" y1="{bottom:.1f}" y2="{bottom:.1f}"/>',
         f'<line class="base" x1="{seg["x0"]}" x2="{seg["xr"]:.1f}" y1="{base:.1f}" y2="{base:.1f}"/>',
         f'<g><title>Each bar hangs as deep as the model\'s value a share on the line: what '
         f'the line carries, not the value lost at LOE. Dated losses from the exclusivities '
         f'on file; after 24 months, one bar a model LOE year.</title>'
         f'<text class="ln" x="0" y="{top + 12:.1f}">Exclusivity ends</text>'
         f'<text class="lu" x="0" y="{top + 24:.1f}">depth: model $ a share</text>'
         f'<text class="lu" x="0" y="{top + 35:.1f}">on the line, not lost</text></g>']
    occ = Occ()
    labelled = []
    for c in inside:
        x = X(_d(c["loe"]))
        mod = ("sm" if c.get("modality") == "small molecule" else
               "bio" if c.get("modality") == "biologic" else "unk")
        when = "ended" if c.get("passed") else "ends"
        share = (f", {pct(c['share_of_revenue'], 1)} of {c.get('fy') or 'last year'}'s revenue"
                 if c.get("share_of_revenue") is not None else "")
        if c.get("model_per_share"):
            h = c["model_per_share"] * k
            tip = (f"{c['asset']} exclusivity {when} {dmy(c['loe'])} ({c.get('loe_basis') or 'basis not on file'})"
                   f"{share}. The model carries the line at {usd(c['model_per_share'])} a share.")
            o.append(f'<g><title>{esc(tip)}</title><rect class="{mod}{" past" if c.get("passed") else ""}" '
                     f'x="{x - 2.5:.1f}" y="{base:.1f}" width="5" height="{h:.1f}"/></g>')
            occ.r.append((x - 2.5, base, x + 2.5, base + h))
            labelled.append((c, x, h))
        else:
            o.append(f'<g><title>{esc(c["asset"])} exclusivity {when} {dmy(c["loe"])} '
                     f'({esc(c.get("loe_basis") or "basis not on file")}); no model line carries it.'
                     f'</title><rect class="none" x="{x - 1.5:.1f}" y="{base:.1f}" width="3" height="4"/></g>')
    for c, x, h in sorted(labelled, key=lambda t: -t[2])[:3]:
        lab = place_label([(f"{c['asset']} {usd(c['model_per_share'])}", "lbl", 9.5, False, True),
                           (("ended " if c.get("passed") else "") + mon(c["loe"]), "lm", 9, False, False)],
                          x, base + 12, 3, occ, (seg["x0"], base + 1, seg["xr"], bottom - 1),
                          prefer=("r", "l"))
        o.append(lab)
    for yr, v in sorted(later.items()):
        x = X(dt.date(yr, 7, 1))
        yy = base
        parts = []
        for prod in v.get("products") or []:
            name, val = prod[0], _num(prod[1]) or 0
            modality = prod[2] if len(prod) > 2 else None
            cls = "sm" if modality == "small molecule" else ("bio" if modality == "biologic" else "unk")
            h = val * k
            parts.append(f'<rect class="{cls}" x="{x - 4.5:.1f}" y="{yy:.1f}" width="9" '
                         f'height="{max(h - 0.6, 0.6):.1f}"/>')
            yy += h
        tip = (f"Exclusivity ends {yr} in the model: "
               + ", ".join(f"{q[0]} {usd(q[1])}" for q in v.get("products") or [])
               + f". {usd(v.get('per_share'))} a share in all.")
        o.append(f'<g><title>{esc(tip)}</title>{"".join(parts)}</g>')
    w = wall(p, end24.year)
    if w:
        wx0 = X(dt.date(w[0], 1, 1)) + 1
        wx1 = X(dt.date(w[1], 12, 31)) - 1
        o.append(f'<path class="wall" d="M{wx0:.1f},{base - 1:.1f}V{base - 4:.1f}H{wx1:.1f}V{base - 1:.1f}"/>'
                 f'<text class="wallt" x="{(wx0 + wx1) / 2:.1f}" y="{base - 6:.1f}" text-anchor="middle">'
                 f'{usd(w[2])} in {w[0]} to {w[1]}</text>')
    return "".join(o)


def timeline_legend() -> str:
    def sv(inner, w=14, h=12):
        return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">{inner}</svg>'
    items = [
        (sv('<circle class="pf p3" cx="7" cy="6" r="5"/>'), "gate, area = $ at stake"),
        (sv('<circle class="ring p3" cx="7" cy="6" r="3"/>'), "readout, not priced"),
        (sv(f'<path class="rg" d="{diamond(7, 6, 4.5)}"/>'), "FDA decision, earliest date"),
        (sv('<circle class="due" cx="7" cy="6" r="5"/>'), "due, no result"),
        (sv('<circle class="ok" cx="7" cy="6" r="4.5"/>'), "Phase 3 result"),
        (sv('<circle class="ghost" cx="3" cy="6" r="2.5"/><line class="slip" x1="6" y1="6" '
            'x2="14" y2="6"/>', 16), "slip of 90 days or more"),
        (sv('<rect class="sm" x="2" y="1" width="4" height="10"/><rect class="bio" x="8" '
            'y="1" width="4" height="10"/>'), "small molecule, biologic"),
    ]
    return ('<div class="cx-leg">' + "".join(f'<span>{s}{esc(t)}</span>' for s, t in items)
            + '</div>')


# ----------------------------------------------------------------------- range chart
def _view_rows(rows, view):
    return [r for r in rows if r["view"] == view]


def _nice_max(v):
    for step in (1, 2, 5, 10, 20, 50, 100):
        if v <= step * 8:
            return max(step, math.ceil(v / step) * step), step
    return math.ceil(v), max(1, math.ceil(v / 8))


def range_svg(p, view="near", selected=None, width=956, vmax=None) -> str:
    """One view of the ranked range chart: every gate in the view's groups on one $ a
    share axis, its bar from what a miss leaves to what a pass adds, today as a tick,
    hatched where other Phase 3s hold the line after a miss. Each row is a click target
    (data-gate)."""
    rows = _view_rows(gate_rows(p), view)
    allrows = gate_rows(p)
    pad = 8
    name_x, date_x = pad + 14, pad + 194
    px0, px1 = pad + 286, width - 236
    pass_r, miss_r = width - 166, width - 100
    odds_x, odds_w, odds_r = width - 82, 30, width - 4
    hdr, gh, rh = 18, 19, 17
    top = vmax or max([r["success"] or 0 for r in allrows] + [r["now"] or 0 for r in allrows] + [1])
    top, step = _nice_max(top)

    def px(v):
        return px0 + (px1 - px0) * max(v, 0) / top

    groups = [gi for gi in range(4) if GROUPS[gi][1] == view and any(r["grp"] == gi for r in rows)]
    shown_n = min(len(rows), VIEW_ROWS)
    h = hdr + gh * len(groups) + rh * shown_n + (rh if len(rows) > VIEW_ROWS else 0) + 4
    o = [f'<svg class="cx-rg-svg" viewBox="0 0 {width} {h:.0f}" width="{width}" height="{h:.0f}" '
         f'role="img" aria-label="Value at stake at the next gate, {esc(dict(VIEWS)[view].lower())}, '
         f'dollars a share">',
         '<defs><pattern id="hd" width="4" height="4" patternUnits="userSpaceOnUse" '
         'patternTransform="rotate(45)"><rect width="4" height="4" class="hd-bg"/>'
         '<rect width="1.3" height="4" class="hd-ln"/></pattern></defs>']
    grid = ['<g class="grid-g">']
    o.append(f'<text x="{pad}" y="12" class="k">LINE · NEXT GATE</text>'
             f'<text x="{date_x}" y="12" class="k">DATE</text>'
             f'<text x="{pass_r}" y="12" class="k up" text-anchor="end">PASS ADDS</text>'
             f'<text x="{miss_r}" y="12" class="k dn" text-anchor="end">MISS TAKES</text>'
             f'<text x="{odds_r}" y="12" class="k" text-anchor="end">ODDS</text>')
    t = 0
    while t <= top + 1e-9:
        o.append(f'<text x="{px(t):.1f}" y="12" class="tk m" text-anchor="middle">'
                 f'{"$" if t == 0 else ""}{t:g}</text>')
        t += step
    o.append(f'<line x1="0" x2="{width}" y1="{hdr - 2}" y2="{hdr - 2}" class="hair-s"/>')
    y = hdr
    drawn = 0
    for gi in groups:
        grs = [r for r in rows if r["grp"] == gi]
        name = GROUPS[gi][0]
        s = sum(r["swing"] or 0 for r in grs)
        big = sorted(grs, key=lambda r: -(r["swing"] or 0))
        if len(big) >= 2 and (big[0]["swing"] or 0) + (big[1]["swing"] or 0) > 0.8 * s:
            lead = f'{big[0]["name"]} and {big[1]["name"]} {usd((big[0]["swing"] or 0) + (big[1]["swing"] or 0))}'
        else:
            lead = f'largest {big[0]["name"]} {usd(big[0]["swing"])}'
        sub = {0: f"to {mon(_today(p) + dt.timedelta(days=365))}",
               1: f"to {mon(_today(p) + dt.timedelta(days=731))}",
               2: f"from {mon(_today(p) + dt.timedelta(days=732))}",
               3: "gate study not dated or not matched"}[gi]
        o.append(f'<rect x="0" y="{y:.1f}" width="{width}" height="{gh}" class="gh-bg"/>'
                 f'<text x="{pad}" y="{y + 13:.1f}" class="gh">{esc(name.upper())}'
                 f'<tspan class="gh-sub" dx="8">{esc(sub)}</tspan></text>'
                 f'<text x="{odds_r}" y="{y + 13:.1f}" class="gh-sum m" text-anchor="end">'
                 f'<tspan class="gh-big">{usd(s)}</tspan> at stake · {_plural(len(grs), "gate")} · '
                 f'{esc(lead)}</text>')
        y += gh
        for r in grs:
            if drawn >= VIEW_ROWS:
                break
            drawn += 1
            c = y + rh / 2
            dtxt, due = date_text(r)
            mtxt, mval = miss_move(r)
            p_gate = r.get("p_gate")
            on = " on" if r["asset_id"] == selected else ""
            nm_cls = "gl-nm sm" if len(str(r.get("name") or "")) > 20 else "gl-nm"
            o.append(f'<a class="gl-row{on}" data-gate="{r["asset_id"]}">'
                     f'<title>{esc(_gate_tip(r))}</title>'
                     f'<rect x="0" y="{y:.1f}" width="{width}" height="{rh}" class="gl-hit"/>'
                     f'<rect x="0" y="{y:.1f}" width="2" height="{rh}" class="gl-rail"/>'
                     f'<rect x="{pad}" y="{c - 3.5:.1f}" width="7" height="7" class="ph-{r["ph"]}"/>'
                     f'<text x="{name_x}" y="{c + 4:.1f}" class="{nm_cls}">{esc(r.get("name"))}'
                     f'<tspan class="gl-tag" dx="6">{esc(r["short"])}</tspan></text>'
                     f'<text x="{date_x}" y="{c + 3.6:.1f}" class="gl-dt m">{esc(dtxt)}'
                     + (f'<tspan class="gl-due" dx="5">due</tspan>' if due else "") + '</text>')
            now, succ, fail = r["now"], r["success"], r["failure"]
            yb = c - 4
            if None not in (now, succ, fail):
                if r["held_ps"] is not None:
                    hx = px(r["held_ps"])
                    if hx - px(fail) > 0.5:
                        o.append(f'<rect x="{px(fail):.1f}" y="{yb:.1f}" width="{hx - px(fail):.1f}" '
                                 f'height="8" class="seg-hd"/>')
                    if px(now) - hx > 0.5:
                        o.append(f'<rect x="{hx:.1f}" y="{yb:.1f}" width="{px(now) - hx:.1f}" '
                                 f'height="8" class="seg-dn"/>')
                elif px(now) - px(fail) > 0.3:
                    o.append(f'<rect x="{px(fail):.1f}" y="{yb:.1f}" width="{px(now) - px(fail):.1f}" '
                             f'height="8" class="seg-dn"/>')
                if px(succ) - px(now) > 0.3:
                    o.append(f'<rect x="{px(now):.1f}" y="{yb:.1f}" width="{px(succ) - px(now):.1f}" '
                             f'height="8" class="seg-up"/>')
                o.append(f'<rect x="{px(now) - 1:.1f}" y="{c - 6.5:.1f}" width="2" height="13" class="tick"/>')
            else:
                o.append(f'<text x="{px0 + 4}" y="{c + 3.5:.1f}" class="gl-none">{NO_DATA}</text>')
            up = r["up"]
            strong = " b" if up is not None and abs(up) >= 1 else ""
            o.append(f'<text x="{pass_r}" y="{c + 4:.1f}" class="gl-up m{strong}" text-anchor="end">{sgn(up)}</text>')
            mcls = "gl-held" if mtxt == "held" else "gl-dn"
            strong = " b" if mval is not None and abs(mval) >= 1 else ""
            o.append(f'<text x="{miss_r}" y="{c + 4:.1f}" class="{mcls} m{strong}" text-anchor="end">{esc(mtxt)}</text>')
            if p_gate is not None:
                o.append(f'<rect x="{odds_x}" y="{c - 2:.1f}" width="{odds_w}" height="4" class="trk"/>'
                         f'<rect x="{odds_x}" y="{c - 2:.1f}" width="{odds_w * p_gate:.1f}" height="4" class="odf"/>')
            o.append(f'<text x="{odds_r}" y="{c + 4:.1f}" class="gl-od m" text-anchor="end">{pct(p_gate)}</text>'
                     f'<line x1="0" x2="{width}" y1="{y + rh - 0.5:.1f}" y2="{y + rh - 0.5:.1f}" class="hair"/></a>')
            y += rh
    if len(rows) > VIEW_ROWS:
        left = sorted(rows, key=lambda r: -(r["swing"] or 0))[VIEW_ROWS:]
        o.append(f'<text x="{name_x}" y="{y + 12.5:.1f}" class="gl-more">{len(left)} more, each '
                 f'{usd(max(r["swing"] or 0 for r in left))} a share or less, on the Forecast tab'
                 f'<title>{esc(", ".join(str(r.get("name")) for r in left))}</title></text>')
        y += rh
    t = 0
    while t <= top + 1e-9:
        grid.append(f'<line x1="{px(t):.1f}" x2="{px(t):.1f}" y1="{hdr}" y2="{y:.1f}" '
                    f'class="{"grid0" if t == 0 else "grid"}"/>')
        t += step
    grid.append("</g>")
    o.insert(2, "".join(grid))
    o.append("</svg>")
    return "".join(o)


def range_html(p, selected=None, width=956) -> str:
    """The range chart with its section rule, its legend and the switch between the next
    24 months and the gates after them or with no date. The view drawn first is the one
    that holds the selected gate; the frame switches between them without a rerun."""
    rows = gate_rows(p)
    if not rows:
        return (section_html("What can move the share", "next gate per pipeline line · $ a share")
                + f'<div class="cx-empty">No pipeline line carries a priced next gate on this '
                  f'book: {NO_DATA} for what a pass adds or a miss takes.</div>')
    sel = next((r for r in rows if r["asset_id"] == selected), None)
    first = sel["view"] if sel else ("near" if _view_rows(rows, "near") else "far")
    vmax = max([r["success"] or 0 for r in rows] + [r["now"] or 0 for r in rows] + [1])
    buttons, views = [], []
    for view, label in VIEWS:
        vr = _view_rows(rows, view)
        on = view == first
        swing = sum(r["swing"] or 0 for r in vr)
        buttons.append(f'<button type="button" class="cx-vb{" on" if on else ""}" data-view="{view}"'
                       f'{"" if vr else " disabled"}>{esc(label)} <b>{len(vr)}</b>'
                       f'<i>{usd(swing)}</i></button>')
        body = (range_svg(p, view, selected, width, vmax) if vr else
                f'<div class="cx-empty">No gate {"lands in the next 24 months" if view == "near" else "lands later or goes undated"}.</div>')
        views.append(f'<div class="cx-rv{"" if on else " off"}" data-view="{view}">{body}</div>')
    n_priced = sum(1 for r in rows if r["priced"])
    legend = (f'<span class="cx-leg rg" title="{len(rows)} gates, {n_priced} with a dated '
              f'catalyst on the calendar. Dates: est. is the registry estimate, ≥ the '
              f'earliest an FDA decision can fall.">'
              '<span><i class="k-up"></i>pass adds</span>'
              '<span><i class="k-dn"></i>miss takes</span>'
              '<span><i class="k-hd"></i>held while other Phase 3s run</span>'
              '<span><i class="k-tk"></i>today</span></span>')
    head = section_html("What can move the share", "",
                        extra=f'<span class="cx-vw" role="group" aria-label="Gates shown">'
                              f'{"".join(buttons)}</span>{legend}')
    # Both views share one grid cell, the one not shown hidden but laid out, so the frame
    # keeps the height of the taller and a switch never moves the page.
    return f'{head}<div class="cx-rg">' + "".join(views) + '</div>'



def frame_html(p, selected=None, width=956) -> str:
    """What the catnav frame renders: the timeline and the range chart, every gate mark
    and row a click target."""
    today = _today(p)
    end24 = today + dt.timedelta(days=731)
    n24 = sum(1 for e in p.get("events") or [] if _d(e.get("date")) and today <= _d(e["date"]) <= end24)
    n12 = sum(1 for e in p.get("events") or [] if _d(e.get("date"))
              and today <= _d(e["date"]) <= today + dt.timedelta(days=365))
    gates = gate_rows(p)
    if gates or n24:
        tl = (timeline_svg(p, selected, width) + timeline_legend())
    else:
        tl = f'<div class="cx-empty">Nothing dated for {esc(_ticker(p))} in the next 24 months.</div>'
    head = section_html("Next 24 months, by therapy area", "size = value at stake a share",
                        f"{_plural(n24, 'readout')} · {n12} in 12 months · "
                        f"{sum(1 for r in gates if r['priced'])} priced")
    return (f'<div class="cx cx-frame">{head}<div class="chart-mount stretch">{tl}</div>'
            f'<div class="cx-rg-wrap">{range_html(p, selected, width)}</div></div>')


# -------------------------------------------------------------------------- the card
def _gate(p, gid):
    return next((r for r in gate_rows(p) if r["asset_id"] == gid), None)


def leg(v) -> str:
    """A leg a share: "nil" for a leg of nothing, never "$0.00"; "no free data" for none."""
    v = _num(v)
    if v is not None and abs(v) < 0.005:
        return "nil"
    return usd(v)


def fork_svg(r, close=None) -> str:
    """The legs of the gate as a fork: today, then if it passes and if it misses, each
    branch as thick as its odds. Where other Phase 3s hold the line after a miss, the miss
    leg is the held value and the nil of a failed programme is said under it."""
    W, H = 404, 92
    p = r.get("p_gate")
    approval = r.get("gate") == "nda_to_approval"
    o = [f'<svg class="cx-svg fork" viewBox="0 0 {W} {H}" width="100%" role="img" '
         f'aria-label="Legs of the gate: today, if it passes, if it misses">']
    o.append(f'<text x="0" y="26" class="k">TODAY</text>'
             f'<text x="0" y="50" class="fv m">{usd(r["now"])}</text>'
             f'<text x="0" y="66" class="fs m">PoS {pct(r.get("pos_now"))}</text>')
    if p is not None:
        o.append(f'<path d="M84 44 C 106 44, 112 24, 136 24" class="br-up" '
                 f'style="stroke-width:{1 + 4 * p:.1f}"/>'
                 f'<path d="M84 44 C 106 44, 112 68, 136 68" class="br-dn" '
                 f'style="stroke-width:{1 + 4 * (1 - p):.1f}"/>')

    def after(value_text):
        return 144 + 9.3 * len(value_text) + 8

    up = usd(r["success"])
    o.append(f'<text x="144" y="11" class="k">{"IF APPROVED" if approval else "IF THE GATE PASSES"}'
             f' · {pct(p)}</text>'
             f'<text x="144" y="30" class="fv2 up m">{up}</text>'
             f'<text x="{after(up):.0f}" y="30" class="fs up m">{sgn(r["up"])} · PoS '
             f'{pct(r.get("pos_success"))}</text>')
    o.append(f'<text x="144" y="55" class="k">{"IF REJECTED" if approval else "IF IT MISSES"}'
             f' · {pct(None if p is None else 1 - p)}</text>')
    held = r.get("held") or {}
    if r.get("held_ps") is not None:
        n = held.get("open") or 0
        v = usd(r["held_ps"])
        o.append(f'<text x="144" y="74" class="fv2 m">{v}</text>'
                 f'<text x="{after(v):.0f}" y="74" class="fs m">held · PoS {pct(held.get("pos"))}'
                 f'</text>'
                 f'<text x="144" y="89" class="fs m">{_plural(n, "other Phase 3")} open; '
                 f'{leg(r["failure"])} only if all {n + 1} miss</text>')
    else:
        v = leg(r["failure"])
        move = None if None in (r["failure"], r["now"]) else r["failure"] - r["now"]
        basis = ("the stated leg on file" if r.get("legs_basis") == "stated"
                 else "a failed programme is nil, the model convention")
        o.append(f'<text x="144" y="74" class="fv2 dn m">{v}</text>'
                 f'<text x="{after(v):.0f}" y="74" class="fs m">{sgn(move)} · PoS '
                 f'{pct(r.get("pos_failure"))}</text>'
                 f'<text x="144" y="89" class="fs m">{basis}</text>')
    o.append("</svg>")
    return "".join(o)


def card_studies(r) -> list:
    """(nct, date, enrolment, role) for the dates strip: the gate study, the studies held
    behind it, or the asset's other open studies in the gate's phase."""
    out = []
    t = r.get("trial") or {}
    if t.get("nct_id"):
        out.append((t["nct_id"], _d(t.get("primary_completion") or t.get("primary_completion_date")),
                    t.get("enrollment"), "gate"))
    for s in r.get("held_studies") or []:
        out.append((s.get("nct_id"), _d(s.get("primary_completion_date")), s.get("enrollment"), "held"))
    for s in r.get("open_studies") or []:
        out.append((s.get("nct_id"), _d(s.get("primary_completion_date")), s.get("enrollment"), "open"))
    return [s for s in out if s[1]]


def _frac_year(x: dt.date) -> float:
    start = dt.date(x.year, 1, 1)
    return x.year + (x - start).days / ((dt.date(x.year + 1, 1, 1) - start).days)


def dates_svg(r, today) -> str:
    """Three rows on a year axis: the studies (sized by patients) with the gate study's
    slip, the earliest and the standard FDA approval, and the model's launch year."""
    W, H = 404, 110
    L, R = 48, W - 6
    st = card_studies(r)
    launch = r.get("launch") or {}
    lg = launch.get("gate") if isinstance(launch.get("gate"), dict) else {}
    move = r.get("move") or {}
    marks = [today] + [s[1] for s in st]
    old, new = _d(move.get("old")), _d(move.get("new"))
    if old and new:
        marks += [old, new]
    ev = launch.get("evidence") or {}
    readout = _d(ev.get("date")) if ev.get("kind") == "readout" else None
    if readout:
        marks.append(readout)
    early = _d(lg.get("decision_date") or launch.get("decision_date"))
    std = _d((launch.get("standard") or {}).get("decision_date"))
    marks += [m for m in (early, std) if m]
    seed = launch.get("seed_year")
    if isinstance(seed, int):
        marks += [dt.date(seed, 1, 1), dt.date(seed, 12, 31)]
    lo, hi = min(marks), max(marks)
    y0 = lo.year + (0.5 if lo.month >= 7 else 0.0)
    y1 = hi.year + 1 + (0.0 if hi.month <= 6 else 0.5)
    y1 = max(y1, y0 + 3)
    span = y1 - y0
    if span > 9:                       # a far study is clamped, the axis stays readable
        y1 = y0 + 9
        span = 9

    def px(x):
        return L + (R - L) * (min(max(_frac_year(x), y0), y1) - y0) / span

    o = [f'<svg class="cx-svg dates" viewBox="0 0 {W} {H}" width="100%" role="img" '
         f'aria-label="Dates: studies, slips, earliest approval and the model launch year">',
         '<defs><marker id="ar-slip" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="6" '
         'markerHeight="6" orient="auto"><path d="M0 0L6 3L0 6z" class="slip-ar"/></marker>'
         '<marker id="ar-pull" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="6" markerHeight="6" '
         'orient="auto"><path d="M0 0L6 3L0 6z" class="pull-ar"/></marker></defs>']
    rs, ra, rm, ax = 34, 73, 92, 104
    for lbl, yy in (("STUDIES", rs), ("FDA", ra), ("MODEL", rm)):
        o.append(f'<text x="0" y="{yy + 3}" class="k">{lbl}</text>'
                 f'<line x1="{L}" x2="{R}" y1="{yy}" y2="{yy}" class="hair"/>')
    yr = math.ceil(y0)
    while yr <= y1:
        x = L + (R - L) * (yr - y0) / span
        o.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="12" y2="{ax - 6}" class="grid"/>'
                 f'<text x="{x:.1f}" y="{ax + 6}" class="tk m" text-anchor="middle">{yr}</text>')
        yr += 1
    tx = px(today)
    o.append(f'<line x1="{tx:.1f}" x2="{tx:.1f}" y1="8" y2="{ax - 6}" class="today"/>'
             f'<text x="{tx + 3:.1f}" y="8" class="tdl m">today</text>')
    if old and new and old != new and r.get("trial"):
        xo, xn = px(old), px(new)
        days = (new - old).days
        cls = "slip" if days > 0 else "pull"
        if abs(xn - xo) > 14:
            o.append(f'<circle cx="{xo:.1f}" cy="{rs}" r="3.5" class="old"/>'
                     f'<line x1="{xo + 5 if xn > xo else xo - 5:.1f}" x2="{xn - 7 if xn > xo else xn + 7:.1f}" '
                     f'y1="{rs - 9}" y2="{rs - 9}" class="{cls}-ln" marker-end="url(#ar-{cls})"/>')
        o.append(f'<text x="{min(max((xo + xn) / 2, L + 60), R - 60):.1f}" y="{rs - 14}" class="{cls}-t m" '
                 f'text-anchor="middle">{_plural(abs(days), "day")} {"later" if days > 0 else "earlier"} · seen '
                 f'{dm(move.get("seen"))}</text>')
    big = max([s[2] or 0 for s in st] + [1])
    for nct, dd, n, role in sorted(st, key=lambda s: -(s[2] or 0)):
        rad = 2.5 + 5 * math.sqrt((n or 0) / big)
        cls = {"gate": "st-gate", "held": "st-held", "open": "st-open"}[role]
        tip = (f"{nct} · {n:,} patients · completes {dmy(dd)} · {role}" if n
               else f"{nct} · completes {dmy(dd)} · {role}")
        o.append(f'<circle cx="{px(dd):.1f}" cy="{rs}" r="{rad:.1f}" class="{cls} {r["ph"]}">'
                 f'<title>{esc(tip)}</title></circle>')
    gate_st = [s for s in st if s[3] == "gate"]
    if gate_st:
        _n, dd, n, _ = gate_st[0]
        anchor = "end" if px(dd) > R - 70 else "start" if px(dd) < L + 70 else "middle"
        o.append(f'<text x="{px(dd):.1f}" y="{rs + 16}" class="lab m" text-anchor="{anchor}">gate '
                 f'{dm(dd)}{f" · {n:,}" if n else ""}</text>')
    others = [s for s in st if s[3] != "gate"]
    if others and not gate_st:
        last = max(others, key=lambda s: s[1])
        o.append(f'<text x="{min(px(last[1]), R - 2):.1f}" y="{rs + 17}" class="lab mu m" '
                 f'text-anchor="end">{len(others)} {"held" if last[3] == "held" else "open"}, to '
                 f'{mon(last[1])}</text>')
    if readout:
        xr_ = px(readout)
        anchor = "end" if xr_ > R - 70 else "start" if xr_ < L + 70 else "middle"
        o.append(f'<circle cx="{xr_:.1f}" cy="{rs}" r="4.5" class="st-gate p3"/>'
                 f'<text x="{max(xr_, L) if anchor == "start" else xr_:.1f}" y="{rs + 16}" '
                 f'class="lab m" text-anchor="{anchor}">Phase 3 positive {dm(readout)}</text>')
    if not st and not readout:
        o.append(f'<text x="{L + 4}" y="{rs - 5}" class="lab mu m">no study dated for this gate</text>')
    if early:
        x = px(early)
        o.append(f'<path d="M{x:.1f} {ra - 5} l5 5 l-5 5 l-5 -5z" class="dia"/>'
                 f'<text x="{x:.1f}" y="{ra - 8}" class="lab m" text-anchor="middle">earliest {mon(early)}</text>')
    if std:
        # Beside its diamond, right where it fits, left where the earliest is not in the
        # way, else under the line.
        x = px(std)
        text = f"standard {mon(std)}"
        w = _tw(text, 9.5, mono=True)
        xe = px(early) if early else None
        if x + 7 + w <= R:
            tx_, ty_, anchor = x + 7, ra + 3.5, "start"
        elif xe is None or not (x - 7 - w - 6 <= xe <= x):
            tx_, ty_, anchor = x - 7, ra + 3.5, "end"
        else:
            tx_, ty_, anchor = min(x + 4, R), ra + 13, "end"
        o.append(f'<path d="M{x:.1f} {ra - 4} l4 4 l-4 4 l-4 -4z" class="dia-o"/>'
                 f'<text x="{tx_:.1f}" y="{ty_}" class="lab mu m" '
                 f'text-anchor="{anchor}">{text}</text>')
    if not early:
        o.append(f'<text x="{L + 4}" y="{ra - 5}" class="lab mu m">no floor: no live Phase 3 or '
                 f'accepted application on file</text>')
    if isinstance(seed, int):
        xa, xb = px(dt.date(seed, 1, 1)), px(dt.date(seed, 12, 31))
        status = str(launch.get("status") or "not assessed").replace("_", " ")
        anchor = "end" if xa > L + 110 else "start"
        tx_ = xa - 4 if anchor == "end" else xb + 4
        o.append(f'<rect x="{xa:.1f}" y="{rm - 4}" width="{max(xb - xa, 2):.1f}" height="8" class="mdl"/>'
                 f'<text x="{tx_:.1f}" y="{rm + 3.5}" class="lab m" text-anchor="{anchor}">launch {seed} · '
                 f'{esc(status)}</text>')
    else:
        o.append(f'<text x="{L + 4}" y="{rm - 5}" class="lab mu m">no launch year seeded</text>')
    o.append("</svg>")
    return "".join(o)


def card_html(p, gid, facts_html="", lines=()) -> str:
    """The selected gate: what it is and when, its legs as a fork, its dates, the facts
    the Next gate block prints (passed in as ``facts_html``: chance, cost to reach, net,
    earliest approval) and the sentences under them."""
    r = _gate(p, gid)
    if r is None:
        return (f'<div class="cx cx-card none"><div class="cx-empty">No pipeline line carries a '
                f'priced next gate on this book, so there is no gate to select.</div></div>')
    rows = gate_rows(p)
    close = _close(p)
    t = r.get("trial") or {}
    sub = []
    if t.get("nct_id"):
        sub.append(f'<span class="m">{esc(t["nct_id"])}</span>')
        if t.get("enrollment"):
            sub.append(f'{t["enrollment"]:,} patients')
        cond = (t.get("conditions") or [t.get("indication")] or [None])[0]
        if cond:
            sub.append(esc(cond))
        if t.get("overall_status") or t.get("status"):
            sub.append(esc(str(t.get("overall_status") or t.get("status")).lower()))
    sub.append(esc(_when_long(r)))
    chips = ""
    if not r["priced"]:
        chips += '<span class="u-chip">no dated catalyst</span>'
    if r.get("legs_basis") == "derived":
        chips += f'<span class="u-chip basis" title="{esc(r.get("basis"))}">derived legs</span>'
    elif r.get("legs_basis") == "stated":
        chips += '<span class="u-chip basis">stated legs</span>'
    swing_share = (f" · {pct(r['swing'] / close, 1)} of price" if close and r["swing"] is not None
                   else "")
    note = (r.get("held") or {}).get("note")
    why = f'<div class="cx-why">{esc(r["why"])}</div>' if r.get("why") else ""
    lines_html = "".join(f'<div class="cx-line">{esc(x)}</div>' for x in lines if x)
    facts = facts_html or ""
    return (f'<div class="cx cx-card {r["ph"]}">'
            f'<div class="cx-card-k"><span>Selected gate · click a disc or a bar</span>'
            f'<span class="m">#{r["rank"]} of {len(rows)} by swing</span></div>'
            f'<div class="cx-card-h"><span class="cx-nm">{esc(r.get("name"))}</span>'
            f'<span class="stage s-{r["ph"]}">{esc(r["glabel"])}</span>{chips}</div>'
            f'<div class="cx-sub">{" · ".join(sub)}</div>{why}'
            f'<div class="cx-mh"><span>Legs · $ a share</span><span class="m">swing {usd(r["swing"])}'
            f'{swing_share}</span></div>{fork_svg(r, close)}'
            + (f'<div class="cx-cap">{esc(note)}</div>' if note else "")
            + f'<div class="cx-mh"><span>Dates</span><span class="m">studies sized by patients</span></div>'
            f'{dates_svg(r, _today(p))}'
            + (f'<div class="cx-facts">{facts}</div>' if facts else "")
            + lines_html + '</div>')


def resolve_text(r) -> str:
    """Why the card draws no record control: the stake row's own note, or that no
    catalyst row is on file to record against."""
    stake = (r or {}).get("stake")
    if not stake:
        return "No catalyst row on file to record against: the gate is priced from the model alone."
    return str(stake.get("resolve_note") or "Not resolved by hand.")


# --------------------------------------------------------------------------- next up
def next_rows(p, n=12) -> list:
    """The next dated events from today, in date order."""
    today = _today(p)
    out = [e for e in p.get("events") or [] if _d(e.get("date")) and _d(e["date"]) >= today]
    out.sort(key=lambda e: (e["date"], e.get("id") or 0))
    return out[:n]


def _why_short(e) -> str:
    if e.get("priced"):
        return f"{usd(e.get('per_share'))} at stake"
    if e.get("reason") == "no_gate" and e.get("marketed"):
        return "marketed, label expansion"
    return WHY_SHORT.get(e.get("reason"), "not priced")


def next_html(p, n=12) -> str:
    """Next up: date, line and phase, the registry condition and why it carries no price,
    patients on a square-root bar, and the line's model value a share."""
    rows = next_rows(p, n)
    today = _today(p)
    in12 = sum(1 for e in p.get("events") or [] if _d(e.get("date"))
               and today <= _d(e["date"]) <= today + dt.timedelta(days=365))
    head = section_html("Next up", "est. registry dates",
                        f"{len(rows)} of {in12} in 12 months")
    if not rows:
        return head + f'<div class="cx-empty">Nothing dated ahead for {esc(_ticker(p))}.</div>'
    big = max([(e.get("trial") or {}).get("enrollment") or 0 for e in rows] + [1])
    out = []
    for e in rows:
        t = e.get("trial") or {}
        n_ = t.get("enrollment")
        cond = (t.get("conditions") or [""])[0] if t.get("conditions") else ""
        w = 0 if not n_ else 3 + 34 * math.sqrt(n_ / big)
        ph = phase_class(e.get("phase"))
        url = e.get("url") or (f"https://clinicaltrials.gov/study/{e['nct']}" if e.get("nct") else "")
        tip = _event_tip(e)
        tag = "a" if url else "div"
        href = f' href="{esc(url)}" target="_blank" rel="noopener"' if url else ""
        why = _why_short(e)
        out.append(f'<{tag} class="cx-nr{" pr" if e.get("priced") else ""}"{href} title="{esc(tip)}">'
                   f'<span class="d m">{dm(e["date"])}</span>'
                   f'<span class="n"><b>{esc(e.get("asset") or "unmatched")}</b>'
                   f'<i class="mk-ph {ph}">{esc(str(e.get("phase") or "").replace("Phase ", "Ph "))}</i>'
                   f'<em>{esc(cond)}{" · " if cond else ""}{esc(why)}</em></span>'
                   f'<span class="pt"><i style="width:{w:.0f}px"></i><b class="m">'
                   f'{f"{n_:,}" if n_ else "n/a"}</b></span>'
                   f'<span class="v m">{usd(e.get("line_value")) if e.get("line_value") is not None else "n/a"}</span>'
                   f'</{tag}>')
    cols = ('<div class="cx-nr h"><span>date</span><span>line · condition · why no price</span>'
            '<span>patients</span><span>line $</span></div>')
    return head + '<div class="cx-next">' + cols + "".join(out) + "</div>"


# --------------------------------------------------------------------- risk register
def loe_svg(p, width=380) -> str:
    """Model value a share by the year the line loses exclusivity, the wall shaded."""
    by = {int(y): v for y, v in (p.get("loe_by_year") or {}).items() if str(y).isdigit()}
    today = _today(p)
    years = list(range(today.year, today.year + 15))
    H, B = 96, 80
    cw = (width - 4) / len(years)
    vmax = max([by.get(y, {}).get("per_share") or 0 for y in years] + [0.01])
    w = wall(p, today.year + 1)
    o = [f'<svg class="cx-svg loe" viewBox="0 0 {width} {H}" width="100%" role="img" '
         f'aria-label="Model value a share by the year the line loses exclusivity">',
         '<defs><pattern id="lh" width="4" height="4" patternUnits="userSpaceOnUse" '
         'patternTransform="rotate(45)"><rect width="1.3" height="4" class="lh-ln"/></pattern></defs>']
    if w:
        wx0 = 4 + (w[0] - years[0]) * cw
        wx1 = 4 + (w[1] + 1 - years[0]) * cw
        o.append(f'<rect x="{wx0:.1f}" y="4" width="{wx1 - wx0:.1f}" height="{B - 4}" class="wall"/>'
                 f'<text x="{(wx0 + wx1) / 2:.1f}" y="13" class="lab m" text-anchor="middle">'
                 f'{w[0]} to {w[1]} · {usd(w[2])}</text>')
    for i, yv in enumerate(years):
        e = by.get(yv)
        x = 4 + i * cw
        if e and e.get("per_share"):
            h = (B - 22) * e["per_share"] / vmax
            cls = ("lb-w" if w and w[0] <= yv <= w[1] else "lb-p" if yv <= today.year else "lb")
            fill = ' fill="url(#lh)"' if cls == "lb-p" else ""
            names = ", ".join(f"{q[0]} {usd(q[1])}" for q in e.get("products") or [])
            o.append(f'<g><title>{yv}: {esc(names)}</title><rect x="{x + 2:.1f}" y="{B - h:.1f}" '
                     f'width="{cw - 4:.1f}" height="{h:.1f}" class="{cls}"{fill}/>'
                     f'<text x="{x + cw / 2:.1f}" y="{B - h - 2:.1f}" class="lv m" '
                     f'text-anchor="middle">{e["per_share"]:.1f}</text></g>')
        if yv % 2 == 0:
            o.append(f'<text x="{x + cw / 2:.1f}" y="{B + 12}" class="tk m" text-anchor="middle">'
                     f'{yv if yv == years[0] else str(yv)[2:]}</text>')
    o.append(f'<line x1="2" x2="{width}" y1="{B}" y2="{B}" class="hair-s"/></svg>')
    return "".join(o)


def slips_svg(slips, width=380) -> str:
    """Each slip from its old date to its new, the one on a priced gate in down."""
    if not slips:
        return ""
    rh, L = 14, 104
    H = 14 + rh * len(slips) + 12
    lo = min(_d(s["old"]) for s in slips)
    hi = max(_d(s["new"]) for s in slips)
    y0, y1 = _frac_year(lo) - 0.2, _frac_year(hi) + 0.3

    def px(x):
        return L + (width - 8 - L) * (_frac_year(x) - y0) / max(y1 - y0, 0.5)

    o = [f'<svg class="cx-svg sl" viewBox="0 0 {width} {H}" width="100%" role="img" '
         f'aria-label="Readout dates that slipped, old to new">',
         '<defs><marker id="ar-s2" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="5" '
         'markerHeight="5" orient="auto"><path d="M0 0L6 3L0 6z" class="slip-ar"/></marker></defs>']
    for yv in range(math.ceil(y0), int(y1) + 1):
        x = L + (width - 8 - L) * (yv - y0) / max(y1 - y0, 0.5)
        o.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="8" y2="{H - 12}" class="grid"/>'
                 f'<text x="{x:.1f}" y="{H - 2}" class="tk m" text-anchor="middle">{str(yv)[2:]}</text>')
    for i, s in enumerate(slips):
        c = 14 + i * rh
        xo, xn = px(_d(s["old"])), px(_d(s["new"]))
        g = " g" if s.get("gate_asset") else ""
        name = str(s.get("asset") or s.get("nct"))
        o.append(f'<g><title>{esc(name)} {esc(s.get("nct"))}: {dmy(s["old"])} to {dmy(s["new"])}, '
                 f'{s["days"]} days, seen {dmy(s.get("seen"))}</title>'
                 f'<text x="0" y="{c + 3.5}" class="sl-n{g}">{esc(name[:17])}</text>'
                 f'<circle cx="{xo:.1f}" cy="{c}" r="2.5" class="old"/>'
                 + (f'<line x1="{xo + 3:.1f}" x2="{xn - 4:.1f}" y1="{c}" y2="{c}" class="slip-ln{g}" '
                    f'marker-end="url(#ar-s2)"/>' if xn - xo > 8 else "")
                 + f'<circle cx="{xn:.1f}" cy="{c}" r="2.8" class="new{g}"/>'
                 f'<text x="{min(xn + 6, width - 2):.1f}" y="{c + 3.5}" class="lab m"'
                 f'{" text-anchor=" + chr(34) + "end" + chr(34) if xn > width - 40 else ""}>{s["days"]}d</text></g>')
    o.append("</svg>")
    return "".join(o)


def crowd_svg(c, ticker, width=380) -> str:
    cp = c.get("company_pool") or {}
    lead = cp.get("leader") or {}
    vals = [(lead.get("ticker"), _num(lead.get("share_of_claims")), "lead"),
            (ticker, _num(cp.get("share_of_claims")), "me")]
    vals = [v for v in vals if v[0] and v[1] is not None]
    if not vals:
        return ""
    top = max(v[1] for v in vals) or 1
    o = [f'<svg class="cx-svg cr" viewBox="0 0 {width} {8 + 18 * len(vals)}" width="100%" role="img" '
         f'aria-label="Share of claims in the pool, the leader against {esc(ticker)}">']
    for i, (t, v, cls) in enumerate(vals):
        y = 4 + i * 18
        w = (width - 110) * v / top
        o.append(f'<text x="0" y="{y + 10}" class="cr-t m{" me" if cls == "me" else ""}">{esc(t)}</text>'
                 f'<rect x="44" y="{y + 2}" width="{w:.1f}" height="9" class="cr-{cls}"/>'
                 f'<text x="{48 + w:.1f}" y="{y + 10}" class="lab m">{pct(v, 1)}</text>')
    o.append("</svg>")
    return "".join(o)


def record_svg(readouts, width=380) -> str:
    """Signed Phase 3 results on a month axis: positive above the line, negative below."""
    rs = [r for r in readouts if _d(r.get("event_date"))]
    if not rs:
        return ""
    H = 50
    a = min(_d(r["event_date"]) for r in rs)
    b = max(_d(r["event_date"]) for r in rs)
    a, b = dt.date(a.year, a.month, 1) - dt.timedelta(days=10), b + dt.timedelta(days=20)

    def px(x):
        return 6 + (width - 12) * (x - a).days / max((b - a).days, 1)

    o = [f'<svg class="cx-svg rc" viewBox="0 0 {width} {H}" width="100%" role="img" '
         f'aria-label="Signed Phase 3 results">', f'<line x1="0" x2="{width}" y1="24" y2="24" class="hair-s"/>']
    m = dt.date(a.year, a.month, 1)
    while m <= b:
        if m >= a:
            o.append(f'<text x="{px(m):.1f}" y="{H - 2}" class="tk m" text-anchor="middle">{MON[m.month - 1][0]}</text>')
        m = dt.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    for r in rs:
        x = px(_d(r["event_date"]))
        good = r.get("outcome") == "positive"
        o.append(f'<g><title>{esc(r.get("asset") or r.get("drug"))} · Phase {esc(r.get("phase"))} '
                 f'{esc(r.get("outcome"))} · {dmy(r["event_date"])}</title>'
                 f'<line x1="{x:.1f}" x2="{x:.1f}" y1="24" y2="{14 if good else 34}" class="{"rc-u" if good else "rc-d"}"/>'
                 f'<circle cx="{x:.1f}" cy="{12 if good else 36}" r="4" class="{"rc-up" if good else "rc-dn"}"/></g>')
    o.append("</svg>")
    return "".join(o)


def _rr(a, b, c, cls="") -> str:
    return (f'<div class="cx-rr{(" " + cls) if cls else ""}"><span class="m">{a}</span>'
            f'<span>{b}</span><span class="m r">{c}</span></div>')


def risk_cards(p) -> list:
    """The five lanes of what could cost the company, each (key, kicker, figure, sub,
    visual, rows): exclusivity, slips, crowding, the readout record and the regulatory
    events with no date. A lane with nothing on file says so."""
    close = _close(p)
    ticker = _ticker(p)
    today = _today(p)
    rows = gate_rows(p)
    cards = []
    # 1. exclusivity
    w = wall(p, today.year + 1)
    cliffs = [c for c in p.get("cliffs") or [] if _d(c.get("loe"))]
    nxt = [c for c in cliffs if not c.get("passed") and c.get("model_per_share")]
    passed = [c for c in cliffs if c.get("passed") and c.get("model_per_share")]
    no_loe = p.get("no_loe") or []
    if w:
        fig = usd(w[2])
        share = f" · {pct(w[2] / close)} of price" if close else ""
        sub = f"a share on lines whose model LOE falls in {w[0]} to {w[1]}{share}"
        lines = []
        for y in range(w[0], w[1] + 1):
            for q in ((p.get("loe_by_year") or {}).get(str(y)) or {}).get("products") or []:
                lines.append(_rr(y, esc(q[0]), usd(q[1])))
        note = []
        if nxt:
            c = nxt[0]
            rev = (f" · {pct(c['share_of_revenue'], 1)} of {c.get('fy') or 'last year'}'s revenue"
                   if c.get("share_of_revenue") is not None else "")
            note.append(f"Next: <b>{esc(c['asset'])}</b> {dmy(c['loe'])}{rev} · "
                        f"{usd(c['model_per_share'])} a share.")
        if passed:
            c = passed[-1]
            note.append(f"{esc(c['asset'])} ended {dmy(c['loe'])} ({esc(c.get('loe_basis') or 'basis not on file')}), "
                        f"a {usd(c['model_per_share'])} line.")
        if no_loe:
            lines.append(_rr("none", f"{_plural(len(no_loe), 'line')} with no LOE on file",
                             usd(sum(v for _n, v in no_loe))))
        vis = loe_svg(p) + (f'<div class="rs-n">{" ".join(note)}</div>' if note else "")
        body = ("".join(lines) + '<div class="rs-f">Value the model carries on the line, not '
                'value lost at LOE. The year is the model\'s.</div>')
    else:
        fig, sub, vis, body = "none", "no model LOE year on file for a counted line", "", ""
    cards.append(("loe", "Loss of exclusivity", fig, sub, vis, body))
    # 2. slips
    slips = p.get("slips") or []
    if slips:
        top = slips[0]
        g = top.get("gate_asset")
        fig = f'{top["days"]}<span class="u">days</span>'
        swing = f"{usd(top['gate_swing'])} gate study" if g else "study"
        sub = f"{esc(top.get('asset') or top['nct'])}'s {swing} now reads {mon(top['new'])} · seen {dm(top.get('seen'))}"
        on_gate = sum(1 for s in slips if s.get("gate_asset"))
        vis = slips_svg(slips[:8])
        body = ("".join(_rr(f"{s['days']}d", f"{esc(s.get('asset') or s['nct'])} <span class=\"mu\">{esc(s['nct'])}</span>",
                            ("gate " + usd(s["gate_swing"])) if s.get("gate_asset") else esc(s.get("phase") or ""))
                        for s in slips)
                + f'<div class="rs-f">{_plural(len(slips), "primary-completion slip")} seen since '
                  f'{dm(min(s["seen"] for s in slips if s.get("seen")))}; '
                  f'{"none sits" if not on_gate else _plural(on_gate, "sits", "sit")} on a priced gate.</div>')
    else:
        fig, sub, vis, body = "none", "no primary-completion slip in the 30-day feed", "", ""
    cards.append(("slip", "Slips", fig, sub, vis, body))
    # 3. crowding
    c = p.get("crowding")
    cp = (c or {}).get("company_pool") or {}
    if c and cp.get("rank"):
        pool = c.get("pool") or {}
        lead = (cp.get("leader") or {}).get("ticker")
        fig = f'{ordinal(cp["rank"])}<span class="u">of {cp.get("of_companies") or NO_DATA}</span>'
        sub = f"{esc(ticker)} by share of {esc(str(c.get('indication') or '').lower())} claims" + (
            f" · {esc(lead)} leads" if lead else "")
        patients = pool.get("patients")
        vis = (crowd_svg(c, ticker) + f'<div class="rs-n">The model keeps <b>{pct(cp.get("keeps"))}</b> of the '
               f'patients {esc(ticker)} would reach alone: {pool.get("claimants") or NO_DATA} drugs from '
               f'{pool.get("companies") or NO_DATA} companies in a '
               f'{(f"{patients / 1e6:.1f}m" if patients else NO_DATA)}-patient pool.</div>')
        body = (_rr("", f"{esc(ticker)} value in {esc(str(c.get('indication') or '').lower())}", usd(c.get("value_per_share")))
                + _rr("", f"{esc(ticker)} claimants", f'{cp.get("claimants") or NO_DATA} of {pool.get("claimants") or NO_DATA}')
                + _rr("", "Share of the pool", pct(cp.get("share_of_pool"), 1))
                + '<div class="rs-f">Model output: crowding in the patient pool the forecast draws on.</div>')
    else:
        fig, sub, vis, body = "none", "no crowded pool in a valued indication", "", ""
    cards.append(("pool", "Crowding", fig, sub, vis, body))
    # 4. the record
    ro = p.get("readouts") or []
    if ro:
        npos = sum(1 for r in ro if r.get("outcome") == "positive")
        first = min((_d(r.get("event_date")) for r in ro if _d(r.get("event_date"))), default=None)
        fig = f'{npos}<span class="u">of {len(ro)}</span>'
        sub = f"signed Phase 3 results positive since {mon(first)}"
        gates = {r["asset_id"]: r for r in rows}
        flags = []
        for r in ro:
            g = gates.get(r.get("asset_id"))
            if r.get("outcome") == "negative" and g and _d(r.get("event_date")):
                flags.append(f'{esc(r.get("asset") or r.get("drug"))} negative {dm(r["event_date"])} is not on the '
                             f'book: the model holds it at {pct(g.get("pos_now"))} ({usd(g["now"])} a share).')
        vis = record_svg(ro) + "".join(f'<div class="rs-n warn">{f}</div>' for f in flags)
        body = "".join(_rr(dm(r.get("event_date")), esc(r.get("asset") or r.get("drug")),
                           f'<span class="{"up-t" if r.get("outcome") == "positive" else "dn-t"}">{esc(r.get("outcome"))}</span>')
                       for r in ro)
    else:
        fig, sub, vis, body = "none", "no signed Phase 3 result on file", "", ""
    cards.append(("rec", "Record", fig, sub, vis, body))
    # 5. undated regulatory events
    floors = [r for r in rows if r.get("fl")]
    reg = p.get("regulatory") or []
    n = len(floors) + len(reg)
    if n:
        fig = str(n)
        sub = "regulatory events with no date on file, so none reaches the calendar"
        lines = [_rr(f"≥ {mon(r['fl'])}", f"{esc(r['name'])} FDA decision", usd(r["swing"])) for r in floors]
        for x in reg:
            name = x.get("asset") or str(x.get("headline") or "")[:40]
            lines.append(_rr(dm(x.get("date")), esc(name), f'<span class="mu">{esc(x.get("kind"))}</span>'))
        vis = (f'<div class="rs-n">{_plural(len(floors), "FDA decision")} after a positive Phase 3 drawn at the '
               f'earliest approval, and {_plural(len(reg), "regulatory item")} from the change feed.</div>')
        body = ("".join(lines) + '<div class="rs-f">Priority Reviews and CHMP opinions come from the change '
                'feed; the floors are the earliest approval from the readout and the PDUFA review clock.</div>')
    else:
        fig, sub, vis, body = "none", "every regulatory event on file carries a date", "", ""
    cards.append(("reg", "Undated", fig, sub, vis, body))
    return cards


def risks_html(p) -> str:
    """The risk register: five cards as one accordion, a card's rows one click away."""
    out = []
    for key, kicker, fig, sub, vis, body in risk_cards(p):
        empty = fig == "none"
        out.append(f'<details class="cx-risk k-{key}{" empty" if empty else ""}" name="cx-risk">'
                   f'<summary><span class="rk">{esc(kicker)}<i></i></span>'
                   f'<span class="rf m">{fig}</span><span class="rsub">{sub}</span></summary>'
                   f'<div class="rb">{vis}{body}</div></details>')
    return (section_html("Risk register", "what could cost " + _ticker(p), "click a card for its rows")
            + '<div class="cx-risks">' + "".join(out) + "</div>")


# ------------------------------------------------------------------------- unpriced
def unpriced_html(p) -> str:
    """Why the rest of the dated events carry no price: one bar by reason, its key, and
    the names behind each reason."""
    cnt = p.get("unpriced_reasons") or {}
    tot = sum(cnt.values())
    events = p.get("events") or []
    priced = sum(1 for e in events if e.get("priced"))
    head = section_html(f"Why {tot} events carry no price", "stakes, by reason",
                        f"{tot} of {tot + priced}")
    if not tot:
        return head + '<div class="cx-empty">Every dated event on file carries a price.</div>'
    segs, keys, groups = [], [], []
    known = [k for k, _l in REASONS] + sorted(k for k in cnt if k not in dict(REASONS))
    labels = dict(REASONS)
    for k in known:
        n = cnt.get(k, 0)
        if not n:
            continue
        cls = REASON_CLASS.get(k, "u0")
        label = labels.get(k, k.replace("_", " "))
        segs.append(f'<i class="{cls}" style="flex:{n}" title="{n} · {esc(label)}"><b>{n}</b></i>')
        keys.append(f'<span><i class="{cls}"></i><b class="m">{n}</b> {esc(label)}</span>')
        names = []
        for e in events:
            if e.get("reason") == k and e.get("asset") and e["asset"] not in names:
                names.append(e["asset"])
        shown = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
        groups.append(f'<div class="cx-ug"><span class="k"><i class="{cls}"></i>{esc(label)}</span>'
                      f'<span class="v">{esc(shown) or NO_DATA}</span></div>')
    ex = next((e for e in events if e.get("reason") == "other_indication" and e.get("why")), None)
    example = (f'<div class="rs-n">{esc(ex.get("asset") or "")} {dm(ex.get("date"))}: '
               f'{esc(ex["why"])}</div>' if ex else "")
    return (head + f'<div class="cx-ub">{"".join(segs)}</div><div class="cx-uk">{"".join(keys)}</div>'
            + example + '<div class="cx-ugs">' + "".join(groups) + "</div>")


# --------------------------------------------------------------------------- dialog
def programme_svg(r, today, width=500) -> str:
    """Every study behind the gate as a bar from start to primary completion."""
    items = []
    t = r.get("trial") or {}
    if t.get("nct_id"):
        items.append((t["nct_id"], _d(t.get("start_date")), _d(t.get("primary_completion")
                                                              or t.get("primary_completion_date")),
                      t.get("enrollment"), "gate", (t.get("conditions") or [t.get("indication") or ""])[0],
                      t.get("overall_status") or t.get("status")))
    for s in (r.get("held_studies") or []) + (r.get("open_studies") or []):
        items.append((s.get("nct_id"), _d(s.get("start_date")), _d(s.get("primary_completion_date")),
                      s.get("enrollment"), "held", (s.get("conditions") or [""])[0], s.get("overall_status")))
    items = [i for i in items if i[2]]
    if not items:
        return ""
    items.sort(key=lambda i: i[2])
    rh, nx = 20, 168
    H = 22 + rh * len(items) + 16
    lo = min([i[1] for i in items if i[1]] + [today])
    hi = max(i[2] for i in items)
    y0, y1 = float(lo.year), float(hi.year + 1)

    def px(x):
        return nx + (width - 66 - nx) * (_frac_year(x) - y0) / max(y1 - y0, 1)

    o = [f'<svg class="cx-svg pg" viewBox="0 0 {width} {H}" width="100%" role="img" '
         f'aria-label="Studies behind the gate, start to primary completion">']
    for yv in range(int(y0), int(y1) + 1):
        x = nx + (width - 66 - nx) * (yv - y0) / max(y1 - y0, 1)
        o.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="12" y2="{H - 14}" class="grid"/>'
                 f'<text x="{x:.1f}" y="{H - 2}" class="tk m" text-anchor="middle">{yv}</text>')
    tx = px(today)
    o.append(f'<line x1="{tx:.1f}" x2="{tx:.1f}" y1="6" y2="{H - 14}" class="today"/>'
             f'<text x="{tx + 3:.1f}" y="8" class="tdl m">today</text>'
             f'<text x="{width}" y="8" class="k" text-anchor="end">PATIENTS</text>')
    big = max([i[3] or 0 for i in items] + [1])
    for k, (nct, s0, s1, n, role, cond, status) in enumerate(items):
        y = 14 + k * rh
        g = role == "gate"
        xa = px(s0) if s0 else px(today)
        o.append(f'<g><title>{esc(nct)} · {esc(cond)} · {esc(status)} · '
                 f'{(f"{n:,} patients" if n else "enrolment not on file")} · start '
                 f'{dmy(s0) if s0 else NO_DATA}, completes {dmy(s1)}</title>'
                 f'<text x="0" y="{y + 11}" class="pg-n{" g" if g else ""}">{esc(str(cond or nct)[:28])}</text>'
                 f'<rect x="{xa:.1f}" y="{y + 4}" width="{max(px(s1) - xa, 2):.1f}" height="8" '
                 f'class="{"pg-g " + r["ph"] if g else "pg-h"}"/>'
                 f'<circle cx="{px(s1):.1f}" cy="{y + 8}" r="3.5" class="{"pg-gd " + r["ph"] if g else "pg-hd"}"/>'
                 f'<rect x="{width - 58}" y="{y + 5}" width="{36 * (n or 0) / big:.1f}" height="6" class="pg-pt"/>'
                 f'<text x="{width}" y="{y + 12}" class="lab m" text-anchor="end">{(f"{n:,}" if n else "n/a")}</text></g>')
    o.append("</svg>")
    return "".join(o)


def _kv(k, v, cls="") -> str:
    return f'<div class="mk-kv{(" " + cls) if cls else ""}"><span>{esc(k)}</span><span>{v}</span></div>'


# One step of a published chance chain in the gate's basis: "Phase 2 to Phase 3 28.9%",
# "Phase 3 to NDA/BLA 57.8%", "NDA/BLA to approval 90.6%".
_STEP = re.compile(r"(Phase \d(?:/\d)?|NDA/BLA) to (Phase \d|NDA/BLA|approval) ([\d.]+)%")


def odds_steps(basis) -> list:
    """[(what passing the step means, the published rate)] of the basis, in order: every
    step from the gate to approval, so a Phase 2 gate's chain starts at Phase 2."""
    out = []
    for frm, to, rate in _STEP.findall(str(basis or "")):
        what = "filing to approval" if frm == "NDA/BLA" else f"pass {frm}"
        out.append((what, float(rate) / 100))
    return out


def _odds_chain(r) -> str:
    """The published steps from the gate to approval multiplied out, then the PoS the model
    holds today with its band. The product is of the rates printed, so the sum reads; the
    model's PoS can differ where the asset's own gate sets the odds."""
    band = r.get("band") or {}
    band_txt = (f", band {pct(band.get('pos_low'), 1)} to {pct(band.get('pos_high'), 1)} "
                f"({usd(band.get('per_share_low'))} to {usd(band.get('per_share_high'))} a share)"
                if band.get("pos_low") is not None else "")
    tail = f'<div class="cx-p mut">PoS today {pct(r.get("pos_now"), 1)}{esc(band_txt)}.</div>'
    steps = odds_steps(r.get("basis"))
    if len(steps) < 2:
        return tail
    product = math.prod(rate for _w, rate in steps)
    parts = '<span class="x">×</span>'.join(
        f'<span><b>{pct(rate, 1)}</b> {esc(what)}</span>' for what, rate in steps)
    return (f'<div class="cx-chain">{parts}<span class="x">=</span>'
            f'<span><b>{pct(product, 1)}</b> published</span></div>' + tail)


def dialog_html(p, gid, cost_html="", ladder_html="", studies_html="") -> str:
    """The full detail of one gate: its legs as a table, the odds, what is held behind it,
    the cost to reach it (the Next gate block's tables, passed in), every study behind it
    on one timeline, its dates and clock, where it sits in its market, and the evidence."""
    r = _gate(p, gid)
    if r is None:
        return '<div class="cx cx-dlg"><div class="cx-empty">This gate is not on the book.</div></div>'
    close = _close(p)
    today = _today(p)
    t = r.get("trial") or {}
    held = r.get("held") or {}
    launch = r.get("launch") or {}
    lg = launch.get("gate") if isinstance(launch.get("gate"), dict) else {}
    clock = launch.get("clock") or {}
    std = launch.get("standard") or {}
    move = r.get("move") or {}
    m = r.get("model") or {}
    p_gate = r.get("p_gate")
    legs = [("Today", pct(r.get("pos_now")), r.get("rnpv_now"), usd(r["now"]), "", "")]
    legs.append((f"Gate passes · {pct(p_gate)}", pct(r.get("pos_success")), r.get("rnpv_success"),
                 usd(r["success"]), sgn(r["up"]), "up"))
    if r.get("held_ps") is not None:
        legs.append((f"Gate misses, {_plural(held.get('open') or 0, 'Phase 3')} open · "
                     f"{pct(None if p_gate is None else 1 - p_gate)}", pct(held.get("pos")), None,
                     usd(r["held_ps"]), "held", ""))
    legs.append(("Programme fails", pct(r.get("pos_failure")), r.get("rnpv_failure"), leg(r["failure"]),
                 sgn(None if None in (r["failure"], r["now"]) else r["failure"] - r["now"]), "down"))
    leg_rows = "".join(
        f'<tr><td class="rs-k">{esc(a)}</td><td class="rs-v">{b}</td>'
        f'<td class="rs-v">{"as today" if c is None and a.startswith("Gate misses") else ("" if c is None else "nil" if c == 0 else f"{c:,.0f}")}</td>'
        f'<td class="rs-v">{dd}</td><td class="rs-v {tone}">{e}</td></tr>'
        for a, b, c, dd, e, tone in legs)
    chips = "".join(f'<span class="u-chip basis{" flag" if v == "convention" else ""}">{k} '
                    f'{EVIDENCE.get(v, v)}</span>'
                    for k, v in (("odds", (r.get("evidence") or {}).get("p_gate")),
                                 ("pass leg", (r.get("evidence") or {}).get("success")),
                                 ("miss leg", (r.get("evidence") or {}).get("failure"))) if v)
    stake = r.get("stake") or {}
    if stake.get("resolvable"):
        miss_txt = (f"PoS stays {pct(held.get('pos'))} while {_plural(held.get('open') or 0, 'Phase 3')} "
                    f"stay open; nil only if they miss too" if r.get("held_ps") is not None
                    else f"PoS to {pct(r.get('pos_failure'))}, {usd(r['failure'])} a share")
        record = (f'<div class="cx-dh2">Record the outcome</div><div class="cx-rec">'
                  f'<div class="cx-rec-c up"><div class="k">If you record met</div><div class="v m">'
                  f'{usd(r["now"])} to {usd(r["success"])}</div><div class="s">PoS {pct(r.get("pos_now"))} '
                  f'to {pct(r.get("pos_success"))} · {sgn(r["up"])} a share</div></div>'
                  f'<div class="cx-rec-c"><div class="k">If you record missed</div><div class="v m">'
                  f'{usd(r["held_ps"] if r.get("held_ps") is not None else r["failure"])}</div>'
                  f'<div class="s">{esc(miss_txt)}</div></div></div>'
                  f'<div class="rs-f">Two clicks each, under the buttons below: arm, then confirm. It writes '
                  f'to the book.</div>')
    else:
        record = (f'<div class="cx-dh2">Record the outcome</div>'
                  f'<div class="rs-f">{esc(resolve_text(r))}</div>')
    cost = cost_html or f'<div class="cx-none">{NO_DATA}: no development cost is read for this gate.</div>'
    left = (f'<div class="cx-dh2">Legs at the gate <span class="w">$ a share against the '
            f'{usd(close)} close</span></div>'
            f'<table class="rs"><thead><tr><th>Outcome</th><th>PoS</th><th>rNPV $mm</th><th>$ a share</th>'
            f'<th>Move</th></tr></thead><tbody>{leg_rows}</tbody></table>'
            + (f'<div class="cx-cap">{esc(held.get("note"))}</div>' if held.get("note") else "")
            + f'<div class="cx-dh2">Chance of passing <span class="w">{pct(p_gate, 1)} · published '
              f'{pct(r.get("p_gate_published"), 1)}</span></div>{_odds_chain(r)}'
            + _kv("Basis", f'<span class="wrap">{esc(r.get("basis"))}</span>')
            + _kv("Evidence", f'<span class="cx-chips">{chips}</span>')
            + f'<div class="cx-dh2">Cost to reach the gate <span class="w">build 1 · after tax</span></div>'
            + cost
            + (f'<details class="cx-more"><summary>After later trial costs</summary>{ladder_html}</details>'
               if ladder_html else "")
            + (f'<details class="cx-more"><summary>Trials and sources behind the cost</summary>'
               f'{studies_html}</details>' if studies_html else "")
            + record)
    dates = []
    if move.get("old") and move.get("new") and move.get("days"):
        later = "later" if move["days"] > 0 else "earlier"
        dates.append(_kv("Gate date", f'{dmy(move["new"])} est. · was {dmy(move["old"])} · '
                                      f'<b class="{"dn-t" if move["days"] > 0 else "up-t"}">'
                                      f'{_plural(abs(move["days"]), "day")} {later}</b>, seen '
                                      f'{dmy(move.get("seen"))}'))
    elif r.get("d"):
        dates.append(_kv("Gate date", f'{dmy(r["d"])} · {esc(r.get("date_basis") or "registry")}'
                                      + (" · due, no result on file" if r.get("due") else "")))
    else:
        dates.append(_kv("Gate date", esc(r.get("why") or "no date on file")))
    early = lg.get("decision_date") or launch.get("decision_date")
    if early:
        dates.append(_kv("Earliest approval", f'{dmy(early)} · {esc(clock.get("review") or "review")} review, '
                                              f'{clock.get("months") or NO_DATA} months from the filing date'))
    else:
        dates.append(_kv("Earliest approval", f"{NO_DATA}: no live Phase 3 or accepted application on file"))
    if std.get("decision_date"):
        dates.append(_kv("Standard review", f'{dmy(std["decision_date"])} · {std.get("months")} months'))
    if launch.get("seed_year"):
        dates.append(_kv("Model launch", f'{launch["seed_year"]} · '
                                         f'{esc(str(launch.get("status") or "not assessed").replace("_", " "))}'))
    if launch.get("message"):
        dates.append(f'<div class="cx-p mut">{esc(launch["message"])}</div>')
    if clock.get("source"):
        dates.append(_kv("Clock source", f'<span class="wrap">{esc(clock["source"])}</span>'))
    market = []
    c = p.get("crowding") or {}
    if c and r["asset_id"] in (c.get("asset_ids") or []):
        cp = c.get("company_pool") or {}
        pool = c.get("pool") or {}
        lead = cp.get("leader") or {}
        market.append(_kv(f'{str(c.get("indication") or "").capitalize()} pool',
                          f'{pool.get("claimants") or NO_DATA} drugs · {pool.get("companies") or NO_DATA} companies'
                          + (f' · {pool["patients"] / 1e6:.1f}m patients' if pool.get("patients") else "")))
        if cp.get("rank"):
            market.append(_kv(f"{_ticker(p)} place", f'{ordinal(cp["rank"])} of {cp.get("of_companies")} by share '
                                                     f'of claims, {pct(cp.get("share_of_claims"), 1)}'
                                                     + (f' · {esc(lead.get("ticker"))} leads at '
                                                        f'{pct(lead.get("share_of_claims"), 1)}' if lead.get("ticker") else "")))
        market.append(_kv("Model keeps", f'{pct(cp.get("keeps"))} of the patients {_ticker(p)} would reach alone'))
    if m.get("peak_revenue"):
        market.append(_kv("Peak revenue", f'${m["peak_revenue"] / 1000:.1f}bn in {m.get("peak_year")} · '
                                          f'model, LOE {m.get("loe_year") or NO_DATA}'))
    else:
        market.append(_kv("Peak revenue", NO_DATA))
    if m.get("per_share") is not None:
        share = f" · {pct(m['per_share'] / close, 1)} of price" if close else ""
        market.append(_kv("Line value", f'{usd(m["per_share"])} a share{share}'))
    ev = []
    if t.get("nct_id"):
        ev.append((f"https://clinicaltrials.gov/study/{t['nct_id']}", f"ClinicalTrials.gov {t['nct_id']}"))
    stake_url = stake.get("source_url")
    if stake_url and not (t.get("nct_id") and t["nct_id"] in stake_url):
        ev.append((stake_url, "Catalyst source"))
    src = re.search(r"\((https://www\.fda\.gov/[^)]+)\)", clock.get("source") or "")
    if src:
        ev.append((src.group(1), "PDUFA commitment letter, review clock"))
    ev_html = "".join(f'<a href="{esc(u)}" target="_blank" rel="noopener">{esc(x)}</a>' for u, x in ev)
    gantt = programme_svg(r, today)
    right = ((f'<div class="cx-dh2">Studies behind the gate <span class="w">start to primary completion'
              f'</span></div>{gantt}' if gantt else "")
             + '<div class="cx-dh2">Dates</div>' + "".join(dates)
             + '<div class="cx-dh2">Market and model</div>' + "".join(market)
             + (f'<div class="cx-dh2">Evidence</div><div class="cx-ev">{ev_html}</div>' if ev_html else ""))
    when, _due = date_text(r)
    sub = []
    if t.get("nct_id"):
        sub.append(f'<span class="m">{esc(t["nct_id"])}</span>')
        if t.get("enrollment"):
            sub.append(f'{t["enrollment"]:,} patients')
        if t.get("title"):
            sub.append(esc(t["title"]))
    sub.append(esc(_when_long(r)))
    share = f"{pct(r['swing'] / close, 1)} of the {usd(close)} close" if close and r["swing"] is not None else ""
    head = (f'<div class="cx-dhd"><div><div class="kick"><i class="ph {r["ph"]}"></i>{esc(r["glabel"])} · '
            f'{esc(when)}{" · " + esc(r.get("area")) if r.get("area") else ""}</div>'
            f'<div class="cx-sub dlg">{" · ".join(sub)}</div></div>'
            f'<div class="hero"><span class="fig m">{usd(r["swing"])}</span><span class="u">a share at stake</span>'
            f'<span class="sub">{esc(share)} · {ordinal(r["rank"])} of {len(gate_rows(p))} by swing</span></div></div>')
    return (f'<div class="cx cx-dlg">{head}<div class="cx-dgrid"><div>{left}</div><div>{right}</div></div></div>')


def dialog_title(p, gid) -> str:
    r = _gate(p, gid)
    return f"{r.get('name')} · {r['glabel']}" if r else "Gate"


def notes_text(p) -> str:
    """Where every figure on the tab comes from, said once."""
    return ("Gates, legs and odds: the company's forecast verdict, each line at its next gate. Dated "
            "catalysts and why the rest carry no price: the catalyst stakes. Cost to reach and net: the "
            "development view, after tax at 2018 trial prices. Earliest approval: the launch floor from "
            "the registry and the PDUFA review clock. Slips and regulatory items: the 30-day change feed. "
            "Exclusivity: the exclusivities on file and the model's LOE year. Every registry date is an "
            "estimate; none is curated.")
