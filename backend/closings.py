"""A closed acquisition, read from what the acquirer filed, and the target's own numbers.

The headline deals table cannot start a forecast row: it lists Iovance "acquiring"
Pavilions Marketplace and Beam "acquiring" Robinhood, because a headline names whoever is
nearby. A filing names the parties. So a closing is taken only from a filing the acquirer
made: an 8-K Item 2.01, an 8-K or 6-K press release whose lead states the completion, or
the sentence in a 10-Q, 10-K or 20-F that says "we completed the acquisition of".

Three rules keep a sentence from being read as a closing it is not.

The subject has to be the filer. Beam's 10-K says "Lilly completed its acquisition of
Verve", which is a closing, and Beam is not the acquirer: it sold a stake.

A sale is not an acquisition. Rocket's and Abeona's Item 2.01 filings report the sale of a
priority review voucher; Adaptimmune's reports the sale of its cell therapies.

A press release counts only when its lead states the closing. A results release mentions
last year's acquisitions in passing, and that is not news.

Everything here is pure: text in, findings out. The reads are in
``fetchers/closings_edgar.py`` and the drafting in ``input_drafts.py``.
"""

from __future__ import annotations

import datetime as dt
import html as _html
import re

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_DAY_DATE = re.compile(rf"\b({_MONTH})\s+(\d{{1,2}}),?\s+(20\d\d)\b")
_DAY_FIRST = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH})\s+(20\d\d)\b")
_MONTH_DATE = re.compile(rf"\b(?:[Ii]n|[Dd]uring)\s+({_MONTH})\s+(20\d\d)\b")

# The legal suffix a company name carries, which the key drops.
_LEGAL = (r"(?:,?\s+(?:Inc|Incorporated|Corp|Corporation|Ltd|Limited|plc|PLC|AG|S\.?A|"
          r"N\.?V|GmbH|LLC|L\.L\.C|Co|SE|B\.?V|A/S|Holdings?))\.?")
_WORD = r"[A-Z0-9][\w&’'\-./]*"
# A proper name: capitalised words, with "of", "and" or "&" allowed inside, then an
# optional legal suffix. Case-sensitive on purpose: "the remaining interest in" is not a
# name.
# A lower-case word is let in only at the end and only before a comma or a bracket, for
# a name such as "2seventy bio".
_NAME = (rf"(?P<target>{_WORD}(?:\s+(?:{_WORD}|of|&))*?(?:\s+[a-z]{{2,8}}(?=\s*[,(;]))?"
         rf"(?:{_LEGAL})?)")
# Case-insensitive, because a headline in capitals ("GILEAD COMPLETES ACQUISITION OF
# ARCELLX AHEAD OF ...") has no lower-case word to stop at.
_STOP = (r"(?=\s*(?:\(|,|\.(?:\s|$)|;|:|“|\"|$)|\s+(?i:for|in|a|an|which|from|pursuant|"
         r"through|on|by|to|that|with|and|under|at|as|ahead|after|following|expanding|"
         r"strengthening|adding|bolstering|creating|marking)\b|"
         # A dateline: "Sanofi completes acquisition of Vicebio Paris, December 4, 2025".
         rf"\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,\s+{_MONTH}\s+\d{{1,2}})")
_PREFIX = (r"(?:all\s+of\s+the\s+(?:issued\s+and\s+)?outstanding\s+(?:shares(?:\s+of\s+"
           r"common\s+stock)?|equity\s+interests|capital\s+stock)\s+of\s+|100%\s+of\s+|"
           r"the\s+entire\s+issued\s+share\s+capital\s+of\s+)?")

_COMPLETED = re.compile(
    r"(?i:\b(?:has\s+|had\s+)?(?:completed|completes|consummated|closed|"
    r"announced\s+(?:the\s+)?completion\s+of|announces\s+(?:the\s+)?completion\s+of|"
    r"announced\s+that\s+it\s+(?:has|had)\s+completed)\s+"
    r"(?:the\s+|its\s+|our\s+|their\s+)?(?:previously[- ]announced\s+|previously[- ]disclosed\s+|"
    r"all[- ]cash\s+)?(?:acquisition|merger(?:\s+transaction)?|purchase|tender\s+offer\s+for)"
    r"\s+(?:of|with)\s+)" + _PREFIX + _NAME + _STOP)

# "Purchaser was merged with and into Soleno, ... and Soleno continued as a direct wholly
# owned subsidiary of the Company": the survivor is the target, and the parent has to be
# the filer.
_SURVIVOR = re.compile(
    rf"(?P<survivor>{_WORD}(?:\s+{_WORD})*?)\s+(?:surviving|survived|continued|continuing|"
    rf"continues)\s+as\s+(?:the\s+surviving\s+(?:corporation|company|entity)[^.]{{0,120}}?"
    rf"\s+(?:and\s+)?(?:as\s+)?)?a\s+(?:direct\s+|indirect\s+)?(?:and\s+)?wholly[- ]owned\s+"
    rf"subsidiary\s+of\s+(?P<parent>the\s+Company|Parent|{_WORD}(?:\s+{_WORD})*)")
# "the Purchaser would acquire the entire issued share capital of Life Molecular Imaging
# Limited ... On July 21, 2025, the parties completed the Transaction."
_WOULD_ACQUIRE = re.compile(
    r"(?i:\b(?:would|will|agreed\s+to|shall)\s+acquire\s+)" + _PREFIX + _NAME + _STOP)
_DONE_DEFINED = re.compile(r"(?i)\bcompleted\s+the\s+(?:Transaction|Acquisition|Merger)\b")
_SALE = re.compile(r"(?i)\bcompleted\s+the\s+(?:previously\s+(?:announced|disclosed)\s+)?"
                   r"(?:sale|divestiture|disposition)\b|\bsale\s+of\s+(?:its|the|substantially)"
                   r"|\bpriority\s+review\s+voucher\b")
_ITEM_201 = re.compile(r"(?i)item\s*2\.01")

# What a subject that is the filer looks like, beyond the filer's own names.
_SELF = ("we", "our", "the company", "the group", "parent")
_NOT_A_TARGET = re.compile(r"(?i)^(?:the|a|an|its|our|this|certain|such|each|all|"
                           r"merger\s+sub|purchaser|offer|transaction|acquisition)\b")


_INVISIBLE = re.compile(r"[\u200b-\u200f\u2028\u2029\ufeff\u00ad]")


def _flat(text: str) -> str:
    text = _INVISIBLE.sub("", _html.unescape(text or ""))
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()


def target_key(name: str) -> str:
    """Lower case, legal suffix and punctuation dropped: the name two filings share."""
    name = re.sub(_LEGAL + r"\s*$", "", (name or "").strip())
    name = re.sub(r"[“”\"'’(),.]", " ", name)
    return re.sub(r"\s+", " ", name).strip().lower()


def same_target(a: str, b: str) -> bool:
    """One filing calls it "Intra-Cellular" and another "Intra-Cellular Therapies, Inc.".
    Two keys are one target when the shorter is a word-for-word prefix of the longer."""
    x, y = target_key(a).split(), target_key(b).split()
    if not x or not y:
        return False
    short, long_ = (x, y) if len(x) <= len(y) else (y, x)
    return long_[:len(short)] == short


def aliases(name: str, ticker: str) -> set:
    """The words a filing uses for its filer: ticker, first word of the name, initials."""
    out = {(ticker or "").lower()}
    words = [w for w in re.split(r"[\s,]+", re.sub(_LEGAL + r"\s*$", "", name or "")) if w]
    if words:
        first = words[0].lower()
        out.add(first)
        if "-" in first:
            out.add(first.split("-")[0])
        if words[0] == "Johnson" or first == "johnson":
            out.add("j&j")
        parts = [p for w in words for p in w.split("-") if p[:1].isupper()]
        if len(parts) >= 2:
            out.add("".join(p[0] for p in parts).lower())
    return {a for a in out if len(a) >= 3}


def _is_filer(actor: str, names: set) -> bool:
    actor = re.sub(r"[“”\"'’]", " ", actor.lower())
    actor = re.sub(r"\s+", " ", actor)
    words = set(re.findall(r"[\w&-]+", actor))
    if any(n in words or f" {n} " in f" {actor} " for n in names):
        return True
    return any(re.search(rf"(?:^|[\s,(]){re.escape(s)}(?:$|[\s,)])", actor) for s in _SELF)


def _sentence(text: str, start: int, end: int) -> tuple[str, int]:
    """The sentence around [start, end), and where it starts."""
    head = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    head = head + 1 if head >= 0 else 0
    tail = text.find(". ", end)
    tail = tail + 1 if tail >= 0 else len(text)
    return text[head:tail].strip(), head


def closing_date(sentence: str, fallback: str | None = None) -> str | None:
    """YYYY-MM-DD from the sentence's own date, YYYY-MM from "in July 2025"."""
    found = _DAY_DATE.search(sentence or "")
    if found:
        month = _MONTHS.index(found.group(1).lower()) + 1
        try:
            return dt.date(int(found.group(3)), month, int(found.group(2))).isoformat()
        except ValueError:
            return fallback
    found = _DAY_FIRST.search(sentence or "")
    if found:
        month = _MONTHS.index(found.group(2).lower()) + 1
        try:
            return dt.date(int(found.group(3)), month, int(found.group(1))).isoformat()
        except ValueError:
            return fallback
    found = _MONTH_DATE.search(sentence or "")
    if found:
        return f"{found.group(2)}-{_MONTHS.index(found.group(1).lower()) + 1:02d}"
    return fallback


def _clean_target(name: str) -> str | None:
    name = (name or "").strip(" ,;:")
    if name.endswith(".") and not re.search(_LEGAL + r"$", name):
        name = name.rstrip(".")
    if not name or _NOT_A_TARGET.match(name) or len(name) < 3:
        return None
    return name


def long_name(text: str, short: str) -> str:
    """The full name a filing defines a short one by: "Soleno Therapeutics, Inc., a
    Delaware corporation (“Soleno”)" gives "Soleno Therapeutics, Inc."."""
    pattern = re.compile(
        rf"({_WORD}(?:\s+{_WORD})*?(?:{_LEGAL})?)(?:,\s*an?\s+[\w\s]{{2,60}}?)?\s*\(\s*"
        rf"(?:the\s+)?[“\"]\s*{re.escape(short)}\s*[”\"]")
    for found in pattern.finditer(text or ""):
        candidate = found.group(1).strip(" ,")
        if same_target(candidate, short) and len(candidate) > len(short):
            return candidate
    return short


def find_closings(text: str, filer_names: set, *, lead_only: bool = False,
                  item_201: bool = False) -> dict:
    """{acquisitions: [{target, closing_date, quote}], disposition: bool} for one text.

    ``item_201`` is an 8-K that reports Item 2.01: the merger sentences count as evidence
    there too, and the whole body is read, since the completion is often stated in the
    introductory note before the items. ``lead_only`` reads the first 4,000 characters, a press release's
    headline and first paragraph.
    """
    flat = _flat(text)
    if item_201 and not _ITEM_201.search(flat):
        return {"acquisitions": [], "disposition": False}
    if lead_only:
        flat = flat[:4000]
    out = []

    def add(target, sentence):
        target = _clean_target(target)
        if not target:
            return
        full = long_name(_flat(text), target)
        key = target_key(full)
        if not key:
            return
        for earlier in out:
            # A headline says "Vega Therapeutics" and the lead "Vega Therapeutics, Inc.":
            # one target, named the longer way.
            if same_target(earlier["target"], full):
                if len(full) > len(earlier["target"]):
                    earlier["target"] = full
                return
        out.append({"target": full, "closing_date": closing_date(sentence),
                    "quote": sentence})

    for found in _COMPLETED.finditer(flat):
        sentence, head = _sentence(flat, found.start(), found.end())
        actor = flat[head:found.start()]
        if _is_filer(actor, filer_names):
            add(found.group("target"), sentence)
    if item_201:
        for found in _SURVIVOR.finditer(flat):
            survivor = found.group("survivor").strip(" .")
            if survivor in ("Company", "Merger Sub", "Purchaser", "Sub", "Surviving") or (
                    not _is_filer(found.group("parent"), filer_names)):
                continue
            sentence, _ = _sentence(flat, found.start(), found.end())
            add(survivor, sentence)
        if not out and _DONE_DEFINED.search(flat):
            done = _DONE_DEFINED.search(flat)
            for found in _WOULD_ACQUIRE.finditer(flat[:done.start()]):
                sentence, _ = _sentence(flat, done.start(), done.end())
                add(found.group("target"), sentence)
                break
    disposition = bool(not out and _SALE.search(flat))
    return {"acquisitions": out, "disposition": disposition}


# --- what was paid -----------------------------------------------------------------

_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(billion|million|bn|mm|m)\b", re.I)
_PAID = re.compile(r"(?i)aggregate\s+(?:cash\s+)?(?:consideration|purchase\s+price)|"
                   r"total\s+(?:cash\s+)?consideration|purchase\s+price|equity\s+value|"
                   r"upfront\s+cash\s+payment|cash\s+payment\s+of|\bpaid\b|"
                   r"(?:acquisition|shares)\s+of\s+[^.]{1,80}\s+for\s+(?:approximately\s+)?\$|"
                   r"\bacquired?\s+[^.]{1,80}?\s+for\s+(?:approximately\s+|about\s+)?\$")
_CVR = re.compile(r"(?i)contingent\s+value\s+right|\bCVRs?\b")
_NOT_PAID = re.compile(r"(?i)per\s+share|revenue|net\s+sales|milestone|escrow|"
                       r"market\s+cap|financing|term\s+loan|credit\s+facility|notes\b")


def _amount(number: str, scale: str) -> float:
    value = float(number.replace(",", ""))
    return value * (1e9 if scale.lower() in ("billion", "bn") else 1e6)


def consideration(text: str, target: str) -> dict:
    """{cash, cash_quote, cvr_quote}: the cash paid where a sentence states its total, in
    USD, and the sentence that states a contingent value right. Nothing is summed."""
    flat = _flat(text)
    key = target_key(target).split()[0] if target_key(target) else ""
    out = {"cash": None, "cash_quote": None, "cvr_quote": None}
    for sentence in re.split(r"(?<=[.;])\s+(?=[A-Z(•])", flat):
        lower = sentence.lower()
        if (_CVR.search(sentence) and "$" in sentence and out["cvr_quote"] is None
                and key and key in lower and len(sentence) < 700):
            out["cvr_quote"] = sentence.strip()
        if key and key not in lower:
            continue
        if not _PAID.search(sentence):
            continue
        for found in _MONEY.finditer(sentence):
            around = sentence[max(0, found.start() - 60): found.end() + 40]
            if _NOT_PAID.search(around):
                continue
            amount = _amount(found.group(1), found.group(2))
            if amount >= 1e7 and (out["cash"] is None or amount > out["cash"]):
                out["cash"], out["cash_quote"] = amount, sentence.strip()
    return out


# --- the target's own numbers --------------------------------------------------------

_YEAR_CELL = re.compile(r"^(?:FY\s*)?(20\d\d)\s*[EeFfPp]?$")
_NUMBER_CELL = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?$")
_SECTION = re.compile(r"(?i)certain\s+(?:unaudited\s+)?(?:prospective\s+)?financial\s+"
                      r"(?:projections|information|forecasts)|unaudited\s+prospective\s+"
                      r"financial\s+information|management\s+projections|"
                      r"certain\s+(?:[\w’']+\s+){0,2}projections")
_GAP = 12_000                       # characters of HTML between two projection tables
_UNIT = re.compile(r"(?i)\bin\s+(millions|billions)\b|\(\s*\$\s*(millions|billions)\s*\)|"
                   r"\(\s*(?:US)?\$\s*in\s+(millions|billions)\s*\)")
_REVENUE_ROW = re.compile(r"(?i)revenue|net\s+sales|product\s+sales")
_NOT_REVENUE = re.compile(r"(?i)gross|cost|margin|expense|ebit|profit|cash\s+flow|"
                          r"royalt(?:y|ies)\s+(?:paid|payable|expense)")
_RISK_ADJUSTED = re.compile(r"(?i)risk[- ]adjusted|probability[- ]adjusted|"
                            r"probability\s+of\s+(?:technical\s+and\s+regulatory\s+)?success")
_CELL = re.compile(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>")
_ROW = re.compile(r"(?is)<tr\b[^>]*>(.*?)</tr>")
_TABLE = re.compile(r"(?is)<table\b.*?</table>")
_TAG = re.compile(r"(?s)<[^>]+>")


def _cells(row_html: str) -> list[str]:
    cells = []
    for raw in _CELL.findall(row_html):
        text = _flat(_TAG.sub(" ", raw))
        if text in ("", "$", "€", "£", ")", "%"):
            if text == ")" and cells and cells[-1].startswith("("):
                cells[-1] += ")"
            continue
        cells.append(text)
    return cells


def _number(cell: str) -> float | None:
    cell = cell.replace("$", "").strip()
    if cell in ("—", "–", "-"):
        return 0.0                              # a dash in a financial table is nil
    if not _NUMBER_CELL.match(cell):
        return None
    negative = cell.startswith("(") or cell.startswith("-")
    value = float(cell.strip("()-").replace(",", ""))
    return -value if negative else value


def _year_tables(window: str) -> tuple[dict, int | None, int | None]:
    """(rows, first, last): the year-headed rows of the run of tables that starts first in
    the window, and where that run starts and ends."""
    rows: dict = {}
    first = last_end = None
    for table in _TABLE.finditer(window):
        # Once the projections have started, a table more than a few paragraphs on
        # belongs to something else: an adviser's analysis prints its own year-headed
        # tables, and its "Revenue" is the Street's, not management's.
        if last_end is not None and table.start() - last_end > _GAP:
            break
        years, took = None, False
        for row_html in _ROW.findall(table.group(0)):
            cells = _cells(row_html)
            found = [_YEAR_CELL.match(c) for c in cells]
            if sum(1 for f in found if f) >= 3:
                years = [int(f.group(1)) for f in found if f]
                continue
            if not years or len(cells) < 2:
                continue
            label, values = cells[0], cells[1:]
            numbers = [(_number(v), v) for v in values]
            if any(n is None for n, _ in numbers) or len(numbers) != len(years):
                continue
            entry = rows.setdefault(re.sub(r"\s*\(\d\)\s*$", "", label), {})
            if any(year in entry for year in years):
                continue                        # the same label again is another table's
            for year, (number, cell) in zip(years, numbers):
                entry[year] = (number, cell)
            took = True
        if took:
            first = table.start() if first is None else first
            last_end = table.end()
    return rows, first, last_end


_CASE_TERM = re.compile(
    r"[“\"]\s*((?:[A-Z0-9][\w’'\-/]*\s+){0,6}?(?:Projections?|Case|Forecasts?|Plan|"
    r"Scenario|Model))\s*[”\"]")
_RELIANCE = re.compile(r"(?i)\b(?:relied|reliance|rely|used|use)\b")
_OPINION = re.compile(r"(?i)\bopinions?\b|financial\s+analys[ie]s|fairness")
_NOT_RELIED = re.compile(r"(?i)\bnot\s+(?:\w+\s+){0,3}(?:rel[iy]|use)|\bno\s+reliance")
_UNRISKED = re.compile(r"(?i)\bun-?adjusted\b|\bnon-?risk[- ]adjusted\b|\bunrisked\b|"
                       r"\bnot\s+(?:been\s+)?(?:risk|probability)[- ]adjusted\b|"
                       r"\bwithout\s+(?:any\s+)?(?:risk|probability)\s+adjust")
_BASE_CASE = re.compile(r"(?i)\bbase\b|\bmanagement\s+(?:case|projections?|plan|forecasts?)\b")
_SIDE_CASE = re.compile(r"(?i)\bupside\b|\bdownside\b|\bsensitivit|\bbull\b|\bbear\b|"
                        r"\balternative\b|\bstretch\b|\bconservative\b|\blow\b|\bhigh\b")
_LATER_CASE = re.compile(r"(?i)\b(?:updated|revised|refreshed|final|amended)\b")
_SENTENCE_END = re.compile(r"(?<=[.;])\s+(?=[A-Z“\"(])")


def _case_tables(window: str) -> list[dict]:
    """The year-headed tables of a projections section split into the cases they print.

    A table opens a new case where the words before it name one (a defined term such as
    the "Base Case Projections"), or where it prints a year a row of the case before
    already printed. Otherwise it continues the case before, which is how a long
    projection runs over two tables. Each case keeps the words before its first table,
    which is where a filing says what the case is."""
    cases: list[dict] = []
    current, last_end = None, None
    for table in _TABLE.finditer(window):
        if last_end is not None and table.start() - last_end > _GAP:
            break
        rows, years = {}, None
        for row_html in _ROW.findall(table.group(0)):
            cells = _cells(row_html)
            found = [_YEAR_CELL.match(c) for c in cells]
            if sum(1 for f in found if f) >= 3:
                years = [int(f.group(1)) for f in found if f]
                continue
            if not years or len(cells) < 2:
                continue
            label, values = cells[0], cells[1:]
            numbers = [(_number(v), v) for v in values]
            if any(n is None for n, _ in numbers) or len(numbers) != len(years):
                continue
            entry = rows.setdefault(re.sub(r"\s*\(\d\)\s*$", "", label), {})
            if any(year in entry for year in years):
                continue
            for year, (number, cell) in zip(years, numbers):
                entry[year] = (number, cell)
        if not rows:
            continue
        before = window[last_end if last_end is not None else 0: table.start()]
        caption = _flat(_TAG.sub(" ", before))
        # The case the words just before the table name, else the last one named.
        terms = [m.group(1) for m in _CASE_TERM.finditer(caption)
                 if not _SECTION.fullmatch(m.group(1))]
        near = [m.group(1) for m in _CASE_TERM.finditer(caption[-600:])
                if not _SECTION.fullmatch(m.group(1))]
        name = near[0] if near else (terms[-1] if terms else None)
        overlaps = current is not None and any(
            year in current["rows"].get(label, {})
            for label, series in rows.items() for year in series)
        if current is None or overlaps or (name and name != current["name"]):
            current = {"name": name or (current["name"] if current and not overlaps
                                        else None),
                       "rows": {}, "caption": caption, "start": table.start()}
            cases.append(current)
        for label, series in rows.items():
            current["rows"].setdefault(label, {}).update(series)
        current["end"] = table.end()
        last_end = table.end()
    return cases


def _relied_names(text: str, names: list[str]) -> set:
    """The case names a sentence about the advisers' opinions or analyses says were
    relied on or used. Longer names first, so "Base Case Projections" is not also read
    as the umbrella "Projections"."""
    out: set = set()
    ordered = sorted({n for n in names if n}, key=len, reverse=True)
    for sentence in _SENTENCE_END.split(text):
        if not (_RELIANCE.search(sentence) and _OPINION.search(sentence)):
            continue
        if _NOT_RELIED.search(sentence):
            continue
        rest = sentence
        for name in ordered:
            if name in rest:
                out.add(name)
                rest = rest.replace(name, " ")
    return out


def _case_risk(case: dict, section_flag: bool) -> bool:
    """Whether a case is risk-adjusted: its own name first, then the words before its
    table, then what the section says of the projections as a whole."""
    for text in (case["name"] or "", case["caption"][-500:]):
        if _UNRISKED.search(text):
            return False
        if _RISK_ADJUSTED.search(text):
            return True
    return section_flag


def choose_case(found: dict, prefer_unrisked: bool = False) -> dict:
    """The case a draft takes, by a stated rule, with the reason in words.

    The case the target's board and financial advisers relied on for the fairness
    opinion; failing that, management's base case over an upside or a downside case;
    failing that, the most recent. ``prefer_unrisked`` first narrows the field to the
    unadjusted cases where the filing prints one, for a product in development: the
    engine applies the probability for the product's stage itself, and a risk-adjusted
    case would have it applied twice."""
    cases = found.get("cases") or []
    if not cases:
        return {}
    pool, notes = list(cases), []
    if prefer_unrisked and any(not c["risk_adjusted"] for c in cases) and any(
            c["risk_adjusted"] for c in cases):
        pool = [c for c in cases if not c["risk_adjusted"]]
        notes.append("the filing also prints a risk-adjusted case, and the unadjusted one "
                      "is taken so the engine's probability for the product's stage applies "
                      "once")

    def pick(case, reason):
        return {**case, "reason": "; ".join([reason] + notes)}

    if len(pool) == 1:
        case = pool[0]
        reason = ("the case the target's board and financial advisers relied on for the "
                  "fairness opinion" if case.get("relied") else
                  "the only case the filing prints" if len(cases) == 1 else
                  "the only case left")
        return pick(case, reason)
    relied = [c for c in pool if c.get("relied")]
    if len(relied) == 1:
        return pick(relied[0], "the case the target's board and financial advisers relied "
                               "on for the fairness opinion")
    pool = relied or pool
    side = [c for c in pool if _SIDE_CASE.search(c["name"] or "")]
    base = [c for c in pool if _BASE_CASE.search(c["name"] or "") and c not in side]
    if len(base) == 1 or (side and len(pool) - len(side) == 1):
        case = base[0] if len(base) == 1 else next(c for c in pool if c not in side)
        return pick(case, "management's base case, taken over the upside and downside "
                          "cases")
    later = [c for c in pool if _LATER_CASE.search(c["name"] or "")]
    case = later[-1] if later else max(pool, key=lambda c: c["start"])
    return pick(case, "the most recent of the cases the filing prints")


def with_case(found: dict, case: dict) -> dict:
    """``found`` read as one case: its rows, its caption and its risk."""
    return {**found, "rows": case["rows"], "caption": case["caption"][-300:].strip(),
            "risk_adjusted": case["risk_adjusted"], "case": case.get("name"),
            "case_reason": case.get("reason")}


def projections(html: str, prefer_unrisked: bool = False) -> dict | None:
    """The management projections a merger proxy or a 14D-9 prints, read off its tables.

    {rows: {label: {year: (value, cell)}}, unit, stated_unit, caption, risk_adjusted,
    section_text, cases, case, case_reason}: every value is a cell as printed, kept
    beside the number so a reader can find it, and the value is in millions whatever unit
    the filing prints in (Amicus printed billions). ``caption`` is the text just before
    the case's first table. None where the filing has no such section, or prints no
    year-headed revenue table after it, or does not say the amounts are in millions,
    since a figure without its unit is not a figure.

    The heading is printed more than once: in the contents, in the section itself, and
    in each adviser's opinion that relied on the projections. The tables read are the
    first any of them leads to, which are management's, since the advisers' analyses come
    after them; the heading nearest before them bounds the text read for the words
    around them, such as "risk-adjusted". Where the section prints several cases,
    ``choose_case`` takes one by its stated rule and ``cases`` lists them all.
    """
    best, unitless = None, None
    for heading in _SECTION.finditer(html or ""):
        window = html[heading.start(): heading.start() + 200_000]
        rows, first, last_end = _year_tables(window)
        # A projection runs five years or more; a historical table prints two or three.
        if not any(len(v) >= 5 for v in revenue_rows({"rows": rows}).values()):
            continue                            # a contents page, or another table
        # The unit is the one stated nearest before the first table of the run.
        if not _UNIT.search(_flat(_TAG.sub(" ", window[:last_end]))):
            unitless = unitless or rows
            continue
        at = heading.start() + first
        if best is None or at < best[0] or (at == best[0] and heading.start() > best[1]):
            best = (at, heading.start(), window, first)
    if best is None:
        # A table with no unit stated is reported as one, and nothing is read off it.
        return ({"rows": {}, "unit": None, "stated_unit": None, "caption": "",
                 "risk_adjusted": False, "section_text": "", "unitless": True,
                 "cases": [], "case": None, "case_reason": None}
                if unitless else None)
    window, first = best[2], best[3]
    cases = [c for c in _case_tables(window)
             if any(len(v) >= 5 for v in revenue_rows(c).values())]
    if not cases:
        return None
    end = max(c["end"] for c in cases)
    text = _flat(_TAG.sub(" ", window[:end]))
    before = _flat(_TAG.sub(" ", window[:first]))
    stated = [u for u in _UNIT.finditer(before)] or list(_UNIT.finditer(text))
    word = next(g for g in stated[-1].groups() if g).lower()
    scale = 1000.0 if word == "billions" else 1.0
    section_flag = bool(_RISK_ADJUSTED.search(text))
    relied = _relied_names(_flat(_TAG.sub(" ", window)), [c["name"] for c in cases])
    for case in cases:
        case["rows"] = {label: {year: (value * scale, cell)
                                for year, (value, cell) in series.items()}
                        for label, series in case["rows"].items()}
        case["risk_adjusted"] = _case_risk(case, section_flag)
        case["relied"] = case["name"] in relied
    found = {"unit": "mm USD", "stated_unit": word, "section_text": text,
             "cases": cases}
    return with_case(found, choose_case(found, prefer_unrisked))


def revenue_rows(found: dict | None) -> dict:
    """The projection rows that are revenue, by label."""
    if not found:
        return {}
    return {label: values for label, values in found["rows"].items()
            if _REVENUE_ROW.search(label) and not _NOT_REVENUE.search(label)}


REVENUE_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet")


def annual_revenue(facts: dict, before: str | None = None) -> list[dict]:
    """Full-year revenue the target filed on a 10-K, from its companyfacts, oldest first.

    One tag only, the one whose latest year is newest, so two tags are never mixed into one
    series. Each entry keeps its tag and accession so the quote can name the cell.
    """
    best: list = []
    for tag in REVENUE_TAGS:
        units = (((facts or {}).get("facts") or {}).get("us-gaap") or {}).get(tag) or {}
        series: dict = {}
        for fact in (units.get("units") or {}).get("USD", []):
            if fact.get("form") not in ("10-K", "10-K/A") or not fact.get("start"):
                continue
            days = (dt.date.fromisoformat(fact["end"]) -
                    dt.date.fromisoformat(fact["start"])).days
            if not 330 <= days <= 400 or (before and fact["end"] >= before):
                continue
            current = series.get(fact["end"])
            if current is None or fact.get("filed", "") > current["filed"]:
                series[fact["end"]] = {"end": fact["end"], "value": float(fact["val"]),
                                       "accession": fact.get("accn"), "tag": tag,
                                       "filed": fact.get("filed", ""),
                                       "fiscal_year": int(fact["end"][:4])}
        ordered = [series[k] for k in sorted(series)]
        if ordered and (not best or ordered[-1]["end"] > best[-1]["end"]):
            best = ordered
    return best


def target_filers(payload: dict, target: str) -> list[dict]:
    """The EDGAR full-text search hits filed by the target itself, newest first.

    A merger proxy names the target and a dozen precedent deals, so a hit counts only when
    the filer's own display name is the target's: "Metsera, Inc." filed the proxy that
    mentions Orbital, and that makes Metsera public, not Orbital.
    """
    out = []
    for hit in ((payload or {}).get("hits") or {}).get("hits") or []:
        source = hit.get("_source") or {}
        names = source.get("display_names") or []
        ciks = source.get("ciks") or []
        if not names or not ciks:
            continue
        display = re.sub(r"\s*\(CIK\s*\d+\)\s*$", "", names[0])
        display = re.sub(r"\s*\([A-Z.\-, ]+\)\s*$", "", display).strip()
        if not same_target(display, target):
            continue
        accession, _, filename = (hit.get("_id") or "").partition(":")
        out.append({"cik": str(int(ciks[0])), "name": display,
                    "form": source.get("form"), "root_form": (source.get("root_forms")
                                                              or [None])[0],
                    "accession": accession, "filename": filename,
                    "file_date": source.get("file_date")})
    return sorted(out, key=lambda h: h.get("file_date") or "", reverse=True)


def _words(name: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (name or "").lower()))


def marketed_labels(payload: dict, target: str) -> list[dict]:
    """The target's products on sale, from its openFDA drugsfda applications: an
    original approval on file and a product listed as prescription or over the counter.
    An application counts only where every word of its sponsor name is in the target's
    name, so "SOLENO" is Soleno Therapeutics and another company sharing a first word is
    not. One row per brand, its first approval kept, so a second strength or formulation
    is not a second product."""
    from fetchers.approvals_openfda import parse_drugsfda
    mine = _words(target)
    kept = {"results": [r for r in (payload or {}).get("results", [])
                        if _words(r.get("sponsor_name")) and
                        _words(r.get("sponsor_name")) <= mine]}
    out: dict = {}
    for row in parse_drugsfda(kept, ""):
        status = (row.get("marketing_status") or "").lower()
        if not row.get("brand") or ("prescription" not in status
                                    and "over-the-counter" not in status):
            continue
        key = row["brand"].lower()
        if key not in out or (row["approval_date"] or "9") < (out[key]["approval_date"]
                                                               or "9"):
            out[key] = row
    return sorted(out.values(), key=lambda r: r["approval_date"] or "")
