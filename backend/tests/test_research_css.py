"""The shared research stylesheet: one file, two consumers, no stray colour.

``frontend/assets/research.css`` holds the primitives the research tabs share (the .u-
classes and the derived colour roles of design spec 9.1 and 9.8). The Streamlit page gets
it from ``theme.css()``, the Comps valuation component as its ``shared_css`` arg. These
tests keep it honest: every custom property it reads exists, it holds no colour literal
(every colour is a token or a mix of tokens), and both consumers carry the file's text
unchanged.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
sys.path.insert(0, str(FRONTEND))

import theme  # noqa: E402
from components import compsval  # noqa: E402

RESEARCH = FRONTEND / "assets" / "research.css"
TOKENS = FRONTEND / "assets" / "tokens.css"
HEX = re.compile(r"#[0-9A-Fa-f]{3,8}\b")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _defined(css: str) -> set:
    return set(re.findall(r"(--[\w-]+)\s*:", css))


def _root_blocks(css: str) -> list:
    """The bodies of every top-level ``:root { ... }`` rule. Custom properties hold no
    braces, so the first closing brace ends the block."""
    return re.findall(r"(?<![\w-]):root\s*\{([^{}]*)\}", css)


def _declaration_values(css: str) -> list:
    """Every declaration value, selectors left out, so an id selector can never read as
    a colour."""
    values = []
    for body in re.findall(r"\{([^{}]*)\}", css):
        for declaration in body.split(";"):
            if ":" in declaration:
                values.append(declaration.split(":", 1)[1])
    return values


def test_every_var_names_a_token_or_a_root_property_of_the_file():
    research = _strip_comments(RESEARCH.read_text())
    used = set(re.findall(r"var\(\s*(--[\w-]+)", research))
    assert used, "research.css reads no custom property at all"
    tokens = _defined(_strip_comments(TOKENS.read_text()))
    own_root = set()
    for block in _root_blocks(research):
        own_root |= _defined(block)
    missing = sorted(used - tokens - own_root)
    assert not missing, f"research.css reads undefined properties: {missing}"


def test_the_derived_properties_of_the_spec_sit_in_its_root():
    own_root = set()
    for block in _root_blocks(_strip_comments(RESEARCH.read_text())):
        own_root |= _defined(block)
    for name in ("--clinical", "--flag-wash", "--up-wash", "--down-wash", "--cf-bar",
                 "--hatch"):
        assert name in own_root, f"{name} is not defined in research.css :root"


def test_the_file_holds_no_hex_colour():
    research = RESEARCH.read_text()
    assert not HEX.findall(research), "a hex colour in research.css, comments included"
    stray = [v.strip() for v in _declaration_values(_strip_comments(research))
             if HEX.search(v)]
    assert not stray, f"hex colours in research.css declarations: {stray}"


def test_the_streamlit_page_carries_the_file_after_the_tokens():
    page = theme.css()
    text = RESEARCH.read_text()
    assert text in page, "theme.css() does not contain research.css"
    assert page.index("--ground:") < page.index(text), "research.css precedes the tokens"


def test_the_component_passes_the_same_text_as_shared_css(monkeypatch):
    captured = {}

    def fake_component(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(compsval, "_component", fake_component)
    compsval.comps_valuation({"schema": 1, "companies": []}, focal="LLY", engine="pharma",
                             tokens={"active": "#62A8D4"}, live=True)
    assert compsval.SHARED_CSS == RESEARCH.read_text()
    assert captured["shared_css"] == RESEARCH.read_text()
