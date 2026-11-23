"""A posted readout, tied to its study and recorded, or held and said why.

The block this replaces offered "readouts that may have landed": a headline that named
an asset and used a result word was shown against every priced gate on that asset. On
2026-11-22 it held 17 proposals from four headlines and none decided the gate it stood
against. Merck's TroFuse-015 result is a gastroesophageal study and was shown against
the lung study; an Imfinzi approval in bladder cancer against an oesophageal study and a
Phase 2; the Hibsago approval nine times against a Phase 2 the approval does not rest
on; a Phase 1 maintenance study of VK2735 five times against the Phase 3. A company
runs several studies of one drug, so an asset's name decides nothing.

Three rules, and nothing is recorded unless all three hold.

**The study is named.** A report is tied to a study by its registry number in the text,
or by the study's own name: the registry's acronym (``trials.acronym``), the name in
brackets at the end of its registry title, or a name a company uses that the registry
does not carry (``data/study_names.csv``, each with its source). The study has to be
the reporting company's own. A name is used only where it cannot be a word of the
sentence: one with a digit or a hyphen (TroFuse-015, TOPAZ-1), one in capitals or mixed
case (VOLGA, lidERA) matched as written, and never a capitalised word in a headline
set in capitals. "FENhance" does not match "FENhance 2".

**The outcome is stated.** In a headline, only the words that say the primary endpoint
was met or was not: "met its primary endpoint", "did not meet the primary endpoint".
"Positive topline results" is a company's adjective, and a discontinuation has many
causes, so neither is read as an outcome. In a filing or a release body the outcome is
the one the existing extractors labelled (``trial_readouts``, ``press_readouts``), which
quote the result sentence and are refused unless that sentence is in the text; this
module calls no model and works with no key.

**The date and the page are the source's.** The day the release carries, its URL and the
sentence verbatim.

A report that passes is recorded through the path a hand-entered result uses
(``announced_readouts.record``): the study's readout is closed met or missed on the
announcement day and the resolution goes to the ledger, marked automated. Where that
readout is the gate the model prices, the model is stepped as the one-click resolve
steps it (``forecast_view.resolve_catalyst``), which snapshots the forecast before and
after. Nothing a refresh recomputes is written: a derived gate re-places itself from the
closed readout every time it is read, and ``derive_readouts`` never touches a row that
is met or missed, so there is nothing for the morning to undo. A row then goes to the
change feed saying the readout landed and what it did to the gate.

Everything else is held, never guessed, in ``readout_reports`` with its reason:

  ``outcome_not_read``   the study is certain and no rule reads the outcome;
  ``not_tied``           a result is reported and names no study the book holds;
  ``awaiting_register``  an approval is reported in the use a decision on file waits on,
                         which resolves when openFDA lists it;
  ``on_file``            an approval the approvals table already carries;
  ``no_gate``            an approval in a use no decision on the book is waiting on: a
                         label widened for a marketed product, which decides no gate;
  ``set_aside``          a person has read it and ruled it decides no gate
                         (``data/set_aside_reports.csv``, with the reason and source).

The first three are shown on the Catalysts tab as reported; the last three are kept and
not shown, so a report settled today is not offered again tomorrow. A headline that
names no asset with a readout still open is not a report about this book and is not
kept at all, and neither is a result told again at a congress or in a journal.
"""

from __future__ import annotations

import csv
import datetime as dt
import re

import announced_readouts
import auto_resolve
import db

DATA = db.BACKEND_DIR.parent / "data"
NAMES_CSV = DATA / "study_names.csv"
SET_ASIDE_CSV = DATA / "set_aside_reports.csv"

DAYS = 45                 # how far back a press report is read, and the block shows
FILING_DAYS = 730         # how far back a labelled filing or release is tied to a study
FEED_DAYS = 45            # a readout older than this is recorded, not announced as new
APPROVAL_DAYS = 60        # an approval row this close to an approval headline is the same event
STEP_THE_MODEL = True     # step the priced gate as the one-click resolve does

SHOWN = ("outcome_not_read", "not_tied", "awaiting_register")
RULINGS = {
    "other_study": "it reports a study that is not the one any gate on the book rests on",
    "label_expansion": "it is an approval that widens a marketed product's label, and no "
                       "gate on the book is waiting on that use",
    "decides_no_gate": "it decides no gate the book carries",
}

_NCT = re.compile(r"NCT\d{8}")
_CTGOV = "https://clinicaltrials.gov/study/"

# The primary endpoint, met or not, in so many words. Tested in this order: "did not meet
# its primary endpoint" contains "meet its primary".
MISSED_WORDS = re.compile(
    r"\b(?:did not|does not|failed to|fails to) (?:meet|achieve|reach)\b[^.;]{0,40}?\bprimary\b"
    r"|\bmiss(?:es|ed) (?:its |the |both |all )?(?:co-?)?primary\b"
    r"|\bprimary (?:endpoint|end ?point|objective|outcome)s?\b[^.;]{0,30}?\b(?:was |were )?not (?:met|achieved)\b",
    re.I)
MET_WORDS = re.compile(
    r"\b(?:meets?|met|achiev(?:es|ed)) (?:its |the |all |both |dual |each )*(?:co-?)?primary\b"
    r"|\bprimary (?:endpoint|end ?point|objective|outcome)s?\b[^.;]{0,30}?\b(?:was |were )?(?:met|achieved)\b",
    re.I)
# A headline that reports a result without stating the endpoint's outcome.
RESULT_WORDS = re.compile(
    r"\btop-?line\b|\bresults?\b|\bprimary (?:endpoint|end ?point)\b"
    r"|\bstatistically significant\b|\bsignificantly (?:improv|reduc|prolong|increas)\w*"
    r"|\b(?:phase|ph) ?(?:3|iii|2|ii)\b[^.]{0,40}\bdata\b", re.I)
APPROVED_WORDS = re.compile(r"\bapprov(?:es|ed|al)\b|\bis now approved\b", re.I)
# An FDA approval that has happened: not one sought, and not a European opinion.
US_APPROVED = re.compile(
    r"\bapproved in the US\b|\bFDA approv(?:es|ed|al)\b"
    r"|\bapprov(?:ed|al) by the (?:US |U\.S\. )?FDA\b|\breceives? (?:final )?FDA approval\b"
    r"|\bFood and Drug Administration approves\b", re.I)
NOT_YET = re.compile(r"\bseeks?\b|\bsubmit\w*|\brecommend\w*|\bCHMP\b|\bfiles? for\b", re.I)
# A result told again: a paper, a congress, a longer follow-up of a study already read.
RETOLD = re.compile(
    r"\bpresent(?:s|ed|ation)?\b|\bpublish(?:es|ed)\b|\bpublication\b|\blate-breaking\b"
    r"|\b(?:two|three|four|five|\d+)-year\b|\blong-term\b|\bfull (?:results|data)\b", re.I)


def outcome_of(text: str | None) -> tuple:
    """(met | missed | None, the words that said so). A headline announcing an event to
    come states no outcome, whatever else it contains."""
    text = (text or "").strip()
    if not text or auto_resolve.ANNOUNCEMENT.search(text):
        return None, None
    hit = MISSED_WORDS.search(text)
    if hit:
        return "missed", hit.group(0)
    hit = MET_WORDS.search(text)
    if hit:
        return "met", hit.group(0)
    return None, None


# --------------------------------------------------------------------------- study names
_TRAILING = re.compile(r"\(([A-Za-z][A-Za-z0-9][A-Za-z0-9 \-]{1,22})\)\s*$")


def usable(name: str) -> bool:
    """Whether a study's name can tie a sentence to it without being a word of it."""
    name = (name or "").strip()
    if len(name) < 4 or not re.search(r"[A-Za-z]", name):
        return False
    if re.search(r"[\d\-]", name):
        return True
    letters = re.sub(r"[^A-Za-z]", "", name)
    # VOLGA, ASCENT: capitals throughout. lidERA, FENhance: capitals inside the word.
    return len(letters) >= 5 and (letters.isupper() or bool(re.search(r"[a-z][A-Z]", name)))


def _pattern(name: str) -> re.Pattern:
    """The name as a token of its own: not inside a longer name, and where it carries no
    number, not followed by one ("FENhance" is not "FENhance 2")."""
    tail = r"(?![\w])" if name[-1].isdigit() else r"(?![\w]|[ \-]?\d)"
    flags = re.I if re.search(r"[\d\-]", name) else 0
    return re.compile(r"(?<![\w\-])" + re.escape(name) + tail, flags)


def curated_names(path=None) -> dict:
    """{nct_id: [names]} from data/study_names.csv: names a company uses for a study that
    the registry does not carry as its acronym."""
    out: dict = {}
    try:
        with open(path or NAMES_CSV, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(line for line in handle if not line.startswith("#")):
                nct, name = (row.get("nct_id") or "").strip(), (row.get("name") or "").strip()
                if _NCT.fullmatch(nct) and name:
                    out.setdefault(nct, []).append(name)
    except FileNotFoundError:
        pass
    return out


def names_of(trial: dict, curated: dict | None = None) -> list:
    """The names a release could use for one study, usable ones only, longest first."""
    found = [trial.get("acronym") or ""]
    hit = _TRAILING.search(trial.get("title") or "")
    if hit:
        found.append(hit.group(1))
    found += (curated or {}).get(trial.get("nct_id"), [])
    seen, out = set(), []
    for name in found:
        name = name.strip()
        if usable(name) and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return sorted(out, key=len, reverse=True)


def fill_names(db_path=None, get=None, batch: int = 50, pause: float = 0.4) -> dict:
    """Ask the registry for the acronym of every study with a readout on the calendar
    that has none stored. The pipeline fetch carries the acronym for a study it reads,
    but it reads live studies by sponsor, and a study that has completed is never read
    that way again. A study the registry gives no acronym is stored as '' so it is asked
    once. Soft on failure: a batch that does not answer is left for the next run."""
    import time

    import ctgov
    from fetchers.trial_results import get_json
    get = get or get_json
    conn = db.get_connection(db_path)
    try:
        ids = [r["nct_id"] for r in conn.execute(
            f"""SELECT DISTINCT t.nct_id FROM trials t JOIN catalysts cat
                  ON cat.source_url = '{_CTGOV}' || t.nct_id
                 WHERE cat.catalyst_type = 'data readout' AND t.acronym IS NULL
                 ORDER BY t.nct_id""")]
    finally:
        conn.close()
    asked = named_ = 0
    errors: list = []
    for start in range(0, len(ids), batch):
        chunk = ids[start:start + batch]
        try:
            payload = get(ctgov.STUDIES_URL, {
                "filter.ids": ",".join(chunk), "pageSize": batch,
                "fields": "protocolSection.identificationModule.nctId|"
                          "protocolSection.identificationModule.acronym"})
        except Exception as exc:                                    # noqa: BLE001
            errors.append(f"{chunk[0]}..: {exc}")
            continue
        got = {}
        for study in payload.get("studies") or []:
            ident = (study.get("protocolSection") or {}).get("identificationModule") or {}
            if ident.get("nctId"):
                got[ident["nctId"]] = (ident.get("acronym") or "").strip()
        conn = db.get_connection(db_path)
        try:
            for nct in chunk:
                if nct in got:
                    conn.execute("UPDATE trials SET acronym = ? WHERE nct_id = ?"
                                 " AND acronym IS NULL", (got[nct], nct))
                    asked += 1
                    named_ += bool(got[nct])
            conn.commit()
        finally:
            conn.close()
        if pause:
            time.sleep(pause)
    return {"asked": asked, "named": named_, "errors": errors}


def studies(conn, curated: dict | None = None) -> list:
    """Every study with a derived readout on the calendar: its company, its asset, the
    names it goes by and its readout rows."""
    curated = curated_names() if curated is None else curated
    out: dict = {}
    for r in conn.execute(
            f"""SELECT t.nct_id, t.title, t.acronym, t.phase, t.asset_id,
                       cat.company_id, co.ticker, cat.id AS catalyst_id,
                       COALESCE(cat.status, 'pending') AS status,
                       COALESCE(a.brand_name, a.generic_name, a.internal_code) AS asset
                  FROM catalysts cat
                  JOIN trials t ON cat.source_url = '{_CTGOV}' || t.nct_id
                  JOIN companies co ON co.id = cat.company_id
                  LEFT JOIN assets a ON a.id = COALESCE(t.asset_id, cat.asset_id)
                 WHERE cat.catalyst_type = 'data readout' AND cat.is_curated = 0
                 ORDER BY cat.id"""):
        s = out.setdefault(r["nct_id"], {
            "nct_id": r["nct_id"], "title": r["title"], "acronym": r["acronym"],
            "phase": r["phase"], "asset_id": r["asset_id"], "asset": r["asset"],
            "company_id": r["company_id"], "ticker": r["ticker"], "catalysts": []})
        s["catalysts"].append({"id": r["catalyst_id"], "status": r["status"]})
    for s in out.values():
        s["names"] = names_of(s, curated)
    return list(out.values())


def named(text: str | None, company_id, index: list) -> list:
    """The company's studies a sentence names, each with how: (study, "registry number" |
    "study name"). A name two of the company's studies share ties to neither."""
    text = text or ""
    shouting = text.upper() == text and bool(re.search(r"[A-Z]{4}", text))
    numbers = set(_NCT.findall(text))
    out, by_name = [], {}
    for s in index:
        if s["company_id"] != company_id:
            continue
        if s["nct_id"] in numbers:
            out.append((s, "registry number"))
            continue
        for name in s["names"]:
            if shouting and not re.search(r"[\d\-]", name):
                continue
            if _pattern(name).search(text):
                by_name.setdefault(name.lower(), []).append(s)
                break
    taken = {s["nct_id"] for s, _ in out}
    for hits in by_name.values():
        if len(hits) == 1 and hits[0]["nct_id"] not in taken:
            out.append((hits[0], "study name"))
    return out


def label(study: dict) -> str:
    """ "TroFuse-015 (NCT06356311)", or the number alone where the study has no name."""
    return f"{study['names'][0]} ({study['nct_id']})" if study.get("names") else study["nct_id"]


# ------------------------------------------------------------------------------ sources
def _assets(conn) -> dict:
    """{company_id: [(asset_id, shown name, [names])]} for assets with a readout that is
    still open, the only ones a report could be about a gate on."""
    out: dict = {}
    for r in conn.execute(
            f"""SELECT DISTINCT cat.company_id, a.id, a.brand_name, a.generic_name,
                       a.internal_code FROM catalysts cat
                  LEFT JOIN trials t ON cat.source_url = '{_CTGOV}' || t.nct_id
                  JOIN assets a ON a.id = COALESCE(t.asset_id, cat.asset_id)
                 WHERE cat.catalyst_type = 'data readout'
                   AND COALESCE(cat.status, 'pending') IN ('pending', 'unknown')"""):
        names = [n.strip() for n in (r["brand_name"], r["generic_name"], r["internal_code"])
                 if n and len(n.strip()) >= 4]
        if names:
            out.setdefault(r["company_id"], []).append((r["id"], names[0], names))
    return out


def _asset_named(text: str, assets: list):
    for asset_id, shown, names in assets or []:
        if any(re.search(rf"(?<![\w\-]){re.escape(n)}(?![\w\-])", text, re.I) for n in names):
            return asset_id, shown
    return None, None


def press_items(conn, since: str) -> list:
    """Press headlines of the kinds that can carry a result or an approval, one a release
    (the same release is a change row on several days), with the day the release carries."""
    seen, out = set(), []
    for item in sorted(auto_resolve.recent_press(conn, None, since),
                       key=lambda i: str(i["detected_at"])):
        key = item["url"] or item["headline"]
        if not key or key in seen:
            continue
        seen.add(key)
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                               (item["ticker"],)).fetchone()
        if company is None:
            continue
        news = conn.execute("SELECT published_at FROM news WHERE url = ?",
                            (item["url"],)).fetchone() if item["url"] else None
        out.append({**item, "company_id": company["id"],
                    "published": str((news["published_at"] if news and news["published_at"]
                                      else item["detected_at"]) or "")[:10]})
    return out


def labelled_rows(conn, since: str) -> list:
    """Results the extractors labelled from a filing or a release body, with the two
    places a study's name ties the result to it: the quoted result sentence and the
    document's own title. Not the body: a release that reports one study goes on to
    list the programme's others (Saphnelo's named five), and a name down there says
    only that the study exists."""
    out = []
    for r in conn.execute(
            """SELECT accession, company_id, outcome, event_date, quote, source_url, source
                 FROM trial_readouts
                WHERE outcome IN ('positive', 'negative') AND event_date >= ?
                  AND COALESCE(source, '') <> 'registry' ORDER BY event_date""", (since,)):
        if str(r["accession"]).startswith("news:"):
            head = conn.execute("SELECT title FROM news WHERE id = ?",
                                (str(r["accession"])[5:],)).fetchone()
        else:
            head = conn.execute("SELECT title FROM filings WHERE accession = ?",
                                (r["accession"],)).fetchone()
        out.append({**dict(r), "parts": [r["quote"] or "", (head["title"] if head else "") or ""]})
    return out


def set_aside(path=None) -> dict:
    """{url: {"ruling", "reason", "source_url", "nct_id"}} from data/set_aside_reports.csv."""
    out = {}
    try:
        with open(path or SET_ASIDE_CSV, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(line for line in handle if not line.startswith("#")):
                row = {k: (v or "").strip() for k, v in row.items()}
                if row.get("url") and row.get("ruling") in RULINGS and row.get("reason"):
                    out[row["url"]] = row
    except FileNotFoundError:
        pass
    return out


# ----------------------------------------------------------------------------- recording
def _report(conn, today: dt.date, **f) -> None:
    """Write one report, or move the one on file to what the sources now say. A report a
    person set aside keeps that ruling for as long as the file holds it."""
    f.setdefault("nct_id", None)
    dedupe = f"{f['source_key']}|{f['nct_id'] or ''}"
    cols = ("source_key", "company_id", "source", "kind", "url", "published_at", "sentence",
            "asset_id", "nct_id", "tied_by", "outcome", "matched_words", "state", "reason",
            "catalyst_id", "effect")
    row = {c: f.get(c) for c in cols}
    have = conn.execute("SELECT id, effect, state FROM readout_reports WHERE dedupe = ?",
                        (dedupe,)).fetchone()
    if have is not None and have["state"] == "landed" and row["state"] != "landed":
        return                          # recorded already; the sources still read as held
    if have is None:
        conn.execute(
            f"INSERT INTO readout_reports ({', '.join(cols)}, first_seen, updated_at, dedupe)"
            f" VALUES ({', '.join('?' * len(cols))}, ?, ?, ?)",
            (*row.values(), today.isoformat(), today.isoformat(), dedupe))
        return
    # What landing did is said once, on the run that landed it.
    row["effect"] = row["effect"] or have["effect"]
    sets = ", ".join(f"{c} = ?" for c in cols)
    conn.execute(f"UPDATE readout_reports SET {sets}, updated_at = ? WHERE id = ?",
                 (*row.values(), today.isoformat(), have["id"]))


def _pct(v) -> str:
    return f"{v:.0%}" if isinstance(v, (int, float)) else "no free data"


def _effect(result: dict) -> str:
    """What stepping the gate did, from the resolve's own return."""
    if result.get("route") == "stated legs":
        return (f"the stated odds were stepped from {_pct(result.get('pos_before'))} to "
                f"{_pct(result.get('pos_applied'))}")
    tail = (" and the line is held while other Phase 3 studies run"
            if result.get("held") else "")
    return (f"the gate's odds moved from {_pct(result.get('pos_before'))} to "
            f"{_pct(result.get('pos_applied'))}{tail}")


def land(db_path, study: dict, outcome: str, event_date: str, sentence: str, url: str | None,
         source: str, today: dt.date, step: bool | None = None, automated: bool = True) -> dict:
    """Record one study's outcome. {"state", "catalyst_id", "effect", "new"}.

    The study's readout is closed on the announcement day and the ledger says where the
    result was read. Where the readout is the gate the model prices, the model is stepped
    first, by the resolve the terminal's own button calls, which snapshots before and
    after. A readout already closed the same way is left as it is; one closed the other
    way is not overturned from a rule, and is held for a person."""
    step = STEP_THE_MODEL if step is None else step
    evidence = f"{url}: {sentence}" if url else sentence
    basis = ("a result the company posted, tied to this study by its name or registry "
             "number, with the outcome stated in the source's own words")
    out = {"state": "landed", "catalyst_id": None, "effect": None, "new": False}
    for cat in study["catalysts"]:
        out["catalyst_id"] = cat["id"]
        if cat["status"] == outcome:
            out["effect"] = out["effect"] or "already on file with this outcome"
            continue
        if cat["status"] in announced_readouts.OUTCOMES:
            return {**out, "state": "outcome_not_read",
                    "effect": None,
                    "reason": f"the book holds {study['nct_id']} as {cat['status']} and this "
                              f"report reads as {outcome}; a rule does not overturn a "
                              f"resolution on file"}
        stepped = None
        if step:
            stepped = _step(db_path, study["ticker"], cat, outcome)
        conn = db.get_connection(db_path)
        try:
            announced_readouts.record(
                conn, cat["id"], outcome, event_date, evidence,
                basis if automated else announced_readouts.BASIS,
                f"posted:{source}" if automated else announced_readouts.SOURCE,
                automated=automated, today=today)
            conn.commit()
        finally:
            conn.close()
        cat["status"] = outcome
        out["new"] = True
        out["effect"] = (_effect(stepped) if isinstance(stepped, dict) else
                         f"recorded against the study; no priced gate moved: {stepped}"
                         if stepped else "recorded against the study")
    return out


def _step(db_path, ticker: str, cat: dict, outcome: str):
    """Step the model if this readout is the gate it prices: the resolve's own result, or
    the reason it would not take this catalyst, in its words."""
    import forecast_view
    if cat["status"] == "unknown":
        # A window that closed with nothing found; the result has now been found.
        conn = db.get_connection(db_path)
        try:
            conn.execute("UPDATE catalysts SET status = 'pending' WHERE id = ?", (cat["id"],))
            conn.commit()
        finally:
            conn.close()
    try:
        return forecast_view.resolve_catalyst(db_path, ticker, cat["id"], outcome) \
            or "the catalyst is on no modelled line"
    except ValueError as exc:
        return str(exc)
    except Exception as exc:                                        # noqa: BLE001
        # The forecast did not build. The fact is still recorded; the model is not moved.
        return f"the forecast could not be read ({type(exc).__name__})"


def _feed(conn, study: dict, outcome: str, event_date: str, effect: str | None,
          today: dt.date, refresh_run_id=None) -> None:
    """One row in the change feed: the readout landed, and what it did to the gate."""
    if event_date < (today - dt.timedelta(days=FEED_DAYS)).isoformat():
        return
    said = "met its primary endpoint" if outcome == "met" else "did not meet its primary endpoint"
    text = (f"{study.get('asset') or 'A study'}: {label(study)} {said}, announced "
            f"{event_date}" + (f"; {effect}" if effect else "") + ".")
    key = f"{study['ticker']}|landed:{study['nct_id']}"
    if conn.execute("SELECT 1 FROM changes WHERE entity_type = 'company' AND entity_key = ?"
                    " AND change_type = 'readout_landed'", (key,)).fetchone():
        return
    conn.execute(
        "INSERT INTO changes (entity_type, entity_key, field, old_value, new_value,"
        " change_type, significance, refresh_run_id)"
        " VALUES ('company', ?, 'readout', 'pending', ?, 'readout_landed', 'high', ?)",
        (key, text, refresh_run_id))


PRIMARY_SHOWN = 3


def _number(value) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def posted_primary(conn, nct_id: str) -> str | None:
    """The primary endpoint as the registry posts it, in one line: its name, the estimate
    with its interval, and the p-value, each as posted.

    A posting used to arrive here as "results posted" and nothing else, which told a
    reader that a study had reported and left them to open the registry to learn what.
    The figures are what a table can honestly give. What they cannot give is the verdict:
    whether p = 0.03 met the endpoint depends on the alpha the protocol spent on it,
    which the registry does not carry, and an estimate's good direction depends on what
    was measured. So the line is the registry's own numbers and the outcome stays
    unread, for the release that states it or for a person.
    """
    outcomes = conn.execute(
        """SELECT DISTINCT outcome_index, title FROM trial_result_outcomes
            WHERE nct_id = ? AND outcome_type = 'PRIMARY' ORDER BY outcome_index""",
        (nct_id,)).fetchall()
    if not outcomes:
        return None
    parts = []
    for o in outcomes[:PRIMARY_SHOWN]:
        stats = []
        for a in conn.execute(
                """SELECT method, param_type, param_value, ci_lower, ci_upper, p_value
                     FROM trial_result_analyses WHERE nct_id = ? AND outcome_index = ?
                    ORDER BY id LIMIT 2""", (nct_id, o["outcome_index"])):
            bits = []
            if a["param_value"] is not None:
                bits.append(f"{a['param_type'] or 'estimate'} {_number(a['param_value'])}")
                if a["ci_lower"] is not None and a["ci_upper"] is not None:
                    bits[-1] += f" ({_number(a['ci_lower'])} to {_number(a['ci_upper'])})"
            if a["p_value"] is not None:
                bits.append(f"p = {_number(a['p_value'])}"
                            + (f" by {a['method']}" if a["method"] else ""))
            if bits:
                stats.append(", ".join(bits))
        name = " ".join((o["title"] or "primary endpoint").split())
        parts.append(f"{name}: " + ("; ".join(stats) if stats
                                    else "no statistical analysis posted"))
    more = len(outcomes) - PRIMARY_SHOWN
    return ("Primary endpoint as posted. " + " | ".join(parts)
            + (f" | and {more} more primary endpoints" if more > 0 else ""))


# ---------------------------------------------------------------------------------- run
def run(db_path=None, today: dt.date | None = None, days: int = DAYS, step: bool | None = None,
        refresh_run_id=None, names_path=None, set_aside_path=None) -> dict:
    """Read what the refresh already holds for posted results and approvals, record the
    ones a rule can defend, and keep the rest on file with the reason. Idempotent."""
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        index = studies(conn, curated_names(names_path))
        assets = _assets(conn)
        press = press_items(conn, since)
        rows = labelled_rows(conn, (today - dt.timedelta(days=FILING_DAYS)).isoformat())
        spent = {r["evidence"] or "" for r in conn.execute(
            "SELECT evidence FROM catalyst_resolutions WHERE outcome IN ('met', 'missed')")}
        posted = [dict(r) for r in conn.execute(
            f"""SELECT f.nct_id, f.results_date FROM trial_result_fetches f
                  JOIN catalysts cat ON cat.source_url = '{_CTGOV}' || f.nct_id
                 WHERE f.has_results = 1 AND cat.catalyst_type = 'data readout'
                   AND COALESCE(cat.status, 'pending') IN ('pending', 'unknown')""")]
        for p in posted:
            p["primary"] = posted_primary(conn, p["nct_id"])
    finally:
        conn.close()
    ruled = set_aside(set_aside_path)
    by_nct = {s["nct_id"]: s for s in index}
    reports: list = []
    counts = {"read": len(press) + len(rows), "landed": 0, "held": 0, "set_aside": 0,
              "on_file": 0}

    def landing(study, how, outcome, words, when, sentence, url, source, key, kind="readout"):
        got = land(db_path, study, outcome, when, sentence, url, source, today, step)
        if got["new"]:
            counts["landed"] += 1
        reports.append(dict(
            source_key=key, company_id=study["company_id"], source=source, kind=kind, url=url,
            published_at=when, sentence=sentence, asset_id=study["asset_id"],
            nct_id=study["nct_id"], tied_by=how, outcome=outcome, matched_words=words,
            state=got["state"], reason=got.get("reason"), catalyst_id=got["catalyst_id"],
            effect=got["effect"], _new=got["new"], _study=study))

    # 1. Results the extractors labelled from a filing or a release body.
    for r in rows:
        if any(e.startswith(f"readout {r['accession']}:") or (r["source_url"] or "\0") in e
               for e in spent):
            continue
        outcome = "met" if r["outcome"] == "positive" else "missed"
        tied, seen = [], set()
        for part in r["parts"]:
            for study, how in named(part, r["company_id"], index):
                if study["nct_id"] not in seen:
                    seen.add(study["nct_id"])
                    tied.append((study, how))
        for study, how in tied:
            if all(c["status"] in announced_readouts.OUTCOMES for c in study["catalysts"]):
                continue
            landing(study, how, outcome, None, str(r["event_date"])[:10], r["quote"] or "",
                    r["source_url"], "filing" if not r["source"] else r["source"],
                    str(r["accession"]))

    # 2. Press headlines.
    for item in press:
        text, cid, url = item["headline"] or "", item["company_id"], item["url"]
        base = dict(source_key=url or text, company_id=cid, source="press", url=url,
                    published_at=item["published"], sentence=text)
        if auto_resolve.ANNOUNCEMENT.search(text):
            continue
        approval = item["kind"] == "press_approval" or (
            APPROVED_WORDS.search(text) and not RESULT_WORDS.search(text))
        tied = named(text, cid, index)
        outcome, words = (None, None) if approval else outcome_of(text)
        asset_id, shown = _asset_named(text, assets.get(cid))
        if approval:
            if asset_id is not None:
                reports.append({**base, "kind": "approval", "asset_id": asset_id,
                                **_approval(db_path, text, item["published"], asset_id,
                                            shown)})
        elif RETOLD.search(text) and not outcome:
            continue
        elif tied and outcome:
            for study, how in tied:
                landing(study, how, outcome, words, item["published"], text, url, "press",
                        url or text)
        elif tied and RESULT_WORDS.search(text):
            for study, how in tied:
                if all(c["status"] in announced_readouts.OUTCOMES for c in study["catalysts"]):
                    continue
                reports.append({**base, "kind": "readout", "asset_id": study["asset_id"],
                                "nct_id": study["nct_id"], "tied_by": how,
                                "state": "outcome_not_read",
                                "reason": (f"it names {label(study)} and does not say in so "
                                           f"many words whether the primary endpoint was met")})
        elif asset_id and (outcome or RESULT_WORDS.search(text)):
            reports.append({**base, "kind": "readout", "asset_id": asset_id, "outcome": None,
                            "state": "not_tied",
                            "reason": (f"it names {shown} and no study the book holds, by "
                                       f"registry number or by name")})

    # 3. The registry posting result tables for a study still open: a table states no
    #    outcome in words, so the study is certain and the outcome is not read.
    for p in posted:
        study = by_nct.get(p["nct_id"])
        if study is None:
            continue
        reports.append(dict(
            source_key=f"registry:{p['nct_id']}", company_id=study["company_id"],
            source="registry", kind="readout", url=_CTGOV + p["nct_id"],
            published_at=str(p["results_date"] or "")[:10] or None,
            sentence=(f"Results posted on the registry for {label(study)}."
                      + (f" {p['primary']}" if p.get("primary") else "")),
            asset_id=study["asset_id"], nct_id=study["nct_id"], tied_by="registry number",
            state="outcome_not_read",
            reason="the registry posts result tables, which state no outcome in words"))

    conn = db.get_connection(db_path)
    try:
        for rep in reports:
            study, new = rep.pop("_study", None), rep.pop("_new", False)
            rule = ruled.get(rep.get("url") or "")
            if rule and rep["state"] != "landed":
                rep.update(state="set_aside",
                           reason=f"{rule['reason']} ({rule.get('source_url') or 'read by hand'})",
                           nct_id=rep.get("nct_id") or (rule.get("nct_id") or None))
            if rep["state"] == "landed" and new and study is not None:
                _feed(conn, study, rep["outcome"], rep["published_at"], rep.get("effect"),
                      today, refresh_run_id)
            elif rep["state"] in SHOWN:
                counts["held"] += 1
            counts["set_aside"] += rep["state"] == "set_aside"
            counts["on_file"] += rep["state"] in ("on_file", "no_gate")
            _report(conn, today, **rep)
        conn.commit()
    finally:
        conn.close()
    return counts


def _approval(db_path, text: str, published: str, asset_id, shown) -> dict:
    """What an approval headline is, against what the book holds: an approval or a label
    expansion already on file, a decision the calendar is waiting on, or a use no gate
    is waiting on. An approval is tied to a gate by its indication against the
    decision's, never to a study's readout: an approval is not a readout, whatever study
    it rests on.

    A first approval is a row of ``approvals`` and a widened label is a row of
    ``supplements`` (openFDA's efficacy supplements): that is where the book records
    that either happened, and a headline is only ever read against them."""
    import applications
    happened = bool(US_APPROVED.search(text)) and not NOT_YET.search(text)
    conn = db.get_connection(db_path)
    try:
        try:
            day = dt.date.fromisoformat(published)
        except (TypeError, ValueError):
            day = None
        if happened and day is not None:
            lo = (day - dt.timedelta(days=APPROVAL_DAYS)).isoformat()
            hi = (day + dt.timedelta(days=30)).isoformat()
            row = conn.execute(
                "SELECT application_number, approval_date, agency FROM approvals"
                " WHERE asset_id = ? AND approval_date BETWEEN ? AND ?"
                " ORDER BY approval_date DESC LIMIT 1", (asset_id, lo, hi)).fetchone()
            if row:
                return {"state": "on_file",
                        "reason": (f"the approval is on file: {row['agency'] or 'FDA'} "
                                   f"{row['application_number']} on {row['approval_date']}")}
            row = conn.execute(
                "SELECT application_number, submission_number, approval_date FROM supplements"
                " WHERE asset_id = ? AND approval_date BETWEEN ? AND ?"
                " ORDER BY ABS(julianday(approval_date) - julianday(?)) LIMIT 1",
                (asset_id, lo, hi, day.isoformat())).fetchone()
            if row:
                return {"state": "on_file",
                        "reason": (f"the label expansion is on file: efficacy supplement "
                                   f"{row['application_number']}/{row['submission_number']} "
                                   f"approved {row['approval_date']}")}
        words = applications._words(text)
        for cat in conn.execute(
                "SELECT id, title, expected_date FROM catalysts WHERE asset_id = ?"
                " AND catalyst_type IN ('PDUFA', 'regulatory decision')"
                " AND COALESCE(status, 'pending') = 'pending'", (asset_id,)):
            _product, indication = applications.parse_title(cat["title"])
            if happened and indication and applications._words(indication) & words:
                return {"state": "awaiting_register", "catalyst_id": cat["id"],
                        "reason": (f"an approval is reported in the use the decision on file "
                                   f"is for ({indication}); that decision resolves when "
                                   f"openFDA lists the approval, not on a headline")}
    finally:
        conn.close()
    return {"state": "no_gate",
            "reason": (f"it reports an approval or an opinion on {shown} in a use no "
                       f"decision on the book is waiting on, so it decides no gate")}


def record_report(db_path, report_id: int, outcome: str, today: dt.date | None = None,
                  step: bool | None = None) -> dict | None:
    """A person reads a report the rules held and says the outcome. Only a report whose
    study is certain can be recorded: the outcome was the one thing missing. None where
    there is no such report; ValueError where it cannot take an outcome."""
    today = today or dt.date.today()
    if outcome not in announced_readouts.OUTCOMES:
        raise ValueError(f"outcome must be met or missed, got '{outcome}'")
    conn = db.get_connection(db_path)
    try:
        rep = conn.execute("SELECT * FROM readout_reports WHERE id = ?", (report_id,)).fetchone()
        if rep is None:
            return None
        rep = dict(rep)
        if rep["state"] != "outcome_not_read" or not rep["nct_id"]:
            raise ValueError("only a report tied to a study, with its outcome not read, "
                             "takes a recorded outcome")
        study = next((s for s in studies(conn) if s["nct_id"] == rep["nct_id"]), None)
    finally:
        conn.close()
    if study is None:
        raise ValueError(f"no readout on the calendar for {rep['nct_id']}")
    when = rep["published_at"] or today.isoformat()
    got = land(db_path, study, outcome, when, rep["sentence"] or "", rep["url"],
               rep["source"], today, step, automated=False)
    conn = db.get_connection(db_path)
    try:
        if got["state"] == "landed":
            conn.execute(
                "UPDATE readout_reports SET state = 'landed', outcome = ?, reason = ?,"
                " catalyst_id = ?, effect = ?, updated_at = ? WHERE id = ?",
                (outcome, "the outcome was read and recorded by hand", got["catalyst_id"],
                 got["effect"], today.isoformat(), report_id))
            if got["new"]:
                _feed(conn, study, outcome, when, got["effect"], today)
        conn.commit()
    finally:
        conn.close()
    return {"report_id": report_id, "nct_id": rep["nct_id"], **got}


# ----------------------------------------------------------------------------- the block
def block(db_path=None, ticker: str | None = None, days: int = DAYS,
          today: dt.date | None = None) -> dict:
    """What the Catalysts tab says: the readouts that have landed, each with its source,
    and what was reported and is held, each with why. Two lists, never one."""
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        company = None
        if ticker:
            company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                                   (ticker.upper(),)).fetchone()
            if company is None:
                return {"ticker": ticker.upper(), "days": days, "landed": [], "reported": []}
        who = (" AND cat.company_id = ?", [company["id"]]) if company else ("", [])
        landed = []
        for r in conn.execute(
                f"""SELECT res.outcome, res.event_date, res.source, res.evidence,
                           res.automated, cat.id AS catalyst_id, cat.source_url, co.ticker,
                           t.nct_id, t.title, t.acronym, t.phase,
                           COALESCE(a.brand_name, a.generic_name, a.internal_code) AS asset
                      FROM catalyst_resolutions res
                      JOIN catalysts cat ON cat.id = res.catalyst_id
                      JOIN companies co ON co.id = cat.company_id
                      LEFT JOIN trials t ON cat.source_url = '{_CTGOV}' || t.nct_id
                      LEFT JOIN assets a ON a.id = COALESCE(t.asset_id, cat.asset_id)
                     WHERE res.outcome IN ('met', 'missed') AND res.event_date >= ?
                       AND cat.catalyst_type = 'data readout' AND cat.status = res.outcome
                       {who[0]}
                     ORDER BY res.event_date DESC, res.id DESC""", [since, *who[1]]):
            url, _, sentence = (r["evidence"] or "").partition(": ")
            if not url.startswith("http"):
                url, sentence = None, r["evidence"] or ""
            rep = conn.execute(
                "SELECT effect, tied_by, url, sentence FROM readout_reports"
                " WHERE catalyst_id = ? AND state = 'landed' ORDER BY id DESC LIMIT 1",
                (r["catalyst_id"],)).fetchone()
            names = names_of({"nct_id": r["nct_id"], "title": r["title"],
                              "acronym": r["acronym"]}, curated_names())
            landed.append({
                "ticker": r["ticker"], "asset": r["asset"], "nct_id": r["nct_id"],
                "study": names[0] if names else None, "phase": r["phase"],
                "outcome": r["outcome"], "event_date": r["event_date"],
                "sentence": sentence or (rep["sentence"] if rep else ""),
                "url": url or (rep["url"] if rep else None) or r["source_url"],
                "source": r["source"], "automated": bool(r["automated"]),
                "tied_by": rep["tied_by"] if rep else None,
                "effect": rep["effect"] if rep else None})
        marks = ", ".join("?" * len(SHOWN))
        who_rep = (" AND rep.company_id = ?", [company["id"]]) if company else ("", [])
        reported = []
        for r in conn.execute(
                f"""SELECT rep.*, co.ticker, t.title, t.acronym,
                           COALESCE(a.brand_name, a.generic_name, a.internal_code) AS asset
                      FROM readout_reports rep
                      JOIN companies co ON co.id = rep.company_id
                      LEFT JOIN trials t ON t.nct_id = rep.nct_id
                      LEFT JOIN assets a ON a.id = rep.asset_id
                     WHERE rep.state IN ({marks})
                       AND COALESCE(rep.published_at, rep.first_seen) >= ? {who_rep[0]}
                     ORDER BY COALESCE(rep.published_at, rep.first_seen) DESC, rep.id DESC""",
                [*SHOWN, since, *who_rep[1]]):
            names = names_of({"nct_id": r["nct_id"], "title": r["title"],
                              "acronym": r["acronym"]}, curated_names()) if r["nct_id"] else []
            reported.append({
                "id": r["id"], "ticker": r["ticker"], "asset": r["asset"], "kind": r["kind"],
                "state": r["state"], "nct_id": r["nct_id"],
                "study": names[0] if names else None, "sentence": r["sentence"],
                "url": r["url"], "published_at": r["published_at"], "source": r["source"],
                "reason": r["reason"]})
        return {"ticker": (ticker or "").upper() or None, "days": days,
                "landed": landed, "reported": reported}
    finally:
        conn.close()
