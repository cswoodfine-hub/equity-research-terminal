"""Tables from a filing's HTML with each cell's text runs marked bold or italic.

AstraZeneca's 20-F marks the molecule patent's year in bold and GSK's marks patents
other than the latest-expiring new molecular entity patent in italics; both marks are
lost when the filing is read as plain text. This keeps them: every cell is a list of
(text, bold, italic) runs, formatting taken from <b>/<strong>/<i>/<em> and from inline
font-weight and font-style, inherited from the enclosing element unless overridden.

    python3 -I html_tables.py <filing.htm> <word> [<word> ...]   # tables naming them, as JSON
"""
import html.parser, json, re, sys

WEIGHT = re.compile(r"font-weight\s*:\s*([a-z0-9]+)", re.I)
SLANT = re.compile(r"font-style\s*:\s*([a-z]+)", re.I)
VOID = {"br", "img", "hr", "meta", "input", "col", "link"}


class Tables(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.tables, self.depth = [], [], 0
        self.row = self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            if tag == "br" and self.cell is not None:
                self.cell.append(("\n", False, False))
            return
        # Formatting inherits from the parent and an explicit style overrides it, so a
        # span set to font-style:normal inside an italic cell reads as normal.
        style = dict(attrs).get("style") or ""
        _, bold, italic = self.stack[-1] if self.stack else (None, False, False)
        weight, slant = WEIGHT.search(style), SLANT.search(style)
        if tag in ("b", "strong"):
            bold = True
        if weight:
            w = weight.group(1).lower()
            bold = w in ("bold", "bolder") or (w.isdigit() and int(w) >= 600)
        if tag in ("i", "em"):
            italic = True
        if slant:
            italic = slant.group(1).lower() in ("italic", "oblique")
        self.stack.append((tag, bold, italic))
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.tables.append([])
        elif tag == "tr" and self.depth == 1:
            self.row = []
        elif tag in ("td", "th") and self.depth == 1 and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        while self.stack:
            top = self.stack.pop()[0]
            if top == tag:
                break
        if tag in ("td", "th") and self.cell is not None and self.depth == 1:
            self.row.append(self.cell); self.cell = None
        elif tag == "tr" and self.row is not None and self.depth == 1:
            if any(self.row):
                self.tables[-1].append(self.row)
            self.row = None
        elif tag == "table":
            self.depth -= 1

    def handle_data(self, data):
        if self.cell is None or not data.strip():
            return
        _, bold, italic = self.stack[-1] if self.stack else (None, False, False)
        self.cell.append((data.replace("​", ""), bold, italic))


def cell_text(cell):
    return re.sub(r"\s+", " ", "".join(t for t, _, _ in cell)).strip()


def tables(path):
    p = Tables()
    p.feed(open(path, encoding="utf-8", errors="replace").read())
    return p.tables


if __name__ == "__main__":
    words = [w.lower() for w in sys.argv[2:]]
    out = []
    for n, table in enumerate(tables(sys.argv[1])):
        text = " ".join(cell_text(c) for r in table for c in r).lower()
        if all(w in text for w in words):
            out.append({"table": n, "rows": [[[[t, b, i] for t, b, i in c] for c in r]
                                             for r in table]})
    json.dump(out, sys.stdout, ensure_ascii=False)
