"""Priority review vouchers sold, read out of the filing that reports the sale.

The FDA awards a transferable voucher on approval of a rare paediatric or tropical disease
drug, and the company sells it. Abeona sold the one it was awarded for ZEVASKYN for 155m
gross, against a balance sheet of 226m. That is two thirds of the company's cash arriving
from a source nothing else in this repository records: it is not revenue, so no product
carries it; it is not a financing, because no security was issued and nobody was diluted;
XBRL tags the gain rather than the sale, and the gain nets off a carrying value that is
usually zero and occasionally not.

Eleven companies in the universe state one. For a company with two years of cash and no
product, a voucher is the difference between filing on its own terms and filing because
it has to.

Two rules keep it honest. A figure counts only where it is bound to a proceeds phrase in
the same sentence as the voucher, because a press release reporting a voucher sale also
reports the quarter, and the largest number near the word "voucher" is usually the
quarter's cash. And gross and net are stored in separate columns, neither derived from the
other: Abeona printed 155.0m gross and a 152.4m net gain, and inferring one from the other
would mean choosing a fee that no filing stated.
"""

from __future__ import annotations

import re

# The voucher itself. "PRV" is required to stand alone so "PRVs" in a sentence about the
# market for them still matches while a word ending in those letters does not.
_VOUCHER = re.compile(r"priority review voucher|\bPRVs?\b", re.I)

# The company parted with it. Without this, every filing that merely mentions holding a
# voucher, or being eligible for one, reads as a sale.
_SOLD = re.compile(
    r"\b(sold|sale|sell|selling|monetis|monetiz|divest|transferred|"
    r"purchase agreement|entered into an agreement to sell)", re.I)

# What the money is called. The figure has to sit against one of these, in this sentence.
_GROSS = re.compile(r"\bgross proceeds\b|\bfor (?:total )?(?:cash )?consideration\b"
                    r"|\bsale price\b|\bpurchase price\b", re.I)
_NET = re.compile(r"\bnet proceeds\b|\bnet cash payment\b|\bnet of transaction\b"
                  r"|\bproceeds,? net\b|\bnet of\b", re.I)
# A press release states the price without saying which side of the fee it is on: "sold
# the voucher for $100 million". Only these two forms, because "received" and a bare
# "for" bind to whatever number is nearest and in a cash flow statement that is the wrong
# one. Read as gross, since a figure a seller announces is before fees and gross is the
# column that claims the less.
_PLAIN = re.compile(r"\bproceeds\b|\bfor\s*\$", re.I)

# A cash flow statement names the voucher beside every other investing line, so the
# sentence has a voucher in it, a sale in it, and four figures that are not the price:
# "gain on sale of priority review voucher of $152.4 million, proceeds from maturities of
# short-term investments of $118.8 million". Roll-up language is the tell, and a sentence
# carrying it is left to the press release that reported the sale plainly.
_ROLLUP = re.compile(
    r"\b(investing activities|operating activities|financing activities|"
    r"maturities of|purchases of|non-?cash (?:charges|adjustments)|"
    r"offset by|consisted (?:primarily )?of|adjustments included)\b", re.I)

_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(million|billion)\b", re.I)
_SCALE = {"million": 1e6, "billion": 1e9}

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_WHEN = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(?:\d{1,2},\s*)?(\d{4})\b", re.I)

# A sale is one sentence. Splitting on the sentence rather than taking a window is what
# stops a figure from the next paragraph being read as the price.
_SENTENCE = re.compile(r"(?<=[.;:])\s+|\n")

# How far from the proceeds phrase a figure may sit and still be its figure.
BIND_WINDOW = 90

# What a voucher has ever sold for, in dollars. Awards began in 2009 and the range since
# has run from about 67m to 350m. The bound is a guard against reading the quarter's cash
# or a market's size as a price, not a claim about what one is worth: a real sale outside
# it is reported rather than stored, which is the failure this can afford.
PRICE_FLOOR, PRICE_CEILING = 20e6, 400e6


def _figure(sentence: str, marker) -> float | None:
    """The money bound to a proceeds phrase, forward first then back.

    "gross proceeds of $155 million" is the commoner order; "received $100.0 million in
    net proceeds" is the other one.
    """
    if marker is None:
        return None
    ahead = _MONEY.search(sentence, marker.end(), marker.end() + BIND_WINDOW)
    behind = None
    for match in _MONEY.finditer(sentence[max(0, marker.start() - BIND_WINDOW):
                                          marker.start()]):
        behind = match
    match = ahead or behind
    if not match:
        return None
    value = float(match.group(1).replace(",", "")) * _SCALE[match.group(2).lower()]
    return value if PRICE_FLOOR <= value <= PRICE_CEILING else None


def _month(text: str, near: int, low: str = "", high: str = "") -> str | None:
    """The month of the sale: the one nearest the sentence that could be it."""
    best, closest = None, None
    for match in _WHEN.finditer(text):
        month = (f"{int(match.group(2)):04d}-"
                 f"{_MONTHS.index(match.group(1).lower()) + 1:02d}")
        if low and month <= low:
            continue
        if high and month > high:
            continue
        gap = min(abs(match.start() - near), abs(match.end() - near))
        if closest is None or gap < closest:
            closest, best = gap, month
    return best


def sales(text: str, filed_month: str = "") -> list:
    """Every voucher sale the text states, as {gross_usd, net_usd, month, evidence}.

    A sentence naming a voucher, saying it was sold, and binding a figure to a proceeds
    phrase. Anything short of all three is not stored.
    """
    text = (text or "").replace(" ", " ")
    out, seen = [], set()
    for raw in _SENTENCE.split(text):
        sentence = re.sub(r"\s+", " ", raw).strip()
        if not sentence or not _VOUCHER.search(sentence) or not _SOLD.search(sentence):
            continue
        if _ROLLUP.search(sentence):
            continue
        gross = _figure(sentence, _GROSS.search(sentence))
        net = _figure(sentence, _NET.search(sentence))
        if gross is None and net is None:
            # Neither word appears, so the bare form: "sold the voucher for $100 million".
            gross = _figure(sentence, _PLAIN.search(sentence))
        if gross is None and net is None:
            continue
        key = (gross, net)
        if key in seen:
            continue                     # the same sale restated further down the page
        seen.add(key)
        month = _month(text, text.find(raw), high=filed_month)
        out.append({"gross_usd": gross, "net_usd": net,
                    "month": month or filed_month or None,
                    "evidence": sentence[:400]})
    return [row for row in out if row["month"]]


# When two statements are the same sale. A company announces the sale, then restates it in
# the next quarterly report and again in the annual one, each time with the figure it is
# reporting: Abeona printed 155.0m gross in May and a 152.4m net gain in September and
# December. Within a few per cent and within eighteen months is one sale seen three times;
# further apart than that is two vouchers, which Sarepta has genuinely done.
SAME_SALE_RATIO = 0.08
SAME_SALE_MONTHS = 18


def _months_apart(a: str, b: str) -> int:
    ay, am = int(a[:4]), int(a[5:7])
    by, bm = int(b[:4]), int(b[5:7])
    return abs((ay - by) * 12 + (am - bm))


def merge(rows: list) -> list:
    """One row per sale, from every statement of it.

    The earliest month, because that is when the money arrived rather than when it was
    last mentioned. The gross and the net each from whichever statement gave one, so a
    sale announced gross and restated net ends up with both and neither is inferred.
    """
    clusters: list = []
    for row in sorted(rows, key=lambda r: r["month"]):
        value = row["gross_usd"] or row["net_usd"]
        for cluster in clusters:
            anchor = cluster["gross_usd"] or cluster["net_usd"]
            if (abs(value - anchor) <= anchor * SAME_SALE_RATIO
                    and _months_apart(row["month"], cluster["month"]) <= SAME_SALE_MONTHS):
                cluster["gross_usd"] = cluster["gross_usd"] or row["gross_usd"]
                cluster["net_usd"] = cluster["net_usd"] or row["net_usd"]
                break
        else:
            clusters.append(dict(row))
    return clusters


def _sources(conn, company_id: int) -> list:
    """The filing text worth reading for a voucher sale, newest first.

    A sale is announced in the press release and then repeated in the next annual report,
    so both are read and the duplicate is dropped on the figures rather than on the form.
    """
    return conn.execute(
        "SELECT text, accession, form_type, filed_date, section FROM filing_sections"
        "  WHERE company_id = ? AND section IN ('exhibit', 'exhibit_2', 'exhibit_3',"
        "                                       'body', 'mdna')"
        "  ORDER BY filed_date DESC LIMIT 40", (company_id,)).fetchall()


def build(db_path=None) -> dict:
    """Read every company's filings for a voucher sale and record what they state.

    Rebuilt each run rather than appended to, the same way financings is: the source is
    the filing text, so a re-read is the whole answer and a stale row from a superseded
    parse should not survive it.
    """
    import db

    conn = db.get_connection(db_path)
    written = 0
    try:
        conn.execute("DELETE FROM priority_review_vouchers")
        for company in conn.execute("SELECT id FROM companies"):
            found = []
            for source in _sources(conn, company["id"]):
                for sale in sales(source["text"], (source["filed_date"] or "")[:7]):
                    found.append({**sale, "accession": source["accession"],
                                  "form_type": source["form_type"],
                                  "filed_date": source["filed_date"],
                                  "section": source["section"]})
            for sale in merge(found):
                conn.execute(
                    "INSERT INTO priority_review_vouchers"
                    "  (company_id, sold_month, gross_usd, net_usd, evidence,"
                    "   accession, form_type, filed_date, section)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (company["id"], sale["month"], sale["gross_usd"],
                     sale["net_usd"], sale["evidence"], sale["accession"],
                     sale["form_type"], sale["filed_date"], sale["section"]))
                written += 1
        conn.commit()
    finally:
        conn.close()
    return {"written": written}


def since_balance_sheet(conn, company_id: int, as_of: str) -> dict:
    """{total, rows} of voucher sales that closed after this balance sheet date.

    Net where the filing states it, gross where it does not. The alternative is to drop a
    sale whose fee was never printed, and a voucher missing from a runway is a larger
    error than a fee counted on the wrong side of it.
    """
    rows = [dict(r) for r in conn.execute(
        "SELECT sold_month, gross_usd, net_usd, evidence, filed_date, form_type"
        "  FROM priority_review_vouchers WHERE company_id = ? AND sold_month > ?"
        "  ORDER BY sold_month", (company_id, (as_of or "")[:7]))]
    total = sum((r["net_usd"] or r["gross_usd"] or 0) for r in rows)
    return {"total": total or None, "rows": rows}
