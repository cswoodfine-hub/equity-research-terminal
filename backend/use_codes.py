"""Orange Book patent use codes: their wording, read from FDA's patent pages.

The data files the Orange Book fetcher reads give a method-of-use patent's codes but not
what they mean. FDA's patent page for an application shows each code with its wording
as a tooltip:

    <a href="#" data-toggle="tooltip" ... title="TREATMENT OF TYPE 2 DIABETES MELLITUS
    IN COMBINATION WITH EXENATIDE">U-2139</a>

A code means the same on every product that lists it and does not change once defined,
so only codes the book holds without a definition are looked up, choosing the
applications that cover the most of them first.
"""

from __future__ import annotations

import html
import re

PAGE_URL = ("https://www.accessdata.fda.gov/scripts/cder/ob/patent_info.cfm"
            "?Product_No={product}&Appl_No={number}&Appl_type={kind}")

_CODE = re.compile(r'title="([^"]*)"\s*>\s*(U-\d+)\s*</a>', re.I)


def parse(page: str) -> dict:
    """{code: definition} from one patent page. A code with an empty title is left out:
    the page writes empty tooltips on paediatric extension rows."""
    out = {}
    for title, code in _CODE.findall(page or ""):
        text = re.sub(r"\s+", " ", html.unescape(title)).strip()
        if text:
            out[code.upper()] = text
    return out


def page_url(appl_code: str, product: str = "001") -> str | None:
    """The patent page for an application in the book's shape (NDA202293). None for
    anything else: only NDAs and ANDAs carry Orange Book patents."""
    m = re.fullmatch(r"(NDA|ANDA)(\d+)", (appl_code or "").upper())
    if not m:
        return None
    # The page wants six digits: NDA21549 reads as no patents at all, 021549 lists them.
    return PAGE_URL.format(product=product, number=m.group(2).zfill(6),
                           kind="N" if m.group(1) == "NDA" else "A")


def plan(needed: dict, limit: int | None = None) -> list[str]:
    """Applications to read, most missing codes first, until every code is covered or
    the limit is reached. ``needed`` is {application: set of codes}."""
    left = {code for codes in needed.values() for code in codes}
    order = []
    pool = {app: set(codes) for app, codes in needed.items() if app}
    while left and pool and (limit is None or len(order) < limit):
        app = max(sorted(pool), key=lambda a: len(pool[a] & left))
        gain = pool.pop(app) & left
        if not gain:
            break
        order.append(app)
        left -= gain
    return order
