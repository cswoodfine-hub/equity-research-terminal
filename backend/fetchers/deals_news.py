"""Business development from news headlines, for the deals the filings never name.

The filing extractor reads 10-Q and 10-K text, which names a counterparty only when the
deal is material enough to require it. That catches acquisitions and misses licensing:
of fourteen Lilly deals announced in the first four months of 2026, the filings route
found five, all of them acquisitions, and none of the eight licensing deals, including
an 8.85bn agreement with Innovent.

Every one of those was announced by press release on the day. Company IR feeds sit
behind bot protection and time out or refuse, so the free route that answers is the
Google News RSS search, which needs no key and returns the announcement with its date.

What this can do is bounded, and the bound is honest. A headline is not a filing: it
gives the parties and usually the headline value, never the upfront, and a publisher
writes it to be read rather than parsed. So the extraction is rules-only and
deliberately narrow, taking a deal only when a headline states one plainly, and the
headline is stored verbatim as the quote so any row can be checked against its source.
A deal already known from a filing is never duplicated.
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import db
import deals
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "deals_news"
NEWS_SOURCE = "news"
TTL_SECONDS = 12 * 60 * 60
_TIMEOUT_S = 30
_USER_AGENT = "NovatalisResearch/0.1 (contact cswoodfine@icloud.com)"
FEED = "https://news.google.com/rss/search"

# The verbs that state a deal, with the type each implies. Ordered longest first so
# "agrees to acquire" is read before "acquire".
_DEAL_VERBS = (
    (r"completes? (?:the )?acquisition of", "acquisition"),
    (r"agrees? to acquire", "acquisition"),
    (r"to acquire", "acquisition"),
    (r"acquires?", "acquisition"),
    (r"buys?", "acquisition"),
    (r"snaps? up", "acquisition"),
    (r"licen[sc]es?(?: rights)?(?: to| from)?", "licensing"),
    (r"licensing (?:deal|agreement|pact) with", "licensing"),
    (r"partners? with", "collaboration"),
    (r"collaborat(?:es?|ion) with", "collaboration"),
    (r"teams? up with", "collaboration"),
    (r"signs? (?:a )?(?:deal|agreement|pact) with", "collaboration"),
)

# A headline that asks a question or muses about the sector is commentary, not an
# announcement: "Why other Big Pharmas could follow Lilly into psychedelics".
_COMMENTARY = re.compile(
    r"\?|\bcould\b|\bmight\b|\bwhy\b|\brumou?r|\breportedly\b|\bexplores?\b"
    r"|\bweighs?\b|\bmulls?\b|\btalks\b|\bnears?\b|\bbid for\b|\banalysis\b|\bopinion\b"
    r"|\bstock market today\b|\bhere'?s a look\b|\bspree\b", re.I)

# "up to $3.8 billion", "$2.25B", "$950 million".
_VALUE = re.compile(
    r"(up to\s+)?\$\s?([\d,]+(?:\.\d+)?)\s*(billion|bn|b\b|million|mn|m\b)", re.I)

# A company name, matched case-sensitively: capitalised words, allowing &, - and .
# Case matters, so this part of the pattern is never matched with re.I. A headline says
# "acquires cancer therapy developer Arcellx", and only the capitals separate the
# company from the words describing it.
_NAME = r"(?P<who>[A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*){0,4})"

# What a publisher puts in front of the name: sector, nationality, and the shape of the
# thing bought. Trimmed from the front so "biotech Apogee Therapeutics" and "Apogee
# Therapeutics" are recognised as one deal rather than two.
_LEAD = {
    "of", "the", "a", "an", "its", "us", "u.s.", "uk", "u.k.", "eu",
    "biotech", "biotechnology", "biopharma", "biopharmaceutical", "pharma",
    "pharmaceutical", "pharmaceuticals", "drugmaker", "drug", "maker", "developer",
    "company", "firm", "startup", "start-up", "group", "business", "unit", "division",
    "cancer", "oncology", "gene", "cell", "therapy", "therapies", "vaccine", "clinical",
    "stage", "clinical-stage", "late-stage", "early-stage", "novel", "experimental",
    "american", "british", "canadian", "chinese", "danish", "dutch", "french", "german",
    "indian", "irish", "japanese", "swiss", "german's", "china's", "japan's",
    "germany's", "france's", "shares", "stake", "majority", "rights", "assets",
    "portion", "portfolio", "global", "u.s", "u.k", "us-based", "uk-based",
    "china-based", "based", "swiss-based", "boston", "houston", "waltham", "plano",
    "connecticut", "massachusetts", "california", "texas", "ai", "digital", "medical",
    "device", "obesity", "immunology", "inflammatory", "radiopharmaceutical",
}

# What a publisher hyphenates in front of a name, and the diseases it leads with.
# "Prostate Cancer Treatment-Maker Halda" is Halda described, not a company called that.
_DESCRIPTOR = re.compile(
    r"^(?:[\w']+-(?:maker|based|focused|backed|owned|led|stage|listed)|"
    r"prostate|breast|lung|kidney|liver|skin|blood|brain|rare|orphan|"
    r"weight[- ]loss|anti[- ]obesity|treatment|therapy|drug|medicine|vaccine|"
    r"antibody|radiopharma|neuro|cardio|derma|respiratory|autoimmune)$")

# A name that turns out to be the holder rather than the party. "argenx SE to acquire
# BIOG portfolio company, Forte Biosciences, Inc" names the trust that owns Forte, and
# the company being bought is the one after the phrase. Matched against what follows the
# captured name, so the reader steps over the holder and takes the next name.
_HOLDER = re.compile(
    r"^\s*(?:'s|\u2019s)?\s*(?:portfolio\s+compan(?:y|ies)|subsidiar(?:y|ies)|"
    r"affiliate|unit|division|arm|spin-?out|spin-?off|joint venture|group compan(?:y|ies)|"
    r"holding|majority[- ]owned)\b[,:;\s]*", re.I)

# Words a headline hangs off a name: "Innovent Biologics worth $8.85 billion".
_TAIL = {"worth", "for", "in", "to", "with", "and", "over", "at", "as", "on", "up",
         "valued", "after", "amid", "deal", "agreement", "pact", "programme",
         "program", "rights", "unit", "business", "assets", "inc", "inc.", "plc",
         "corporation", "corp", "corp.", "ltd", "ltd.", "sa", "nv", "ag"}

# Title case makes an ordinary word look like a company. None of these is one.
_NOT_A_NAME = {
    "to", "the", "its", "his", "her", "their", "while", "when", "after", "before",
    "shares", "share", "stock", "again", "rating", "deal", "three", "two", "first",
    "second", "new", "more", "most", "another", "women", "men", "market", "markets",
    "challenge", "expand", "advance", "strengthen", "boost", "build", "further",
    "agreement", "collaboration", "licensing", "partnership", "acquisition", "buy",
}


# "Lilly to acquire Kelonia Therapeutics to advance in vivo CAR-T cell therapies": the
# clause after the purpose verb is what the deal is for, in the announcement's words.
_AREA = re.compile(
    r"\bto\s+(?:advance|expand|accelerate|strengthen|develop|build|boost)\s+(.+)$"
    r"|\bfor the treatment of\s+(.+)$", re.I)
# The clause often runs on into the price or the publisher. Both are cut.
_AREA_TAIL = re.compile(
    r"\s*(?:\bin\b|\bfor\b|\bwith\b)?\s*(?:up to\s*)?\$.*$|\s*[|\u2013-]\s+\w+\s*$", re.I)


def parse_area(headline: str) -> str | None:
    """What the deal is for, taken verbatim from the headline, or None when it says.

    Title case is undone word by word rather than wholesale, so "Sleep-Wake Treatments"
    reads as prose while "CAR-T" and "AI" keep their capitals. Nothing is summarised or
    inferred: a headline that states no purpose gets no area.
    """
    match = _AREA.search(_clean_title(headline) or "")
    if not match:
        return None
    area = (match.group(1) or match.group(2) or "").strip()
    area = _AREA_TAIL.sub("", area).strip(" .,:;-")
    if not 4 <= len(area) <= 80:
        return None
    def unshout(word: str) -> str:
        # Per hyphen segment, so "Sleep-Wake" reads as prose and "CAR-T" keeps its case.
        return "-".join(p.lower() if p[:1].isupper() and p[1:].islower() else p
                        for p in word.split("-"))

    return " ".join(unshout(w) for w in area.split())


def _clean_title(title: str) -> str:
    """Google appends the publisher after a dash; the headline is what precedes it."""
    return re.sub(r"\s+-\s+[^-]+$", "", (title or "").strip())


def _publisher(title: str) -> str | None:
    """Who wrote it, from the tail _clean_title removes.

    A rumour is worth what its source is worth, so the publisher is stored beside the
    words rather than thrown away with the formatting.
    """
    match = re.search(r"\s+-\s+([^-]+)$", (title or "").strip())
    return match.group(1).strip() if match else None


def parse_value(headline: str) -> str | None:
    """The deal value as written, or None. Kept as text because a headline value is a
    headline value: "up to" almost always means milestones are included, and turning it
    into a number would lose the one word that says so."""
    match = _VALUE.search(headline or "")
    if not match:
        return None
    prefix, amount, unit = match.groups()
    unit = "billion" if unit.lower().startswith(("b", "bn")) else "million"
    return f"{'up to ' if prefix else ''}${amount} {unit}"


def _clean_name(raw: str) -> str | None:
    """The company inside a captured phrase, or None when the phrase names no company.

    A headline describes before it names: "acquires cancer therapy developer Arcellx".
    The description is trimmed from both ends, and what survives has to look like a name
    rather than a title-cased ordinary word, since "Buys Shares" is not a counterparty.
    """
    def token(word: str) -> str:
        return word.lower().strip(".,'\u2019")

    def describes(word: str) -> bool:
        """Whether a leading word describes the company rather than naming it.

        The set catches the plain ones. The pattern catches what a publisher hyphenates:
        "Prostate Cancer Treatment-Maker Halda" and "CT-based Halda Therapeutics" are the
        same company described two ways, and left in they read as two more.
        """
        low = token(word)
        return low in _LEAD or bool(_DESCRIPTOR.match(low))

    words = raw.strip(" .,'").split()
    # Stop before the last word: everything cannot be a description, and a company
    # genuinely called by a descriptor word keeps its name.
    while len(words) > 1 and describes(words[0]):
        words.pop(0)
    while words and token(words[-1]) in _TAIL:
        words.pop()
    if not words or token(words[0]) in _NOT_A_NAME:
        return None
    # Trimming "Ltd." off "Bio Palette Co., Ltd." leaves the comma behind it.
    name = " ".join(words).strip(" ,;:-")
    return name if len(name) >= 3 else None


def parse_deal(headline: str, company_names) -> dict | None:
    """{deal_type, counterparty, announced_value} from a headline, or None when it states no deal.

    The counterparty is the party that is not the company being searched for, which is
    why the company's own names are passed in: "Eli Lilly acquires Ajax Therapeutics"
    and "Ajax Therapeutics acquired by Eli Lilly" name the same two parties either way
    round, and only one of them is the counterparty.
    """
    text = _clean_title(headline)
    if not text or _COMMENTARY.search(text) or deals.NOT_OUR_DEAL.search(text):
        return None
    for verb, deal_type in _DEAL_VERBS:
        # The verb is read whatever its case; the name is not, so the capitals stay
        # meaningful. Hence the scoped flag rather than re.I over the whole pattern.
        match = re.search(rf"(?i:\b{verb})\s+{_NAME}", text)
        if not match:
            continue
        who = match.group("who")
        # The captured name can be the holder rather than the party: "acquire BIOG
        # portfolio company, Forte Biosciences". Step over the phrase and take the name
        # after it, which is the company actually changing hands.
        holder = _HOLDER.match(text[match.end():])
        if holder:
            after = re.match(_NAME, text[match.end() + holder.end():])
            if after:
                who = after.group("who")
        counterparty = _clean_name(who)
        # An organisation, not the thing being bought. The capital-letter match takes
        # whatever follows the verb, which for "Acquires Selective PDE10A Inhibitor" is
        # the asset and for "acquire China rights" is a market.
        if not counterparty or not deals.is_party(counterparty):
            continue
        # A headline naming the searched company after the verb is the passive voice
        # ("X acquired by Lilly"), which names no counterparty this way round.
        if any(n.lower() in counterparty.lower() for n in company_names):
            return None
        return {"deal_type": deal_type, "counterparty": counterparty,
                "announced_value": parse_value(text), "area": parse_area(text),
                "quote": text}
    return None


# --- deals nobody has announced ------------------------------------------------------
# What the commentary filter above throws away is almost all noise, and one thing a year
# that moves the whole sector: two large caps confirmed to be in merger talks. That is
# not a deal and must never be counted as one, but a reader who opens the terminal that
# morning and sees nothing has been failed by it.
#
# So the same headlines are read a second time under a far higher bar. A report qualifies
# only when it names a figure, that figure is enormous, and it names the other party.
# Everything short of that stays discarded.

# The verbs that say a deal is being discussed rather than done.
_TALKS = re.compile(
    r"\b(?:in (?:advanced )?talks|merger talks|weigh(?:s|ing)?|mull(?:s|ing)?"
    r"|explor(?:es|ing)|consider(?:s|ing)|approach(?:ed|es)|held talks"
    r"|near(?:s|ing)(?= a| an| deal| merger)|bid for|takeover (?:approach|interest)"
    r"|combin(?:e|ing) with|merge with|merger with)\b", re.I)

# What kind of thing is being discussed. A merger of two large caps is the case this lane
# exists for; a takeover reads the same way from the other side.
_TALKS_TYPE = ((r"merger|merge|combin", "merger"),
               (r"takeover|acquir|buy|bid", "acquisition"),
               (r"stake", "stake"))

# The bar, in dollars. Ten billion is roughly the point below which a reported deal is a
# business development story rather than a sector one, and above which both share prices
# move on the report alone. It is a stated threshold, not a scored one, so it can be
# argued with and changed in one place.
REPORTED_MIN_USD = 10e9

_MULTIPLIER = {"billion": 1e9, "bn": 1e9, "b": 1e9,
               "million": 1e6, "mn": 1e6, "m": 1e6}


def value_usd(headline: str) -> float | None:
    """The headline's figure as a number, or None where it states none."""
    match = _VALUE.search(headline or "")
    if not match:
        return None
    _, amount, unit = match.groups()
    try:
        return float(amount.replace(",", "")) * _MULTIPLIER[unit.lower().rstrip(".")]
    except (ValueError, KeyError):
        return None


def parse_reported(headline: str, company_names) -> dict | None:
    """{deal_type, counterparty, reported_value, reported_usd} for a reported deal.

    None unless the headline says a deal is being discussed, states a figure at or above
    the threshold, and names a counterparty that is not the company searched for. The
    headline is returned verbatim as the quote, because a report is worth exactly the
    words that were written and no summary of them.
    """
    text = _clean_title(headline)
    if not text or not _TALKS.search(text) or deals.NOT_OUR_DEAL.search(text):
        return None
    usd = value_usd(text)
    if usd is None or usd < REPORTED_MIN_USD:
        return None
    # The other party, taken the same way a confirmed deal takes it: the capitalised name
    # that is not the company being searched for.
    counterparty = None
    for match in re.finditer(_NAME, text):
        name = _clean_name(match.group("who"))
        if not name or not deals.is_party(name):
            continue
        if any(n.lower() in name.lower() or name.lower() in n.lower()
               for n in company_names):
            continue
        counterparty = name
        break
    if not counterparty:
        return None
    kind = next((label for pattern, label in _TALKS_TYPE
                 if re.search(pattern, text, re.I)), "deal")
    return {"deal_type": kind, "counterparty": counterparty,
            "reported_value": parse_value(text), "reported_usd": usd, "quote": text}


def _feed_url(company_name: str) -> str:
    # Merger and takeover terms ride along with the announced-deal words. Without them
    # the feed never returns a talks story, so the lane below would have nothing to read.
    query = (f'"{company_name}" (acquires OR acquisition OR licensing OR '
             f'collaboration OR partnership OR merger OR takeover OR "in talks")')
    return FEED + "?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})


def parse_feed(xml_text: str) -> list[dict]:
    """(title, link, published date) per item. Pure, so the parser is testable."""
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        when = None
        for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                when = dt.datetime.strptime(pub, fmt).date().isoformat()
                break
            except ValueError:
                continue
        if title:
            out.append({"title": title, "link": link, "date": when})
    return out


class DealsNewsFetcher(BaseFetcher):
    """One Google News search per company, headlines in, deals out."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, db_path=None, ticker: str | None = None):
        super().__init__(db_path)
        self.ticker = ticker.upper() if ticker else None

    @property
    def entity_key(self) -> str:
        return self.ticker or "universe"

    def fetch(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            sql = "SELECT id, ticker, name FROM companies"
            args = ()
            if self.ticker:
                sql += " WHERE ticker = ?"
                args = (self.ticker,)
            companies = [dict(r) for r in conn.execute(sql + " ORDER BY ticker", args)]
        finally:
            conn.close()
        feeds, errors = {}, []
        for company in companies:
            try:
                request = urllib.request.Request(
                    _feed_url(company["name"]), headers={"User-Agent": _USER_AGENT})
                with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                    feeds[company["ticker"]] = resp.read().decode("utf-8", "ignore")
            except Exception as exc:              # one company's feed, not the run
                errors.append(f"{company['ticker']}: {exc}")
        return {"feeds": feeds, "companies": companies, "errors": errors}

    def normalise(self, raw) -> list[dict]:
        by_ticker = {c["ticker"]: c for c in raw["companies"]}
        merged: dict[tuple, dict] = {}
        # Reported deals ride along on the same pass. They are kept apart from the first
        # character to the last: their own dict here, their own table on the way out, and
        # nothing that sums a deal value ever reads them.
        self.reported: dict[tuple, dict] = {}
        for ticker, xml_text in raw["feeds"].items():
            company = by_ticker[ticker]
            # The company's own names, so the passive voice is recognised rather than
            # read as a deal with itself.
            names = {company["name"], ticker,
                     company["name"].split()[0]} - {"The", "A"}
            try:
                items = parse_feed(xml_text)
            except ET.ParseError:
                continue
            for item in items:
                deal = parse_deal(item["title"], names)
                if not deal:
                    talk = parse_reported(item["title"], names)
                    if talk:
                        key = (ticker,
                               talk["counterparty"].split()[0].lower().strip(".,'"))
                        prior = self.reported.get(key)
                        # The biggest telling wins. Outlets round the same rumour
                        # differently and the largest figure is the one being discussed.
                        if prior is None or talk["reported_usd"] > prior["reported_usd"]:
                            self.reported[key] = {
                                **talk, "ticker": ticker,
                                "company_id": company["id"],
                                "event_date": item["date"],
                                "article_url": item["link"],
                                "publisher": _publisher(item["title"])}
                    continue
                row = {**deal, "ticker": ticker, "company_id": company["id"],
                       "event_date": item["date"], "source_url": item["link"]}
                # A dozen outlets write one deal a dozen ways: "Halda", "Halda
                # Therapeutics", "Connecticut biotech Halda Therapeutics". They share a
                # first word, which is the company, so that is the identity. The
                # tellings are then merged rather than counted: the earliest date, since
                # that is the announcement, the fullest name, and the first value any of
                # them printed.
                key = (ticker, row["counterparty"].split()[0].lower().strip(".,'"))
                seen = merged.get(key)
                if seen is None:
                    merged[key] = row
                    continue
                if row["event_date"] and (not seen["event_date"]
                                          or row["event_date"] < seen["event_date"]):
                    seen["event_date"] = row["event_date"]
                    seen["source_url"] = row["source_url"]
                    seen["quote"] = row["quote"]
                if len(row["counterparty"]) > len(seen["counterparty"]):
                    seen["counterparty"] = row["counterparty"]
                if seen["announced_value"] is None:
                    seen["announced_value"] = row["announced_value"]
                if seen["area"] is None:
                    seen["area"] = row["area"]
        return list(merged.values())

    def snapshot(self, rows: list[dict]) -> None:
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(conn, {"source": NEWS_SOURCE, "deals": len(rows)})
            conn.commit()
        finally:
            conn.close()

    def _write_snapshot(self, conn, payload) -> None:
        import json
        conn.execute(
            "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
            " refresh_run_id) VALUES (?, 'source', ?, ?, ?)",
            (self.source, self.entity_key, json.dumps(payload), self.refresh_run_id))

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM deals WHERE accession IS NULL").fetchone()[0]
            if n:
                self._write_snapshot(conn, {"source": NEWS_SOURCE, "deals": n,
                                            "fetch_kind": "cache"})
                conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        written = filled = redated = linked = 0
        try:
            for row in rows:
                # A deal already read out of a filing is the better record: it carries
                # the company's own words. News never overwrites it, and never repeats it.
                existing = conn.execute(
                    """
                    SELECT id, announced_value, area, event_date, article_url
                      FROM deals
                     WHERE company_id = ?
                       AND LOWER(COALESCE(counterparty, '')) = LOWER(?)
                    """, (row["company_id"], row["counterparty"])).fetchone()
                if existing:
                    # The filing's row stands, but a filing names the price far less
                    # reliably than it names the party: four of Lilly's April
                    # acquisitions were filed with no figure while every headline
                    # carried one. So a headline fills a blank size and records that it
                    # did, and never overwrites a figure the filing states.
                    if row["announced_value"] and existing["announced_value"] is None:
                        conn.execute(
                            "UPDATE deals SET announced_value = ?,"
                            "       announced_value_source = 'news' WHERE id = ?",
                            (row["announced_value"], existing["id"]))
                        filled += 1
                    # The filing row gains the announcement it was reported from, so
                    # the card can open the article rather than the 10-Q it sat in.
                    if not existing["article_url"]:
                        conn.execute("UPDATE deals SET article_url = ? WHERE id = ?",
                                     (row["source_url"], existing["id"]))
                        linked += 1
                    if row["area"] and not existing["area"]:
                        conn.execute("UPDATE deals SET area = ? WHERE id = ?",
                                     (row["area"], existing["id"]))
                    # A 10-Q dates every deal in it to the day it was filed. The
                    # headline carries the day the deal was announced, which is what
                    # this field means and is always the earlier of the two. Later is
                    # never taken: a recap is not an announcement.
                    if (row["event_date"] and existing["event_date"]
                            and row["event_date"] < existing["event_date"]):
                        conn.execute(
                            "UPDATE deals SET event_date = ?,"
                            "       event_date_source = 'news' WHERE id = ?",
                            (row["event_date"], existing["id"]))
                        redated += 1
                    continue
                conn.execute(
                    """
                    INSERT INTO deals (accession, company_id, deal_type, counterparty,
                                       announced_value, announced_value_source, area,
                                       event_date, event_date_source, quote, source_url,
                                       article_url, is_curated)
                    VALUES (NULL, ?, ?, ?, ?,
                            CASE WHEN ? IS NULL THEN NULL ELSE 'news' END,
                            ?, ?, 'news', ?, ?, ?, 0)
                    """,
                    (row["company_id"], row["deal_type"], row["counterparty"],
                     row["announced_value"], row["announced_value"], row["area"],
                     row["event_date"], row["quote"], row["source_url"],
                     row["source_url"]))
                written += 1

            # Reported deals, written last and written apart. A report that names a
            # counterparty the company has since actually done a deal with is dropped:
            # once it is announced, the rumour is history and the deal is the record.
            reported = 0
            for row in getattr(self, "reported", {}).values():
                done = conn.execute(
                    "SELECT 1 FROM deals WHERE company_id = ?"
                    "   AND LOWER(COALESCE(counterparty, '')) = LOWER(?)",
                    (row["company_id"], row["counterparty"])).fetchone()
                if done:
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO reported_deals
                        (company_id, counterparty, deal_type, reported_value,
                         reported_usd, quote, publisher, article_url, event_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (row["company_id"], row["counterparty"], row["deal_type"],
                     row["reported_value"], row["reported_usd"], row["quote"],
                     row["publisher"], row["article_url"], row["event_date"]))
                reported += 1
            conn.commit()
        finally:
            conn.close()
        notes = []
        if reported:
            notes.append(f"{reported} reported deals, unannounced and not counted as deals")
        if filled:
            notes.append(f"{filled} filed deals gained a size from a headline")
        if redated:
            notes.append(f"{redated} filed deals moved to their announcement date")
        if linked:
            notes.append(f"{linked} filed deals linked to their announcing article")
        return RefreshResult(self.source, written, [], False, 0, notes=notes)
