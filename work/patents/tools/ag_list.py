"""FDA's Listing of Authorized Generics, as {brand: earliest year an AG was reported}.

The list (a PDF on fda.gov, issue of 2026-10-05 read here) is built from NDA holders'
annual reports since 1999. FDA says the date column is the period of the annual report
that first mentioned the authorised generic, not the day it launched, so only the year
is kept, and the earliest one per brand. Entries are numbered; each runs from its
number to the next.

    python3 work/patents/tools/ag_list.py <ag.pdf>       # prints the parsed brands
"""

import re
import sys

PDF_URL = "https://www.fda.gov/media/77725/download"

_ENTRY = re.compile(r"(?:^|\n)\s*(\d{1,4})\s{2,}(?=[A-Z0-9])")
_DATE = re.compile(r"\b(?:\d{1,2}/)?(?:\d{1,2}/)?((?:19|20)\d{2})\b")


def parse(text: str) -> dict:
    """{brand name, upper case: earliest reported year}. Pure."""
    marks = list(_ENTRY.finditer(text))
    out = {}
    for i, m in enumerate(marks):
        chunk = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        name = re.split(r"\s{2,}", chunk.strip(), maxsplit=1)[0].strip()
        if not name or not re.match(r"^[A-Z0-9][A-Z0-9 \-.,/&'+®]*$", name):
            continue
        # The date column is last; a strength rarely reads as a year, and taking the
        # last date-like token keeps a 2005 strength out of it.
        years = [int(y) for y in _DATE.findall(chunk)]
        if not years:
            continue
        year = years[-1] if len(years) == 1 else min(years[-2:])
        name = " ".join(name.split())
        if name not in out or year < out[name]:
            out[name] = year
    return out


def load(pdf_path) -> dict:
    import pypdf
    reader = pypdf.PdfReader(pdf_path)
    return parse("\n".join(p.extract_text() or "" for p in reader.pages))


if __name__ == "__main__":
    found = load(sys.argv[1])
    print(len(found), "brands")
    for name in ("ALLEGRA", "SYMBICORT", "LIPITOR", "CRESTOR", "PLAVIX", "LYRICA",
                 "JANUVIA", "ZYTIGA", "ADVAIR DISKUS", "SPRYCEL", "VIAGRA", "CIALIS"):
        print(f"  {name}: {found.get(name)}")
