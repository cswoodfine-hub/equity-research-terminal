"""What became of each catalyst, read back from what the book already knows.

Every catalyst on file was pending, and not because none had happened. A derived readout
is deleted by ``derive_readouts`` once its date passes; a PDUFA row stays pending for
ever; and nothing read the approvals table or the announced readouts back against the
calendar. Zilganersen was approved on 2026-09-03 and its PDUFA, due 2026-09-22, was still
pending. So ``call_log`` had scored no gate, the Brier calibration had never run, and
every gate-odds regime was an assertion. This is the keystone the rest hangs on, and it
runs inside the refresh before the derivation that would otherwise delete the evidence.

Four outcomes, and the rule for each is stated rather than inferred.

**met / missed, from the approvals table.** A regulatory catalyst resolves on an
approval row for its asset dated near its window: on or after the expected date less
``EARLY_DAYS``, since the FDA acts early, and no later than the window's end plus
``LATE_DAYS``. There is no free register of refusals, so a complete response letter is
not read here; a regulatory catalyst with no approval is ``unknown`` or ``slipped``, never
missed, because the absence of a row is not a letter.

**met / missed, from the announced readouts.** ``trial_readouts`` carries a signed
result the company itself announced, with the drug named and the phase stated. A data
readout resolves on one for the same company whose phase matches the catalyst's and
whose drug names the catalyst's asset or appears in its title, dated inside the window
widened by ``EARLY_DAYS`` before and ``LATE_DAYS`` after. The result's sign is the
outcome.

**slipped.** Two mechanics, because the register's rows have two identities. A PDUFA row
is its own row, keyed on the filing that announced it, so when the FDA extends the date a
new row arrives and the old one is superseded: it is marked slipped with its successor
named. Capricor's deramiocel was due 2026-08-22 on three rows and the extension to
2026-11-22 arrived as a fourth. A derived readout is updated in place by
``derive_readouts`` when the registry moves its completion date, so a terminal status
would block its own successor; the slip is logged as an event here and the row stays
pending at its new date.

**An announcement that fits several catalysts is read, not guessed.** A readout carries
no trial id and is matched on company, drug and phase, and a company runs several
studies of one drug: Novartis had six pending Rhapsido Phase 3s, GSK two Jemperli Phase
2s, and one announcement fitted all of them. Three tiers decide it, in order. The
announcement text, which is the stored filing body or, fetched once and cached, the
press release at its own SEC URL, is read for NCT numbers: one that is a pending
catalyst resolves that catalyst, and NCTs that are none of them mean the announced trial
was never in the register, which is logged as ``elsewhere`` and resolves nothing. That is
the common case, not the edge: of the stored announcements that name an NCT, seven of
eight name one outside the register, because a trial that completed before the book
looked never became a catalyst. Failing an NCT, the registry's own description of each
sibling, its conditions, MeSH terms and primary outcome, is scored against the text,
and a sibling that alone carries the announcement's words resolves: "dMMR/MSI-H",
"rectal" and "cCR12" belong to one of GSK's three. Failing that, the announcement is
logged as ``ambiguous`` and resolves nothing.

**unknown.** A window that closed ``GRACE_DAYS`` ago with nothing found. The row is kept
with that status rather than deleted, because a readout that was due and never announced
is itself a fact about the company, and because ``derive_readouts`` only withdraws
pending rows.

Dating is the market's, not the machine's. The register's ``updated_at`` is what
``call_log`` reads as the resolution date, so it is set to the approval date or the
announcement date, and the moment the resolver ran is kept separately in the audit.
"""

from __future__ import annotations

import datetime as dt
import re

import json

import db
import pdufa
import trial_readouts
from runway import date_window

REGULATORY = ("PDUFA", "regulatory decision", "regulatory submission", "AdCom")
READOUT = ("data readout",)

EARLY_DAYS = 120     # the FDA acts early; a Phase 3 can read out ahead of completion
LATE_DAYS = 45       # an announcement follows the data by weeks, not months
GRACE_DAYS = 45      # a window closed this long ago with nothing found is unknown

_PHASE = re.compile(r"\bPhase\s*(\d)", re.I)


def _shift(day: str, days: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=days)).isoformat()


def _phase_of(title: str | None) -> int | None:
    m = _PHASE.search(title or "")
    return int(m.group(1)) if m else None


def _names(conn, asset_id) -> list[str]:
    if asset_id is None:
        return []
    row = conn.execute("SELECT brand_name, generic_name FROM assets WHERE id = ?",
                       (asset_id,)).fetchone()
    return [n.lower() for n in (row["brand_name"], row["generic_name"]) if row and n] if row else []


def _drug_matches(drug: str | None, names: list[str], title: str | None) -> bool:
    d = (drug or "").strip().lower()
    if len(d) < 4:
        return False
    hay = (title or "").lower()
    return any(d in n or n in d for n in names) or d in hay


def _record(conn, catalyst_id: int, outcome: str, source: str, evidence: str | None,
            basis: str, event_date: str | None, today: dt.date) -> bool:
    cur = conn.execute(
        """INSERT OR IGNORE INTO catalyst_resolutions
               (catalyst_id, outcome, event_date, resolved_at, source, evidence, basis, dedupe)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (catalyst_id, outcome, event_date, today.isoformat(), source, evidence, basis,
         evidence or ""))
    return cur.rowcount == 1


def _close(conn, catalyst_id: int, status: str, event_date: str | None, today: dt.date):
    conn.execute("UPDATE catalysts SET status = ?, updated_at = ? WHERE id = ?",
                 (status, event_date or today.isoformat(), catalyst_id))


def _regulatory(conn, cat, window, today) -> str | None:
    lo, hi = _shift(window[0], -EARLY_DAYS), _shift(window[1], LATE_DAYS)
    approval = conn.execute(
        """SELECT approval_date, application_number, agency FROM approvals
            WHERE asset_id = ? AND approval_date BETWEEN ? AND ?
            ORDER BY approval_date LIMIT 1""", (cat["asset_id"], lo, hi)).fetchone()
    if approval:
        ev = f"{approval['agency'] or 'FDA'} approval {approval['application_number']} on {approval['approval_date']}"
        _record(conn, cat["id"], "met", "approvals", ev,
                f"an approval row for the asset between {lo} and {hi}", approval["approval_date"], today)
        _close(conn, cat["id"], "met", approval["approval_date"], today)
        return "met"
    successor = conn.execute(
        """SELECT id, expected_date FROM catalysts
            WHERE asset_id = ? AND catalyst_type = ? AND id <> ? AND status = 'pending'
              AND expected_date > ? ORDER BY expected_date LIMIT 1""",
        (cat["asset_id"], cat["catalyst_type"], cat["id"], cat["expected_date"])).fetchone()
    if successor:
        ev = f"superseded by catalyst {successor['id']} at {successor['expected_date']}"
        _record(conn, cat["id"], "slipped", "calendar", ev,
                "a later pending row of the same kind for the same asset", None, today)
        _close(conn, cat["id"], "slipped", None, today)
        return "slipped"
    if _shift(window[1], GRACE_DAYS) < today.isoformat():
        _record(conn, cat["id"], "unknown", "calendar", None,
                f"no approval row and no successor {GRACE_DAYS} days after the window closed",
                None, today)
        _close(conn, cat["id"], "unknown", None, today)
        return "unknown"
    return None


_NCT = re.compile(r"NCT\d{8}")
_WORD = re.compile(r"[a-z][a-z0-9/-]{3,}")
# Words every trial description carries, which decide nothing between siblings.
_STOP = {"study", "trial", "phase", "participants", "patients", "adult", "adults",
         "efficacy", "safety", "tolerability", "evaluate", "assess", "versus", "with",
         "treatment", "placebo", "randomized", "none", "number", "neoplasms", "diseases",
         "disease", "cancer", "carcinoma", "compared", "investigate", "double-blind"}
MIN_SCORE = 2.0             # a sibling must carry this much weighted evidence
LEAD_RATIO = 2.0            # and twice the runner-up's, or the words did not decide it
RARE_DF = 40                # a word in this many trials or fewer counts in full
COMMON_WEIGHT = 0.25        # a word in more than that counts a quarter


def announcement_text(conn, readout: dict, fetch: bool = True, get=None) -> str:
    """The announcement's own words: its quote, plus the filing body stored for it or,
    fetched once and cached under section 'readout', the press release at its URL."""
    parts = [readout.get("quote") or ""]
    body = conn.execute(
        "SELECT text FROM filing_sections WHERE accession = ? ORDER BY section = 'readout' DESC",
        (readout["accession"],)).fetchone()
    if body and body["text"]:
        parts.append(body["text"])
    elif fetch and readout.get("source_url"):
        try:
            form = conn.execute("SELECT form_type FROM filings WHERE accession = ?",
                                (readout["accession"],)).fetchone()
            text = trial_readouts.readout_text(
                {"url": readout["source_url"],
                 "form_type": form["form_type"] if form else None},
                get or trial_readouts._get)
        except Exception:                                      # noqa: BLE001
            text = ""
        if text:
            conn.execute(
                """INSERT OR IGNORE INTO filing_sections
                       (company_id, accession, form_type, filed_date, section, char_count, text)
                   VALUES (?, ?, ?, ?, 'readout', ?, ?)""",
                (readout.get("company_id"), readout["accession"],
                 form["form_type"] if form else None, readout.get("event_date"),
                 len(text), text))
            parts.append(text)
    return " ".join(parts)


def trial_tokens(trial) -> set:
    """The words that describe one trial and might distinguish it from its siblings."""
    if not trial:
        return set()
    text = " ".join(str(trial[k] or "") for k in ("title", "conditions", "primary_outcome")
                    if k in trial.keys())
    try:
        mesh = json.loads(trial["mesh_terms"] or "{}") if "mesh_terms" in trial.keys() else {}
        text += " " + " ".join(m.get("term", "") for m in (mesh.get("meshes") or []))
    except (ValueError, TypeError, AttributeError):
        pass
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def _rare(conn, words: set) -> set:
    """The words that appear in RARE_DF trials or fewer across the whole register.

    "rectal" and "dmmr/msi-h" name a study; "advanced", "survival" and "review" are in
    hundreds of them and decide nothing, so a hit on one of those is worth a quarter."""
    rare = set()
    for w in words:
        n = conn.execute(
            "SELECT COUNT(*) FROM trials WHERE lower(title || ' ' || COALESCE(conditions, '')"
            " || ' ' || COALESCE(primary_outcome, '')) LIKE ?", (f"%{w}%",)).fetchone()[0]
        if n <= RARE_DF:
            rare.add(w)
    return rare


def disambiguate(conn, siblings: list, text: str) -> tuple:
    """(winner catalyst id or None, how, evidence) for an announcement fitting several.

    NCT first: a named trial that is a pending sibling wins outright; named trials that
    are none of the siblings mean the announcement is about something else. Then the
    registry's words. A word two siblings share cannot tell them apart, so any word in
    more than one sibling is dropped, not only the words in all of them: GSK's rectal
    and head-and-neck studies both say "locally advanced" and "dostarlimab", and keeping
    those let the runner-up score eight against the winner's twelve. What is left is
    weighted by rarity across the register, and a sibling must reach MIN_SCORE and
    LEAD_RATIO times the runner-up, or nothing is decided.
    """
    low = text.lower()
    named = set(_NCT.findall(text))
    if named:
        hits = [s for s in siblings if s["nct"] in named]
        if len(hits) == 1:
            return hits[0]["id"], "nct", f"the announcement names {hits[0]['nct']}"
        if not hits:
            return None, "elsewhere", (f"the announcement names {', '.join(sorted(named))}, "
                                       f"none of them a pending catalyst")
        return None, "ambiguous", f"the announcement names {len(hits)} pending catalysts"
    counts: dict = {}
    for s in siblings:
        for w in s["tokens"]:
            counts[w] = counts.get(w, 0) + 1
    shared = {w for w, n in counts.items() if n > 1}
    candidates = {w for s in siblings for w in s["tokens"] - shared if w in low}
    rare = _rare(conn, candidates) if candidates else set()
    scored = []
    for s in siblings:
        found = sorted(w for w in s["tokens"] - shared if w in low)
        weight = sum(1.0 if w in rare else COMMON_WEIGHT for w in found)
        scored.append((weight, s, [w for w in found if w in rare] + [w for w in found if w not in rare]))
    scored.sort(key=lambda x: -x[0])
    top = scored[0] if scored else None
    runner = scored[1][0] if len(scored) > 1 else 0.0
    if top and top[0] >= MIN_SCORE and top[0] >= LEAD_RATIO * max(runner, COMMON_WEIGHT):
        return top[1]["id"], "tokens", (f"the announcement carries {', '.join(top[2][:6])}, "
                                        f"which of the {len(siblings)} fit only {top[1]['nct']}")
    return None, "ambiguous", (f"the announcement's words fit {len(siblings)} pending "
                               f"catalysts and single out none")


def _sibling_rows(conn, cat, phase) -> list:
    out = []
    for r in conn.execute(
            """SELECT c.id, c.description AS nct, c.status, t.title, t.conditions,
                      t.primary_outcome, t.mesh_terms
                 FROM catalysts c LEFT JOIN trials t ON t.nct_id = c.description
                WHERE c.company_id = ? AND c.asset_id IS ? AND c.catalyst_type = 'data readout'
                  AND c.status = 'pending'""", (cat["company_id"], cat["asset_id"])):
        if _phase_of(r["title"] if r["title"] else None) in (phase, None):
            row = dict(r)
            row["tokens"] = trial_tokens(r)
            out.append(row)
    return out


def _siblings(conn, cat, phase) -> int:
    """How many pending catalysts the company has for the same asset at the same phase.

    A readout is matched on company, drug and phase and carries no trial id, so where
    the company runs two Phase 2 studies of one drug the announcement fits both. GSK
    had three pending Jemperli Phase 2 readouts and one announced result. Resolving all
    three on it would be wrong twice; resolving one at random would be wrong in a way no
    one could see. So an announcement that fits more than one pending catalyst resolves
    none, and the ambiguity is left for the registry move or the grace period.
    """
    n = 0
    for r in conn.execute(
            """SELECT title FROM catalysts WHERE company_id = ? AND asset_id IS ?
                  AND catalyst_type = 'data readout' AND status = 'pending'""",
            (cat["company_id"], cat["asset_id"])):
        if _phase_of(r["title"]) == phase:
            n += 1
    return n


def _readout(conn, cat, window, today, fetch=True, get=None) -> str | None:
    lo, hi = _shift(window[0], -EARLY_DAYS), _shift(window[1], LATE_DAYS)
    phase = _phase_of(cat["title"])
    names = _names(conn, cat["asset_id"])
    ambiguous = cat["asset_id"] is not None and _siblings(conn, cat, phase) > 1
    for r in conn.execute(
            """SELECT accession, drug, phase, outcome, event_date, quote, source_url
                 FROM trial_readouts
                WHERE company_id = ? AND outcome IN ('positive', 'negative')
                  AND event_date BETWEEN ? AND ? ORDER BY event_date""",
            (cat["company_id"], lo, hi)):
        if phase is not None and r["phase"] is not None and int(r["phase"]) != phase:
            continue
        if not _drug_matches(r["drug"], names, cat["title"]):
            continue
        if ambiguous:
            already = conn.execute(
                "SELECT 1 FROM catalyst_resolutions WHERE evidence LIKE ? LIMIT 1",
                (f"readout {r['accession']}%",)).fetchone()
            if already:
                return None                     # this announcement was read once already
            siblings = _sibling_rows(conn, cat, phase)
            text = announcement_text(conn, dict(r, company_id=cat["company_id"]), fetch, get)
            winner, how, why = disambiguate(conn, siblings, text)
            if winner is None:
                _record(conn, cat["id"], how, "trial_readouts",
                        f"readout {r['accession']}: {why}",
                        "an announced result read against the pending catalysts it could "
                        "fit, by the trial numbers it names and then by the registry's own "
                        "words for each", r["event_date"], today)
                return None
            outcome = "met" if r["outcome"] == "positive" else "missed"
            _record(conn, winner, outcome, "trial_readouts",
                    f"readout {r['accession']}: {r['drug']} Phase {r['phase']} {r['outcome']} "
                    f"on {r['event_date']}; {why}",
                    "one of several pending catalysts, singled out by " + how,
                    r["event_date"], today)
            _close(conn, winner, outcome, r["event_date"], today)
            # The outcome is the winner's whichever sibling's turn found it: the loop
            # skips a row closed earlier in the run, so it is counted exactly once here.
            return outcome
        outcome = "met" if r["outcome"] == "positive" else "missed"
        ev = f"readout {r['accession']}: {r['drug']} Phase {r['phase']} {r['outcome']} on {r['event_date']}"
        _record(conn, cat["id"], outcome, "trial_readouts", ev,
                "an announced result for the same company, phase and drug inside the window",
                r["event_date"], today)
        _close(conn, cat["id"], outcome, r["event_date"], today)
        return outcome
    # The registry moved the date: an event on a row that stays pending.
    if cat["description"] and str(cat["description"]).startswith("NCT"):
        trial = conn.execute(
            "SELECT primary_completion_date, overall_status FROM trials WHERE nct_id = ?",
            (cat["description"],)).fetchone()
        due = trial["primary_completion_date"] if trial else None
        if due and str(due)[:10] > window[1]:
            ev = f"registry primary completion moved to {str(due)[:10]}"
            if _record(conn, cat["id"], "slipped", "registry", ev,
                       "the trial's completion date now sits past the catalyst's window", None, today):
                return "slipped"
            return None
    if _shift(window[1], GRACE_DAYS) < today.isoformat():
        _record(conn, cat["id"], "unknown", "calendar", None,
                f"no announced result and no registry move {GRACE_DAYS} days after the window closed",
                None, today)
        _close(conn, cat["id"], "unknown", None, today)
        return "unknown"
    return None


def resolve(db_path=None, today: dt.date | None = None, fetch: bool = True, get=None) -> dict:
    """Resolve every pending catalyst whose window has closed. Returns counts by outcome."""
    today = today or dt.date.today()
    counts = {"met": 0, "missed": 0, "slipped": 0, "unknown": 0, "open": 0}
    # ``fetch`` lets the resolver read an announcement at its SEC URL where no body is
    # stored, once, and cache it; off in tests and anywhere a network call is unwanted.
    conn = db.get_connection(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT id, company_id, asset_id, catalyst_type, expected_date, title,
                      description FROM catalysts
                WHERE status = 'pending' AND expected_date IS NOT NULL
                ORDER BY expected_date""")]
        for cat in rows:
            # A sibling resolved by an earlier announcement this run is closed already.
            if conn.execute("SELECT status FROM catalysts WHERE id = ?",
                            (cat["id"],)).fetchone()["status"] != "pending":
                continue
            window = date_window(cat["expected_date"])
            if not window or window[1] >= today.isoformat():
                continue
            if cat["catalyst_type"] in REGULATORY:
                got = _regulatory(conn, cat, window, today)
            elif cat["catalyst_type"] in READOUT:
                got = _readout(conn, cat, window, today, fetch, get)
            else:
                got = None
            counts[got or "open"] += 1
        conn.commit()
    finally:
        conn.close()
    return counts


def ledger(db_path=None, limit: int = 200) -> list[dict]:
    """The resolutions, newest first, each joined to its catalyst and company."""
    conn = db.get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute(
            """SELECT r.*, c.catalyst_type, c.expected_date, c.title, c.status, co.ticker
                 FROM catalyst_resolutions r
                 JOIN catalysts c ON c.id = r.catalyst_id
                 JOIN companies co ON co.id = c.company_id
                ORDER BY r.resolved_at DESC, r.id DESC LIMIT ?""", (limit,))]
    finally:
        conn.close()
