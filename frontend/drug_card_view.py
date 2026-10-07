"""The drug card of Comps > Indications: one drug in one indication, opened by a click on
its bubble in the clinical scorecard or its row in the ranked table.

Pure builders over the payload of ``GET /indications/{id}/drug/{asset_id}``
(backend/drug_card.py). ``card_html`` returns the head and the panes as markup strings for
``st.markdown`` inside an ``st.dialog``; nothing here touches Streamlit, the network or a
clock, so the tests run it on a saved payload. Every figure is the payload's own: a null
is printed as "no free data", or its section says what is not on file, and never drawn as
a zero.
"""

from __future__ import annotations

import datetime as dt
import html

NO_DATA = "no free data"
DOT = "·"
MAX_TRIALS = 12

# The patient-build inputs in the engine's order, each with how its value reads.
_INPUTS = {
    "prevalence": "prevalence",
    "incidence": "new cases a year",
    "eligible_pct": "eligible share",
    "penetration_peak_pct": "peak penetration",
    "exus_multiple": "ex-US multiple",
    "list_price_per_patient": "list price",
    "gross_to_net_pct": "gross to net",
    "net_price_per_patient": "net price",
}


def _e(text) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def _pct(v, digits: int = 0) -> str | None:
    return None if v is None else f"{v * 100:.{digits}f}%"


def _num(v, digits: int = 0) -> str | None:
    return None if v is None else f"{v:,.{digits}f}"


def _date(text) -> str | None:
    if not text:
        return None
    try:
        return dt.date.fromisoformat(str(text)[:10]).strftime("%-d %b %Y")
    except ValueError:
        return str(text)


def _cur(model: dict | None) -> str:
    return ((model or {}).get("currency") or "USD").upper()


def per_share(v, cur: str) -> str | None:
    """A value a share in its currency: $10.31, or CHF 0.58."""
    if v is None:
        return None
    return f"${v:,.2f}" if cur == "USD" else f"{cur} {v:,.2f}"


def millions(v, cur: str) -> str | None:
    """A figure in millions in its currency: $9,756mm, or 1,609mm CHF."""
    if v is None:
        return None
    return f"${v:,.0f}mm" if cur == "USD" else f"{v:,.0f}mm {cur}"


def _fig(key: str, value, sub: str = "", cls: str = "") -> str:
    """One figure: the value over its label and a short basis. A null reads no free data."""
    shown = value if value not in (None, "") else NO_DATA
    none = " none" if value in (None, "") else ""
    return (f'<div class="dc-f"><span class="v{none} {cls}">{_e(shown)}</span>'
            f'<span class="k">{_e(key)}</span>'
            + (f'<span class="s">{_e(sub)}</span>' if sub else "") + "</div>")


def _figs(cells: list) -> str:
    return '<div class="dc-figs">' + "".join(cells) + "</div>"


def _h(title: str, aside: str = "") -> str:
    return (f'<div class="dc-h2">{_e(title)}'
            + (f'<span class="w">{_e(aside)}</span>' if aside else "") + "</div>")


def _none(text: str) -> str:
    return f'<div class="dc-none">{_e(text)}</div>'


def _kv(key: str, value) -> str:
    return (f'<div class="dc-kv"><span>{_e(key)}</span>'
            f'<span>{_e(value if value not in (None, "") else NO_DATA)}</span></div>')


def _table(head: list, rows: list, cls: str = "") -> str:
    """A short table; ``rows`` are lists of cell markup, already escaped."""
    th = "".join(f"<th>{_e(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(rows_) + "</tr>" for rows_ in rows)
    return (f'<div class="dc-tw"><table class="dc-t {cls}"><thead><tr>{th}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def _td(value, num: bool = False, muted: bool = False) -> str:
    cls = " ".join(c for c in ("n" if num else "", "m" if muted or value in (None, "") else "")
                   if c)
    return (f'<td{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>'
            f'{_e(value) if value not in (None, "") else DOT}</td>')


def _nct(nct: str | None) -> str:
    if not nct:
        return f'<td class="m">{DOT}</td>'
    return (f'<td><a href="https://clinicaltrials.gov/study/{_e(nct)}" target="_blank">'
            f"{_e(nct)}</a></td>")


# --- the head -------------------------------------------------------------------------
def _what_it_is(h: dict) -> str:
    mech = "; ".join(m.get("value") for m in h.get("mechanisms") or [] if m.get("value"))
    targets = ", ".join(t for t in h.get("targets") or [] if t.lower() not in mech.lower())
    modality = h.get("modality") or ", ".join(h.get("molecule_type") or [])
    route = ", ".join(h.get("route") or []).lower()
    parts = [
        ("modality", modality or None),
        ("mechanism", mech or "; ".join(h.get("classes") or []) or None),
        ("target", targets or None),
        ("route", route or None),
    ]
    return "".join(f'<span class="dc-wi"><span class="k">{k}</span> '
                   f'{_e(v) if v else f"<i>{NO_DATA}</i>"}</span>' for k, v in parts
                   if v or k in ("mechanism",))


def _stage_text(h: dict) -> str:
    stage = h.get("stage") or "not staged"
    if h.get("phase_elsewhere"):
        stage += ", further along elsewhere"
    return stage


def head_html(c: dict) -> str:
    """Who and what: brand, company, stage here, what it is, any boxed warning, then the
    figures the card's panes explain."""
    h = c.get("head") or {}
    ind = (c.get("indication") or {}).get("name") or ""
    brands = h.get("brands") or []
    kick = " · ".join(x for x in (
        h.get("ticker"), h.get("company"),
        ("sold as " + ", ".join(brands)) if brands else None) if x)
    stage = (f'<span class="dc-stage">{_e(_stage_text(h))}</span>'
             f'<span class="dc-in">in {_e(ind)}</span>')
    boxed = h.get("boxed_warning")
    warn = (f'<div class="dc-warn"><b>Boxed warning.</b> {_e(_clip(boxed, 420))}</div>'
            if boxed else "")
    s = c.get("score") or {}
    model = c.get("model") or {}
    cur = _cur(model)
    val = (c.get("valuation") or [{}])[0] or {}
    # The model's exclusivity first; for a product the book does not value, the date its
    # profile reads from the Orange Book and Purple Book.
    loe = ((c.get("commercial") or {}).get("loe") or {}) if not val.get("loe_year") else {}
    rank = (f'rank {s["rank"]} of {s["of"]}' if s.get("placed") and s.get("rank") else
            (s.get("why_not") or "not scored") if s else "not on the scorecard")
    trials = c.get("trials") or []
    figs = _figs([
        _fig("overall score", _num(s.get("overall")) if s.get("placed") else None, rank),
        _fig("value a share", per_share(model.get("per_share"), cur),
             (f'{_pct(val.get("pct_of_price"), 1)} of the share price'
              if val.get("pct_of_price") is not None else
              "not valued in the book" if not model else "")),
        _fig("probability of success", _pct(model.get("pos")),
             "marketed" if model.get("pos") == 1 and h.get("is_marketed") else ""),
        _fig("peak revenue", millions(model.get("peak_revenue"), cur),
             f'in {model["peak_year"]}' if model.get("peak_year") else ""),
        _fig("exclusivity to", val.get("loe_year") or loe.get("loe_year"),
             _clip(val.get("loe_basis") or loe.get("basis"), 40)
             if (val.get("loe_basis") or loe.get("basis")) else ""),
        _fig("trials posted", f'{c.get("with_results") or 0} of {len(trials)}' if trials
             else None, "linked here, with results"),
    ])
    return (f'<div class="dc dc-head"><div class="dc-kick">{_e(kick)}</div>'
            f'<div class="dc-line">{stage}</div>'
            f'<div class="dc-what">{_what_it_is(h)}</div>{warn}{figs}</div>')


def _clip(text, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]) + "..."


# --- clinical -------------------------------------------------------------------------
def _score_block(c: dict) -> str:
    s = c.get("score")
    if not s:
        return _h("Clinical scorecard") + _none("Not on this indication's scorecard.")
    if not s.get("placed"):
        return (_h("Clinical scorecard", f'{s.get("of")} of {s.get("scored_of")} scored')
                + _none("Not placed on the scorecard: " + (s.get("why_not") or "not scored")
                        + ". A score is never guessed."))
    eff, saf, ev = s.get("efficacy") or {}, s.get("safety") or {}, s.get("evidence") or {}
    rr = s.get("rank_range") or []
    span = (f", could sit {rr[0]} to {rr[1]}" if len(rr) == 2 and rr[0] != rr[1] else "")
    ep, sp = eff.get("parts") or {}, saf.get("parts") or {}
    eff_sub = ", ".join(x for x in (
        f'strength {ep["strength"]:.0f}' if ep.get("strength") is not None else "",
        f'wins {ep["wins"]:.0f}' if ep.get("wins") is not None else "",
        f'size {ep["size"]:.0f}' if ep.get("size") is not None else "") if x)
    if eff.get("size_basis") == "not comparable":
        eff_sub += (", " if eff_sub else "") + "size not compared"
    saf_sub = ", ".join(x for x in (
        f'staying on {sp["staying_on"]:.0f}' if sp.get("staying_on") is not None else "",
        f'serious {sp["serious"]:.0f}' if sp.get("serious") is not None else "") if x)
    ev_sub = ", ".join(x for x in (
        f'{ev["participants"]:,} treated' if ev.get("participants") else "",
        ev.get("phase") or "", f'{ev["confidence"]} confidence' if ev.get("confidence") else "")
        if x)
    figs = _figs([
        _fig("overall", _num(s.get("overall")), f'rank {s.get("rank")} of {s.get("of")}{span}'),
        _fig("efficacy", _num(eff.get("score")), eff_sub),
        _fig("safety", _num(saf.get("score")), saf_sub),
        _fig("evidence", _num(ev.get("score")), ev_sub),
    ])
    lines = (eff.get("lines") or []) + (saf.get("lines") or [])
    care = [saf["read_with_care"]] if saf.get("read_with_care") else []
    body = "".join(f'<p class="dc-p">{_e(x)}</p>' for x in lines + care)
    notes = (eff.get("notes") or []) + (saf.get("notes") or [])
    more = ('<details class="dc-more"><summary>What else each score rests on</summary>'
            + "".join(f'<p class="dc-p mut">{_e(x)}</p>' for x in notes) + "</details>"
            if notes else "")
    reg = s.get("regimen") or {}
    given = " ".join(x for x in (reg.get("dose"), reg.get("form"), reg.get("frequency")) if x)
    dur = reg.get("duration")
    regimen = ""
    if given or dur or reg.get("participants"):
        bits = [f"Given {given}" if given else "Dose not named in its arms"]
        if dur:
            bits.append(f"primary endpoints at {dur}"
                        + (f" ({reg['duration_span']})" if reg.get("duration_span") else ""))
        if reg.get("participants"):
            bits.append(f'{reg["participants"]:,} treated in its controlled trials')
        regimen = f'<p class="dc-p mut">{_e(", ".join(bits))}.</p>'
    return (_h("Clinical scorecard", f'{s.get("of")} of {s.get("scored_of")} scored')
            + figs + body + regimen + more)


def _arm_tag(r: dict) -> str:
    """What an arm is when it is not plainly the drug's: the trial's control, or an arm
    whose title names none of the drug's names (an active comparator, or an arm labelled
    by a code or a letter)."""
    if r.get("arm_is_control"):
        return ' <span class="dc-tag">control arm</span>'
    if r.get("arm_is_drug") or r.get("arm_names_drug"):
        return ""
    return ' <span class="dc-tag">other arm</span>'


def _efficacy_block(c: dict) -> str:
    e = c.get("efficacy") or {}
    groups = e.get("groups") or []
    if not groups:
        return (_h("Posted results against comparators")
                + _none("No result posted against a comparator in this indication: "
                        + NO_DATA + "."))
    rows = []
    for g in groups:
        unit = g.get("unit") or "no unit"
        peers = g.get("n_assets")
        rows.append([f'<td colspan="9" class="dc-grp">{_e(_clip(g.get("title"), 110))} '
                     f'<span class="m">{_e(unit)}'
                     + (f", {peers} drugs posted on it" if peers and peers > 1 else "")
                     + "</span></td>"])
        for r in g.get("rows") or []:
            kind = r.get("reference_kind")
            comp = _num(r.get("placebo"), 2)
            rows.append([
                _nct(r.get("nct_id")), _td(r.get("phase"), muted=True),
                _td(_num(r.get("weeks")), num=True),
                f'<td>{_e(_clip(r.get("arm"), 44))}' + _arm_tag(r) + "</td>",
                _td(_num(r.get("n")) if r.get("n") else None, num=True),
                _td(_num(r.get("value"), 2), num=True),
                f'<td class="n">{_e(comp) if comp else DOT}'
                + (f' <span class="dc-tag">{_e(kind)}</span>' if kind and kind != "placebo"
                   and comp else "") + "</td>",
                _td(_num(r.get("delta"), 2), num=True),
                _td(r.get("p_value"), num=True),
            ])
    more = ""
    if (e.get("rows") or 0) > (e.get("shown") or 0):
        more = (f'<p class="dc-p mut">{e["shown"]} of {e["rows"]} posted rows; the Efficacy '
                "view lists every one.</p>")
    n = e.get("rows") or 0
    return (_h("Posted results against comparators", f'{n} arm{"s" if n != 1 else ""}')
            + _table(["trial", "phase", "wk", "arm", "n", "value", "comparator", "difference",
                      "p"], rows, "dc-eff") + more
            + '<p class="dc-p mut">The comparator is the same trial\'s placebo where it has '
              "one, else the arm the sponsor calls the control, else the other of two arms. "
              "Trials differ in population and length, so read a difference against its own "
              "comparator first.</p>")


def _safety_block(c: dict) -> str:
    r = c.get("safety")
    if not r or not r.get("trials"):
        return (_h("Safety against control")
                + _none("No adverse events posted for its trials in this indication: "
                        + NO_DATA + "."))

    def vs(key, digits=1):
        mine, ctrl = r.get(f"{key}_rate"), r.get(f"placebo_{key}_rate")
        return _pct(mine, digits), (f"against {_pct(ctrl, digits)} on control"
                                    if ctrl is not None else "no control rate")
    figs = _figs([
        _fig("serious adverse events", *vs("serious")),
        _fig("stopped for side effects", *vs("withdrawn")),
        _fig("deaths", *vs("deaths")),
        _fig("people treated", _num(r.get("participants")),
             f'{_num(r.get("placebo_participants")) or DOT} on control, {r.get("trials")} '
             f'trial{"s" if r.get("trials") != 1 else ""}'),
    ])
    events = [[_td(ev.get("term")), _td(_pct(ev.get("rate")), num=True),
               _td(_pct(ev.get("placebo_rate")), num=True, muted=True)]
              for ev in (r.get("top_events") or [])[:5]]
    table = (_table(["commonest events", "drug", "control"], events, "dc-ev")
             if events else "")
    return (_h("Safety against control", r.get("control_kind") or "")
            + figs + table)


def _trials_block(c: dict) -> str:
    trials = c.get("trials") or []
    if not trials:
        return _h("Trials linked here") + _none("No trial linked to this indication.")
    rows = [[_nct(t.get("nct_id")), _td(t.get("phase"), muted=True),
             _td((t.get("status") or "").capitalize() or None),
             _td(_num(t.get("enrollment")) if t.get("enrollment") else None, num=True),
             _td(_date(t.get("completion")), num=True),
             _td("posted" if t.get("has_results") else "none", muted=not t.get("has_results"))]
            for t in trials[:MAX_TRIALS]]
    more = (f'<p class="dc-p mut">and {len(trials) - MAX_TRIALS} more.</p>'
            if len(trials) > MAX_TRIALS else "")
    return (_h("Trials linked here",
               f'{sum(1 for t in trials if t.get("has_results"))} of {len(trials)} posted')
            + _table(["trial", "phase", "status", "enrolled", "completion", "results"], rows,
                     "dc-tr") + more
            + '<p class="dc-p mut">Completion is the primary completion date for an active '
              "trial and the completion date for a finished one.</p>")


def _readouts_block(c: dict) -> str:
    quotes = c.get("readouts") or []
    if not quotes:
        return ""
    rows = [[_td(_date(q.get("date")), num=True), _td(q.get("outcome")),
             "<td>" + (f'<a href="{_e(q["url"])}" target="_blank">' if q.get("url") else "")
             + _e(_clip(q.get("quote"), 220)) + ("</a>" if q.get("url") else "") + "</td>"]
            for q in quotes]
    return (_h("Readouts from the press", "the sentence each was read from")
            + _table(["date", "outcome", "quote"], rows, "dc-rd"))


def clinical_html(c: dict) -> str:
    return ('<div class="dc">' + _score_block(c) + _efficacy_block(c) + _safety_block(c)
            + _trials_block(c) + _readouts_block(c) + "</div>")


# --- patient pool ---------------------------------------------------------------------
def _input_value(key: str, value, unit: str | None, cur_unit: str | None = None) -> str:
    if value is None:
        return NO_DATA
    if key in ("prevalence", "incidence"):
        return f"{value:,.0f} people"
    if key in ("eligible_pct", "penetration_peak_pct", "gross_to_net_pct"):
        return _pct(value, 1)
    if key == "exus_multiple":
        return f"{value:.2f}x US"
    if key in ("list_price_per_patient", "net_price_per_patient"):
        u = (unit or cur_unit or "").strip()
        if u.startswith("mm "):
            return f"{value * 1e6:,.0f} {u[3:]}"
        return f"{value:,.6g} {u}".strip()
    return f"{value:,.4g}" + (f" {unit}" if unit else "")


def patients_html(c: dict) -> str:
    pool = c.get("pool") or {}
    ind, own = pool.get("indication") or {}, pool.get("own") or {}
    out = [_h("The indication's pool", ind.get("indication") or "")]
    if ind.get("pool"):
        out.append(_figs([
            _fig("shared pool", f'{ind["pool"] / 1e6:,.2f}mm', "patients the claimants share"),
            _fig("claimants", ind.get("claimants"), "modelled drugs drawing on it"),
            _fig("claimed at peak", _pct(ind.get("uncrowded_share")),
                 f'of the pool in {ind["peak_year"]}' if ind.get("peak_year") else ""),
            _fig("after crowding", _pct(ind.get("crowded_share")), "the pool counted once"),
        ]))
    else:
        out.append(_none("No shared patient pool on file for this indication: " + NO_DATA
                         + "." + (f' {ind["claimants"]} modelled claimants.'
                                  if ind.get("claimants") else "")))
    out.append(_h("This drug's share"))
    if own:
        share = (own.get("peak_crowded") / ind["pool"]
                 if ind.get("pool") and own.get("peak_crowded") is not None else None)
        out.append(_figs([
            _fig("peak starts a year", _num(own.get("peak_uncrowded")), "before crowding"),
            _fig("after crowding", _num(own.get("peak_crowded")), "the pool counted once"),
            _fig("kept", _pct(own.get("ratio")), "of its own forecast"),
            _fig("share of the pool", _pct(share, 1), "at its peak, after crowding"),
        ]))
        if not own.get("pooled"):
            out.append('<p class="dc-p mut">Its population is not pooled with the others\', '
                       "so crowding leaves it whole.</p>")
    else:
        out.append(_none("Not one of the pool's modelled claimants."))

    out.append(_h("The patient build", "the model's inputs, base case"))
    builds = c.get("patients") or []
    vals = {v.get("asset_id"): v for v in c.get("valuation") or [] if v}
    if not c.get("model"):
        out.append(_none("Not valued in the book, so no patient build is on file: "
                         + NO_DATA + "."))
    elif not builds or all(not b.get("indication") for b in builds):
        modes = {(vals.get(b.get("asset_id")) or {}).get("mode") for b in builds} or {None}
        other = sorted({n for b in builds for n in b.get("modelled_for") or []})
        if modes & {"marketed", "franchise"}:
            out.append(_none("Valued off its reported revenue, not built from patients, so "
                             "no prevalence, eligibility or penetration is on file."))
        elif other:
            out.append(_none("Built from patients in " + ", ".join(other)
                             + ", not in this indication."))
        else:
            out.append(_none("No patient build on file: " + NO_DATA + "."))
    for b in builds:
        if not b.get("indication"):
            continue
        price_unit = next((p.get("unit") for p in b.get("price") or []
                           if p.get("key") == "list_price_per_patient"), None)
        rows = []
        for item in (b.get("inputs") or []) + (b.get("price") or []):
            rows.append([_td(_INPUTS.get(item["key"], item["key"])),
                         _td(_input_value(item["key"], item.get("value"), item.get("unit"),
                                          price_unit), num=True),
                         _td(item.get("evidence") or "not graded", muted=not item.get("evidence")),
                         f'<td class="dc-src" title="{_e(item.get("source"))}">'
                         f'{_e(_clip(item.get("source"), 150)) or DOT}</td>'])
        if b.get("net_price") is not None and not any(
                p.get("key") == "net_price_per_patient" for p in b.get("price") or []):
            rows.append([_td("net price"),
                         _td(_input_value("net_price_per_patient", b["net_price"], price_unit),
                             num=True),
                         _td("derived", muted=True),
                         _td("list price less gross to net", muted=True)])
        crowd = b.get("crowding")
        if crowd and crowd.get("factor") is not None:
            rows.append([_td("crowding"), _td(f'{crowd["factor"]:.2f}x', num=True),
                         _td("derived", muted=True),
                         _td(f'peak penetration {_pct(crowd.get("stated"), 1)} stated, '
                             f'{_pct(crowd.get("applied"), 1)} applied', muted=True)])
        name = (vals.get(b.get("asset_id")) or {}).get("name")
        if len(builds) > 1 and name:
            out.append(f'<p class="dc-p"><b>{_e(name)}</b></p>')
        out.append(_table(["input", "value", "evidence", "source"], rows, "dc-pb"))
    return '<div class="dc">' + "".join(out) + "</div>"


# --- valuation ------------------------------------------------------------------------
def _gate_block(v: dict, cur: str) -> str:
    g = v.get("gate")
    if not g:
        why = ("A marketed product has no gate left to price." if v.get("mode") in
               ("marketed", "franchise") else "No gate priced for it: " + NO_DATA + ".")
        return _h("Next gate") + _none(why)
    trial = g.get("trial") or {}
    when = _date(g.get("date"))
    held = g.get("held") or {}
    band = g.get("band") or {}
    figs = _figs([
        _fig("chance it passes", _pct(g.get("p_gate")),
             (g.get("evidence") or {}).get("p_gate") or ""),
        _fig("now", per_share(g.get("per_share_now"), cur), f'PoS {_pct(g.get("pos_now"))}'),
        _fig("if it passes", per_share(g.get("per_share_success"), cur),
             f'PoS {_pct(g.get("pos_success"))}', cls="up"),
        _fig("if it misses", per_share(held.get("per_share") if held.get("per_share")
                                       is not None else g.get("per_share_failure"), cur),
             (f'held at PoS {_pct(held.get("pos"))}' if held.get("per_share") is not None
              else f'PoS {_pct(g.get("pos_failure"))}'), cls="down"),
    ])
    lines = [x for x in (
        f'{g.get("label") or "Gate"}'
        + (f", {when}" if when else "") + (f" ({g['date_basis']})" if g.get("date_basis") else "")
        + (f", on {trial['nct_id']}" if trial.get("nct_id") else "") + ".",
        held.get("note"),
        (f'The published band puts the value now at {per_share(band.get("per_share_low"), cur)} '
         f'to {per_share(band.get("per_share_high"), cur)} a share.'
         if band.get("per_share_low") is not None and band.get("per_share_high") is not None
         else None),
        g.get("basis"), g.get("why")) if x]
    return (_h("Next gate", "what passing or missing it is worth, a share")
            + figs + "".join(f'<p class="dc-p mut">{_e(x)}</p>' for x in lines))


def _catalyst_block(c: dict, cur: str) -> str:
    cats = c.get("catalysts") or []
    if not cats:
        return ""
    rows = []
    for r in cats:
        stake = (f'{per_share(r.get("per_share"), cur)} a share swing'
                 if r.get("priced") and r.get("per_share") is not None
                 else _clip(r.get("why") or "not priced", 90))
        rows.append([_td(_date(r.get("expected_date")), num=True),
                     _td(r.get("catalyst_type")),
                     _nct(r.get("description") if (r.get("description") or "").startswith("NCT")
                          else None),
                     _td(stake, muted=not r.get("priced"))])
    return (_h("Dated catalysts", "every indication, next first")
            + _table(["date", "type", "trial", "at stake"], rows, "dc-cat"))


def valuation_html(c: dict) -> str:
    model = c.get("model")
    cur = _cur(model)
    if not model:
        return ('<div class="dc">' + _h("Value")
                + _none("The book does not value this drug, so its value a share, probability "
                        "of success and peak are " + NO_DATA + ".")
                + _catalyst_block(c, cur) + "</div>")
    out = []
    values = [v for v in c.get("valuation") or [] if v]
    for v in values or [{}]:
        title = "Value" + (f', {v["name"]}' if len(values) > 1 and v.get("name") else "")
        if v and not v.get("ok"):
            out.append(_h(title) + _none("The forecast does not build: "
                                         + ", ".join(v.get("missing") or [NO_DATA]) + "."))
            continue
        ps = v.get("per_share") if v else model.get("per_share")
        out.append(_h(title, f"{cur}, base case"))
        out.append(_figs([
            _fig("value a share", per_share(ps, cur),
                 f'{_pct(v.get("pct_of_price"), 1)} of the share price'
                 + (f' on {_date(v["close_date"])}' if v.get("close_date") else "")
                 if v.get("pct_of_price") is not None else ""),
            _fig("probability of success", _pct(v.get("pos", model.get("pos")))),
            _fig("peak revenue", millions(v.get("peak_revenue", model.get("peak_revenue")), cur),
                 f'in {v.get("peak_year") or model.get("peak_year")}'
                 if (v.get("peak_year") or model.get("peak_year")) else ""),
            _fig("exclusivity to", v.get("loe_year"),
                 _clip(v.get("loe_basis"), 44) if v.get("loe_basis") else ""),
            _fig("launch", v.get("launch_year"), "seeded start") if v.get("launch_year")
            else _fig("discount rate", _pct(v.get("wacc"), 1), "cost of capital"),
        ]))
        out.append(_kv("Probability basis", v.get("pos_basis")))
        out.append(_kv("Exclusivity basis", v.get("loe_basis")))
        if v.get("launch_source"):
            out.append(_kv("Launch basis", v.get("launch_source")))
        out.append(_gate_block(v, cur))
    if len(values) > 1:
        out.insert(0, '<p class="dc-p">The compound is valued brand by brand; the head sums '
                      f'them to {per_share(model.get("per_share"), cur)} a share.</p>')
    out.append(_catalyst_block(c, cur))
    return '<div class="dc">' + "".join(out) + "</div>"


# --- commercial -----------------------------------------------------------------------
def commercial_html(c: dict) -> str:
    m = c.get("commercial") or {}
    out = []
    revenue = [r for r in m.get("revenue") or [] if r.get("period") in (None, "FY")]
    out.append(_h("Reported revenue", "full years, $mm"))
    if revenue:
        rows = [[_td(r.get("fiscal_year"), num=True),
                 _td(_num(r["value"] / 1e6) if r.get("value") is not None else None, num=True),
                 _td(f'{r["reported_value"] / 1e6:,.0f}mm {r["reported_unit"]}'
                     if r.get("reported_unit") and r.get("reported_unit") != "USD"
                     and r.get("reported_value") is not None else None, num=True, muted=True),
                 _td(r.get("source"), muted=True)]
                for r in revenue[-6:]]
        out.append(_table(["year", "revenue", "as filed", "source"], rows, "dc-rev"))
    else:
        out.append(_none("No product revenue on file: " + NO_DATA + "."))
    loe = m.get("loe") or {}
    out.append(_h("Exclusivity"))
    out.append(_figs([
        _fig("loss of exclusivity", _date(loe.get("loe")), loe.get("basis") or ""),
        _fig("earliest listed", loe.get("loe_earliest_year"), "first protection to lapse"),
        _fig("last listed", loe.get("last_listed_year"), "method of use patents included"),
    ]))
    access = m.get("access") or {}
    why = access.get("why_empty") or {}
    pres = access.get("prescribing") or {}
    nat = pres.get("national") or {}
    out.append(_h("Medicare Part D use", pres.get("scope_label") or "Medicare Part D only"))
    if nat:
        out.append(_figs([
            _fig("prescribers", _num(nat.get("prescribers"))),
            _fig("claims", _num(nat.get("claims"))),
            _fig("patients", _num(nat.get("beneficiaries")), "beneficiaries"),
            _fig("Part D cost", f'${nat["drug_cost"] / 1e6:,.0f}mm'
                 if nat.get("drug_cost") is not None else None, "gross of rebates, not revenue"),
        ]))
    else:
        out.append(_none(why.get("prescribing") or "No Part D prescribing on file: "
                         + NO_DATA + "."))
    form = access.get("formulary") or {}
    out.append(_h("Plan coverage", form.get("scope_label") or "Medicare Part D plans only"))
    if form.get("formularies_total"):
        out.append(_figs([
            _fig("formularies listing it", f'{form.get("formularies_listing")} of '
                 f'{form.get("formularies_total")}', "formularies, not people"),
            _fig("plans listing it", f'{_num(form.get("plans_listing"))} of '
                 f'{_num(form.get("plans_total"))}'),
            _fig("prior authorisation", _pct(form.get("pa_share")), "of listing formularies"),
            _fig("step therapy", _pct(form.get("st_share")), "of listing formularies"),
        ]))
    else:
        out.append(_none(why.get("formulary") or "No Part D formulary listing on file: "
                         + NO_DATA + "."))
    med = access.get("medicaid") or {}
    quarters = med.get("quarters") or []
    if quarters:
        rows = [[_td(f'{q.get("year")} Q{q.get("quarter")}', num=True),
                 _td(_num(q.get("prescriptions")), num=True),
                 _td(f'${q["reimbursed"] / 1e6:,.1f}mm' if q.get("reimbursed") is not None
                     else None, num=True)] for q in quarters[-4:]]
        out.append(_h("Medicaid", med.get("scope_label") or "Medicaid only, before rebates")
                   + _table(["quarter", "prescriptions", "reimbursed"], rows, "dc-mcd"))
    if access.get("attribution"):
        out.append(f'<p class="dc-p mut dc-attr">{_e(access["attribution"])}</p>')
    return '<div class="dc">' + "".join(out) + "</div>"


def card_html(c: dict) -> tuple[str, list]:
    """The head and the panes, each (label, markup). Commercial only for a marketed
    product."""
    panes = [("Clinical", clinical_html(c)), ("Patient pool", patients_html(c)),
             ("Valuation", valuation_html(c))]
    if (c.get("head") or {}).get("is_marketed"):
        panes.append(("Commercial", commercial_html(c)))
    return head_html(c), panes
