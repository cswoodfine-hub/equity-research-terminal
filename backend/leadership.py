"""Who runs the company, read out of the 8-K that reports the change.

A CEO leaving is one of the few single facts that reprices a mid-cap on the day. EDGAR
files it under Item 5.02, which the filings table already labels "Director or officer
change" and then treats as housekeeping. It is not housekeeping, but nor is most of it:
484 filings carry that item and the great majority elect a director or restate a bonus
plan. The signal is rare, so the work here is precision rather than recall.

Reading the item body for a job title finds one in almost every filing, and nearly all
of them are the wrong one. From a corpus of 60 real filings, "Chief Executive Officer"
appears in the item body of eight and means a transition in one. The rest are:

  a new director's biography    "he served as chief executive officer of Alexion"
  a compensation exhibit        "a Tier 1 Participant (which includes the CEO)"
  an equity award               "granted under the 2018 Stock Incentive Plan to ...,
                                 the Company's Chief Executive Officer"
  a reporting line              "Mr. Dittrich will report to Robert A. Bradway,
                                 Chairman and Chief Executive Officer"

So a title alone proves nothing. A transition needs a verb that moves someone into or
out of a role, the role has to belong to this company rather than to a name in someone's
career history, and the sentence must not be about pay. Each of those is a guard below,
and each exists because of a filing that got past its absence.

The pure half. The download and the change write live in the caller, so the parser can
be tested against saved filings.
"""

from __future__ import annotations

import re

# The roles worth a change row, most senior first, since a sentence naming two ("President
# and Chief Executive Officer") should read as the more senior one.
ROLES: tuple = (
    ("Chief executive", r"chief executive officer\b|\bceo\b"),
    ("Chair", r"chair(?:man|woman|person)?\s+of\s+the\s+board|executive chair(?:man)?\b"),
    ("Chief financial", r"chief financial officer\b|\bcfo\b"),
    ("Chief scientific", r"chief scientific officer\b|chief scientist\b|\bcso\b"),
    ("Chief medical", r"chief medical officer\b|\bcmo\b"),
    ("Chief operating", r"chief operating officer\b|\bcoo\b"),
    # A vice president is not the President. "Dr. Reese will remain employed as an
    # Executive Vice President until his retirement" read as the president leaving.
    ("President", r"(?<!vice )(?<!vice-)\bpresident\b"),
    ("Chief commercial", r"chief commercial officer\b"),
    ("Chief technology", r"chief technology officer\b|chief technical officer\b"),
    ("Chief legal", r"chief legal officer\b|general counsel\b"),
)

# A departure is worth more than an arrival: an unexplained exit is the signal, and a
# named successor is usually already known. Both are recorded.
_DEPART = (r"resign(?:ed|s|ation)?|retire(?:d|s|ment)?|step(?:ped|s|ping)?\s+down|"
           r"depart(?:ed|s|ure)?|separat(?:ed|ion)\s+from|terminat(?:ed|ion)|"
           r"will\s+leave|is\s+leaving|relinquish(?:ed|es)?|transition(?:ed|ing)?\s+out|"
           r"ceas(?:e|es|ed)\s+to\s+serve|ceased\s+serving")
_ARRIVE = (r"appoint(?:ed|s|ment)?|elect(?:ed|s)?|nam(?:ed|es)|promot(?:ed|es)|"
           r"succeed(?:ed|s|ing)?|replac(?:es|ed|ing)|"
           # "cease to serve as Chief Technology Officer" is a resignation, and
           # reading the tail of it as an arrival made one filing report both.
           r"(?<!cease )(?<!ceases )(?<!ceased )(?:will|to)\s+serve\s+as|"
           r"will\s+become|join(?:ed|s|ing)?\s+the\s+company\s+as|has\s+been\s+appointed")

DEPARTURE = "departure"
APPOINTMENT = "appointment"

# Item 5.02(e) is compensatory arrangements, filed under the same item number as a real
# transition. These words mark it, and a sentence carrying one is about pay whatever
# titles it names.
_PAY_WORDS = (
    "severance", "incentive plan", "equity award", "restricted stock", "stock option",
    "option award", "base salary", "annual bonus", "target bonus", "bonus",
    "compensation committee", "compensatory", "participant", "vesting", "grant", "award",
    "retention award", "change in control agreement", "employment agreement provides",
)

# Every 8-K ends with a safe-harbour paragraph that lists what the filing said. It names
# the event again, in a sentence that is about litigation risk rather than about the
# company, and reading it double-counted a retirement.
_BOILERPLATE = (
    "forward-looking statements", "forward looking statements", "safe harbor",
    "within the meaning of the private securities", "risks and uncertainties",
    # The governance disclaimer every appointment carries. It restates the role in a
    # negative sentence, which is true and is not the event.
    "not selected pursuant to", "was not selected", "no arrangement or understanding",
    "there is no family relationship", "no reportable family",
)

# A biography. An incoming director's history names every company they have run, and
# each of those is a chief executive officer in a sentence that also says "appointed".
_BIOGRAPHY = (
    "previously served", "previously held", "prior to joining", "most recently",
    "prior to that", "has served as", "he served as", "she served as", "they served as",
    "from 20", "until its acquisition", "before joining", "earlier in",
)

# The role belongs to another company: "chief executive officer of Alexion". Anchored
# to a capitalised name, so "of the Company" and "of the Board" do not trip it.
_ROLE_OF_OTHER = re.compile(
    r"\b(?:of|at|with)\s+(?!the\b|its\b|our\b|such\b)(?:[A-Z][\w.\-]*\s*){1,4}"
    r"(?:Inc|Corp(?:oration)?|Compan(?:y|ies)|Ltd|Limited|LLC|plc|PLC|N\.V|S\.A|AG|"
    r"GmbH|Pharmaceutical(?:s)?|Therapeutic(?:s)?|Bio(?:sciences|pharma\w*)?|"
    r"Sciences|Medicines|Health(?:care)?|Holdings|Group|Laboratories)\b")

# "will report to <name>, Chairman and Chief Executive Officer" names a role holder who
# is not going anywhere.
_REPORTING_LINE = re.compile(r"\breport(?:s|ing)?\s+to\b", re.I)

_ITEM_502 = re.compile(r"item\s*5\.0?2\b", re.I)
_ITEM_NEXT = re.compile(r"item\s*(?:5\.0[3-9]|[6-9]\.\d{2})\b", re.I)

# Abbreviations that end in a period and do not end a sentence. Without these, every
# "Inc." and "M.D." starts a new sentence and the verb loses its role.
_ABBREV = re.compile(
    r"\b(Inc|Corp|Ltd|Co|Mr|Mrs|Ms|Dr|Jr|Sr|St|No|vs|etc|Ph\.D|M\.D|M\.B\.A|"
    r"Pharm\.D|D\.V\.M|J\.D|U\.S|N\.V|S\.A)\.", re.I)


def item_body(text: str) -> str:
    """The Item 5.02 section, or the whole filing when the heading is not found.

    Some filers put the item heading only in an exhibit, so falling back to the whole
    document keeps those readable; the sentence guards are what prevent that from
    turning the exhibit's prose into an event.
    """
    text = re.sub(r"\s+", " ", text or "")
    match = _ITEM_502.search(text)
    if not match:
        return text
    rest = text[match.end():]
    end = _ITEM_NEXT.search(rest)
    return rest[:end.start()] if end else rest


def sentences(text: str) -> list:
    """Split into sentences, keeping "Inc." and "Ph.D." from ending one."""
    protected = _ABBREV.sub(lambda m: m.group(0).replace(".", "\x00"), text)
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z(])", protected)
    return [p.replace("\x00", ".").strip() for p in parts if p.strip()]


# How close a verb has to sit to a role to be acting on it. One sentence can carry two
# people: "the CMO resigned ... and the CEO has agreed to assume her responsibilities on
# an interim basis" reported the chief executive as leaving, because the senior role in
# the sentence was taken to be the subject. A role is now paired with its nearest verb
# instead, and a role with no verb near it reports nothing.
#
# 90 characters, calibrated against the 60-filing corpus rather than picked. It is the
# widest setting that still refuses a title sitting a clause away from the verb, and it
# costs nothing: 90 and 140 find the same 20 events, while 140 also lets the chief
# executive above read as departing. Below 80 a real compound title starts to break,
# "appointed as the Company's Chief Operating Officer and General Counsel" being one
# verb acting on two roles.
_VERB_WINDOW = 90


# "appointed Dr. Ram Aiyar, President and Chief Executive Officer, to serve as Korro's
# interim Chief Financial Officer" names three roles and changes one. The two before the
# comma are the man's existing title, said to identify him; the role after "as" is what
# he is being appointed to. So when a sentence puts any role in that position, only
# those roles are the event. The comma is what carries the distinction, which is why the
# lookback refuses to cross one.
_AS_ROLE = re.compile(r"\bas\b[^,;]{0,30}$", re.I)


def _roles_in(sentence: str) -> list:
    """(role, position) for every role the sentence names.

    Roles introduced by "as" win outright where any exist, because that is the role the
    sentence is about; the others merely say who the person already was.
    """
    found = []
    for name, pattern in ROLES:
        for match in re.finditer(pattern, sentence, re.I):
            found.append((name, match.start()))
    objects = [r for r in found if _AS_ROLE.search(sentence[:r[1]])]
    return objects or found


def _verbs_in(sentence: str) -> list:
    """(kind, position) for every transition verb the sentence uses."""
    found = [(DEPARTURE, m.start()) for m in re.finditer(_DEPART, sentence, re.I)]
    found += [(APPOINTMENT, m.start()) for m in re.finditer(_ARRIVE, sentence, re.I)]
    return found


def _is_pay(sentence: str) -> bool:
    low = sentence.lower()
    return any(word in low for word in _PAY_WORDS)


def _is_biography(sentence: str) -> bool:
    low = sentence.lower()
    return any(word in low for word in _BIOGRAPHY)


def classify_sentence(sentence: str) -> list:
    """Every (role, kind) transition this sentence reports at this company.

    A list, because one sentence often reports a swap: "Dr. Severino will succeed
    Douglas Ingram" names an arrival and a departure at once, and collapsing that to a
    single answer loses half of it.

    Every rejection below is a filing that would otherwise have produced a false chief
    executive change, which is worse than reporting nothing: an analyst acts on it.
    """
    low = sentence.lower()
    if any(word in low for word in _BOILERPLATE):
        return []
    if _is_pay(sentence) or _is_biography(sentence):
        return []
    if _REPORTING_LINE.search(sentence):
        return []
    if _ROLE_OF_OTHER.search(sentence):
        return []
    verbs = _verbs_in(sentence)
    if not verbs:
        return []
    found = []
    for role, position in _roles_in(sentence):
        kind, distance = min(
            ((k, abs(p - position)) for k, p in verbs), key=lambda pair: pair[1])
        if distance <= _VERB_WINDOW and (role, kind) not in found:
            found.append((role, kind))
    return found


def extract(text: str) -> list:
    """Every leadership transition an Item 5.02 filing reports.

    Returns [{role, kind, sentence}], deduplicated on role and kind: one filing often
    states the same appointment twice, in the item body and again in the press release
    it attaches. Where it does, the shorter sentence is kept, which is reliably the one
    that states the event rather than the one that also disclaims family relationships
    under Item 404(a).
    """
    found: dict = {}
    for sentence in sentences(item_body(text)):
        for key in classify_sentence(sentence):
            prior = found.get(key)
            if prior is None or len(sentence) < len(prior["sentence"]):
                found[key] = {"role": key[0], "kind": key[1],
                              "sentence": sentence[:400]}
    return list(found.values())


# A chief executive or a chair leaving moves the price on the day. A divisional
# president or a general counsel is real news and not that, so it is recorded and not
# escalated. Directors never reach here: the role list does not include them.
HIGH_SIGNIFICANCE = frozenset({"Chief executive", "Chair", "Chief financial"})


def significance(role: str, kind: str) -> str:
    if role in HIGH_SIGNIFICANCE:
        return "high" if kind == DEPARTURE else "medium"
    return "medium" if kind == DEPARTURE else "low"


# --- the impure half: read the filings, store what they report ------------------------

LOOKBACK_DAYS = 400
_ITEM_TITLE = "Director or officer change"


def candidates(db_path=None, lookback_days: int = LOOKBACK_DAYS, today=None) -> list:
    """Item 5.02 filings not yet read.

    Keyed on the accession, so a filing is downloaded once however many times the
    refresh runs. EDGAR is rate limited and there are hundreds of these.
    """
    import datetime as dt

    import db

    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=lookback_days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        seen = {r[0] for r in conn.execute(
            "SELECT DISTINCT accession FROM leadership_changes")}
        rows = [dict(r) for r in conn.execute(
            """
            SELECT f.accession, f.filed_date, f.url, f.company_id, c.ticker
              FROM filings f JOIN companies c ON c.id = f.company_id
             WHERE f.title LIKE ? AND f.filed_date >= ?
               AND f.url IS NOT NULL AND f.url <> ''
             ORDER BY f.filed_date DESC
            """, (f"%{_ITEM_TITLE}%", cutoff))]
    finally:
        conn.close()
    return [r for r in rows if r["accession"] not in seen]


def detect(db_path=None, run_id=None, limit: int = 60, get=None) -> dict:
    """Read the unread Item 5.02 filings and record the transitions they report.

    Bounded per run. A first run over a year of filings would otherwise make several
    hundred EDGAR requests in one pass, and the unread ones simply wait for tomorrow.

    A senior departure is written to the change feed as well as to its own table, so it
    reaches the morning note by the same route as a trial slipping.
    """
    import db
    import deals

    fetch = get or deals._get
    pending = candidates(db_path)[:limit]
    conn = db.get_connection(db_path)
    written = read = 0
    errors: list = []
    try:
        for filing in pending:
            try:
                text = deals.pdufa.strip_html(fetch(filing["url"]))
            except Exception as exc:
                errors.append(f"{filing['ticker']} {filing['accession']}: {exc}")
                continue
            read += 1
            for event in extract(text):
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO leadership_changes"
                    "  (company_id, accession, filed_date, role, kind, evidence, url)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (filing["company_id"], filing["accession"], filing["filed_date"],
                     event["role"], event["kind"], event["sentence"], filing["url"]))
                if not cursor.rowcount:
                    continue
                written += 1
                conn.execute(
                    "INSERT INTO changes (entity_type, entity_key, field, old_value,"
                    "  new_value, change_type, significance, refresh_run_id)"
                    " VALUES ('company', ?, 'leadership', NULL, ?, 'leadership_change',"
                    "         ?, ?)",
                    (f"{filing['ticker']}|{filing['accession']}",
                     f"{event['role']} {event['kind']}",
                     significance(event["role"], event["kind"]), run_id))
            # Filings that report nothing are still marked read, so the next run does
            # not download them again. A row with no role is the marker.
            conn.execute(
                "INSERT OR IGNORE INTO leadership_changes"
                "  (company_id, accession, filed_date, role, kind, evidence, url)"
                " VALUES (?, ?, ?, 'none', 'none', NULL, ?)",
                (filing["company_id"], filing["accession"], filing["filed_date"],
                 filing["url"]))
        conn.commit()
    finally:
        conn.close()
    return {"read": read, "written": written, "pending": len(candidates(db_path)),
            "errors": errors}
