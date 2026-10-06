"""EDGAR reads for a closed acquisition: the acquirer's current report, the target's
filings found by full-text search, its merger proxy or 14D-9, and its company facts.

Four endpoints, all EDGAR, all keyless, all needing the User-Agent every EDGAR request
sends, and paced well under ten requests a second:

- a filing's primary document and its exhibit 99 press releases, from the filing's own
  ``-index.html``;
- full-text search, ``https://efts.sec.gov/LATEST/search-index?q=&forms=&dateRange=
  custom&startdt=&enddt=``, the JSON service behind EDGAR's own full-text search page
  (www.sec.gov/edgar/search). It is how a target that has since delisted is found: the
  ticker map lists only current registrants, and a closing usually ends the target's
  listing. Each hit carries the filer's CIK and display name, the form and the accession
  with the file name;
- ``https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{file}`` for the proxy;
- ``https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json`` for revenue.

Parsing lives in ``closings.py``, so this module only reads.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import filingtext

_TIMEOUT_S = 60
_SLEEP_S = 0.15                    # under ten requests a second
SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{filename}"
# The forms a target files that make it public, and the two that carry projections.
TARGET_FORMS = ("DEFM14A", "SC 14D9", "10-K")
PROXY_FORMS = ("DEFM14A", "SC 14D9")
_EXHIBIT_ROW = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>\d+</td>\s*<td[^>]*>[^<]*</td>\s*"
    r"<td[^>]*><a href=\"([^\"]+)\">[^<]*</a>[^<]*(?:<(?!/tr>)[^>]+>[^<]*)*</td>\s*"
    r"<td[^>]*>(EX-99[^<]*)</td>", re.I | re.S)


class Edgar:
    """A polite EDGAR reader. ``opener(url) -> str`` replaces the network in tests."""

    def __init__(self, user_agent: str | None = None, opener=None,
                 sleep: float = _SLEEP_S):
        self.user_agent = (user_agent or os.getenv("SEC_USER_AGENT") or "").strip()
        if opener is None and not self.user_agent:
            raise RuntimeError("SEC_USER_AGENT is not set; EDGAR blocks anonymous requests")
        self._opener = opener
        self._sleep = sleep
        self.requests = 0

    def get(self, url: str) -> str:
        self.requests += 1
        if self._opener is not None:
            return self._opener(url)
        # Full-text search answers a burst with an occasional 500 that the same request
        # a second later does not get, so a server error is tried twice more.
        for attempt in range(3):
            time.sleep(self._sleep if attempt == 0 else 2.0 * attempt)
            request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            try:
                with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                    return resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                if exc.code < 500 or attempt == 2:
                    raise
        raise RuntimeError(f"unreachable: {url}")

    def current_report(self, primary_url: str) -> list[tuple[str, str]]:
        """[(section, text)]: the primary document, then each exhibit 99 it furnishes."""
        out = [("body", filingtext.html_to_text(self.get(primary_url)))]
        directory = primary_url.rsplit("/", 1)[0] + "/"
        folder = directory.rstrip("/").rsplit("/", 1)[-1]
        if not (len(folder) == 18 and folder.isdigit()):
            return out
        accession = f"{folder[:10]}-{folder[10:12]}-{folder[12:]}"
        try:
            page = self.get(f"{directory}{accession}-index.html")
        except Exception:
            return out
        for index, (href, _kind) in enumerate(_EXHIBIT_ROW.findall(page)[:3]):
            href = href[len("/ix?doc="):] if href.startswith("/ix?doc=") else href
            url = f"https://www.sec.gov{href}" if href.startswith("/") else directory + href
            try:
                out.append((filingtext.exhibit_section(index),
                            filingtext.html_to_text(self.get(url))))
            except Exception:
                continue
        return out

    def search(self, phrase: str, forms=TARGET_FORMS, start: str | None = None,
               end: str | None = None) -> dict:
        query = {"q": f'"{phrase}"', "forms": ",".join(forms)}
        if start and end:
            query.update({"dateRange": "custom", "startdt": start, "enddt": end})
        return json.loads(self.get(f"{SEARCH_URL}?{urllib.parse.urlencode(query)}"))

    def document(self, cik: str, accession: str, filename: str) -> str:
        return self.get(ARCHIVE_URL.format(cik=int(cik), folder=accession.replace("-", ""),
                                           filename=filename))

    def companyfacts(self, cik: str) -> dict:
        return json.loads(self.get(FACTS_URL.format(cik=int(cik))))


def document_url(cik: str, accession: str, filename: str) -> str:
    return ARCHIVE_URL.format(cik=int(cik), folder=accession.replace("-", ""),
                              filename=filename)
