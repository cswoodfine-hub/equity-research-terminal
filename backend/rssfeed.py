"""RSS parsing and company matching, the pure half of the announcement feeds.

The network fetch lives in the fetcher; this turns a feed's XML into items and
decides which company an item names. Matching is conservative: a company is matched
only on a distinctive token, its ticker, or one of its tracked brand names, at a word
boundary, so a press release that happens to contain a common word does not bind to
the wrong name. An item that names nobody is kept with no company, so a universe view
can still show it and nothing is silently dropped.
"""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET


def parse_feed(xml_text: str) -> list[dict]:
    """Items from an RSS 2.0 feed: title, url, published (ISO date), summary. Pure."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        if not link or not title:
            continue
        items.append({
            "title": title,
            "url": link,
            "published": _to_iso(item.findtext("pubDate")),
            "summary": re.sub(r"<[^>]+>", " ",
                              (item.findtext("description") or "")).strip()[:500],
        })
    return items


def _to_iso(pub_date) -> str | None:
    """RFC 822 pubDate to an ISO date, or None. FDA feeds use e.g.
    'Fri, 17 Jul 2026 12:00:00 EST'."""
    if not pub_date:
        return None
    cleaned = re.sub(r"\s+[A-Z]{2,4}$", "", pub_date.strip())
    for fmt in ("%a, %d %b %Y %H:%M:%S", "%a, %d %b %Y %H:%M", "%d %b %Y"):
        try:
            return dt.datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# Name words too generic to match on alone. A company is still matched on its ticker,
# a distinctive name token, or a brand.
_STOP = {"the", "and", "company", "inc", "corp", "co", "plc", "ag", "sa", "group",
         "pharmaceuticals", "pharma", "holdings", "laboratories", "limited", "ltd"}

# Single words that turn up in the brand_name field but never single out one drug: a
# business segment, a dosage word, or a generic ingredient the product-revenue parser
# wrote in as a stray brand. Matching a press release on one of these binds it to the
# wrong company, so none stands as a brand token on its own.
_GENERIC_BRAND = {
    "advanced", "general", "surgical", "electrophysiology", "hips", "knees",
    "antibodies", "vaccine", "vaccines", "biosimilar", "biosimilars", "influenza",
    "launches", "children", "liver", "tablets", "tablet", "solution", "capsules",
    "cefazolin", "acetaminophen", "naproxen", "sodium",
}


def _brand_token(brand: str) -> str | None:
    """The single coined word that marks a brand, or None. A real single-drug brand is
    one coined word (Tzield, Xofluza, Darzalex). A brand_name with a space is a
    revenue-line label or a two-drug combo (Diovan Group, Liver Disease Products
    Vemlidy, Naproxen Sodium); there is no safe way to tell which word is the brand, so
    it is dropped rather than guessed. A lone segment, dosage, or ingredient word is
    dropped too."""
    b = (brand or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z-]{3,}", b):   # one word, four+ letters
        return None
    if b.lower() in _GENERIC_BRAND:
        return None
    return b


def company_tokens(name: str, ticker: str, brands: list[str]) -> list[str]:
    """The distinctive strings that mark a company in free text: the ticker, the
    non-generic words of its name, and its brand names, each at least four characters
    so a short common word cannot match."""
    tokens = {ticker.upper()}
    for word in re.findall(r"[A-Za-z][A-Za-z-]{3,}", name or ""):
        if word.lower() not in _STOP:
            tokens.add(word)
    for brand in brands or []:
        token = _brand_token(brand)
        if token:
            tokens.add(token)
    return sorted(tokens)


def match_company(text: str, token_map: dict) -> int | None:
    """The company id whose token appears in ``text`` at a word boundary, or None.

    ``token_map`` is {company_id: [tokens]}. The first match wins; tokens are
    distinctive enough that overlap is rare, and a brand is unique to its owner.
    """
    haystack = (text or "").upper()
    for company_id, tokens in token_map.items():
        for token in tokens:
            if re.search(rf"\b{re.escape(token.upper())}\b", haystack):
                return company_id
    return None
