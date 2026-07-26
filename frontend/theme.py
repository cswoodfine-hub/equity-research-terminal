"""Design system: palette, type, chart theme, and number formatting.

The palette is the token set in ``components/tokens.py`` (mirrored in
``assets/tokens.css``): six values plus the phase ramp, nothing else. Ground and
panel build every piece of chrome; hue is spent only on encoded meaning: direction,
modality, materiality, and the phase ramp. Colour is never the only signal; every
coloured mark also carries a label, glyph, or position.

Type has three roles, bundled locally in ``assets/fonts`` and inlined as
``@font-face`` so nothing loads from a CDN. Structure and UI take Archivo (Archivo
Narrow for dense table headers); figures, tickers and dates take IBM Plex Mono with
tabular numerals; the written note alone takes Newsreader, so analyst prose reads as
research rather than as chrome.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from pathlib import Path

from components import tokens as TK

_ASSETS = Path(__file__).resolve().parent / "assets"


@dataclass(frozen=True)
class Palette:
    """One set of colour roles. Legacy field names kept so every module shifts
    palette in one move: ink is the text token, data is the up token, oxblood the
    down token, stale the muted token, raised the panel token."""

    name: str
    ground: str          # the absence of signal
    ink: str             # text, rules, axes
    data: str            # a plotted series and the positive direction
    orange_book: str     # small-molecule modality
    purple_book: str     # biologic modality
    oxblood: str         # negative direction and high severity, single pole
    stale: str           # secondary text, past-TTL values
    rule: str            # hairline
    rule_strong: str     # structural hairline
    raised: str          # raised surface
    flag: str            # material change, needs review, uncurated
    phase_tints: tuple   # continuous heatmap stops, ground toward data

    @property
    def modality(self) -> dict:
        return {"small molecule": self.orange_book, "biologic": self.purple_book}

    @property
    def severity(self) -> dict:
        return {"high": self.oxblood, "medium": self.ink, "low": self.stale}

    @property
    def muted(self) -> str:
        """Body text one step down from ink. Captions and secondary labels."""
        return self.stale if self.name == "dark" else "#5A564E"


# Retained for the ramp tests and as the record of the pre-terminal palette. The
# running app always uses DARK, which is the token set.
LIGHT = Palette(
    name="light", ground="#F2EFE9", ink="#1C1B19", data="#116765",
    orange_book="#B04E0C", purple_book="#5B4B8A", oxblood="#8C2F39", stale="#6E6A61",
    rule="#DCD7CC", rule_strong="#B9B3A6", raised="#EDE9E1", flag="#9A7B2F",
    phase_tints=("#DCE8E7", "#A9CFCD", "#6FAFAC", "#37827F", "#116765"),
)

DARK = Palette(
    name="dark", ground=TK.GROUND, ink=TK.TEXT, data=TK.UP,
    orange_book=TK.ORANGE_BOOK, purple_book=TK.PURPLE_BOOK, oxblood=TK.DOWN,
    stale=TK.MUTED, rule=TK.RULE, rule_strong=TK.RULE_STRONG, raised=TK.PANEL,
    flag=TK.FLAG,
    # Continuous stops for density heatmaps, ground toward the data colour.
    phase_tints=("#122122", "#1C3A36", "#2A5A4E", "#3B7A64", TK.UP),
)

P = DARK

# --- Type roles -----------------------------------------------------------
DISPLAY = TK.FONT_PROSE      # the note prose only
BODY = TK.FONT_UI            # structure and UI
NARROW = TK.FONT_UI_NARROW   # dense table headers
MONO = TK.FONT_MONO          # figures, tickers, dates, identifiers

# family name -> filename stem prefix in assets/fonts
_FONT_FILES = (
    ("Archivo", 400, "archivo-latin-400-normal.woff2"),
    ("Archivo", 500, "archivo-latin-500-normal.woff2"),
    ("Archivo", 600, "archivo-latin-600-normal.woff2"),
    ("Archivo", 700, "archivo-latin-700-normal.woff2"),
    ("Archivo Narrow", 600, "archivo-narrow-latin-600-normal.woff2"),
    ("IBM Plex Mono", 400, "ibm-plex-mono-latin-400-normal.woff2"),
    ("IBM Plex Mono", 500, "ibm-plex-mono-latin-500-normal.woff2"),
    ("IBM Plex Mono", 600, "ibm-plex-mono-latin-600-normal.woff2"),
    ("Newsreader", 400, "newsreader-latin-400-normal.woff2"),
    ("Newsreader", 500, "newsreader-latin-500-normal.woff2"),
)


def _font_faces() -> str:
    """Bundled fonts as inline @font-face rules. Base64 keeps them one file with the
    stylesheet, which sidesteps static-file serving entirely; a missing file falls
    back to the system stack rather than erroring."""
    faces = []
    for family, weight, filename in _FONT_FILES:
        path = _ASSETS / "fonts" / filename
        if not path.exists():
            continue
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        faces.append(
            f"@font-face {{ font-family: '{family}'; font-weight: {weight}; "
            f"font-style: normal; font-display: swap; "
            f"src: url(data:font/woff2;base64,{data}) format('woff2'); }}")
    return "\n".join(faces)


_FONT_FACE_CSS = _font_faces()
_TOKENS_CSS = (_ASSETS / "tokens.css").read_text()


def css() -> str:
    """Scoped stylesheet: tokens, fonts, shell, and every component class."""
    tokens_root = _TOKENS_CSS.replace("/* Design tokens. Mirrored in "
                                      "components/tokens.py; a test keeps the two in "
                                      "step.\n   No colour or spacing value may be "
                                      "hardcoded outside these two files. */\n", "")
    return f"""
<style>
{_FONT_FACE_CSS}
{tokens_root}

/* Legacy variable names, aliased onto the tokens so existing rules keep reading. */
:root {{
  --ink: var(--text); --stale: var(--muted);
  --oxblood: var(--down); --data: var(--up);
}}

html, body, [class*="css"], .stApp {{
  background: var(--ground);
  color: var(--text);
  font-family: var(--font-ui);
  /* Base size, and the rem root: headings and the large figures are in rem, so they
     scale with this; a modest bump lifts the whole UI's legibility at once. */
  font-size: 14px;
  -webkit-font-smoothing: antialiased;
}}

/* Every figure holds its column when values change on refresh. */
.stApp, table, td, th, .stMetric, [data-testid="stMetricValue"], .num, .mono {{
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1, "lnum" 1;
}}

header[data-testid="stHeader"] {{ background: transparent !important; }}
[data-testid="stToolbar"] {{ right: 0.6rem; }}

/* Density: an instrument, not a landing page. 8px base scale. */
[data-testid="stMainBlockContainer"], .block-container {{
  padding: 3rem 16px 3rem !important; max-width: 100% !important;
}}
[data-testid="stVerticalBlock"] {{ gap: 8px; }}
[data-testid="stHorizontalBlock"] {{ gap: 16px; }}

h1, h2, h3, h4, h5 {{
  font-family: var(--font-ui); font-weight: 600; letter-spacing: -0.01em;
  color: var(--text); margin: 0 0 0.15rem;
}}
h1 {{ font-size: 1.15rem; }}
h2 {{ font-size: 1.0rem; }}
h3 {{ font-size: 0.9rem; }}

/* --- Top bar ----------------------------------------------------------- */
/* Sticky so the ticker, refresh state and search survive any scroll. Sits under
   Streamlit's transparent 48px header. */
[data-testid="stHorizontalBlock"]:has(.topbar-anchor) {{
  position: sticky; top: 2.8rem; z-index: 120;
  background: var(--ground);
  border-bottom: 1px solid var(--rule-strong);
  padding: 4px 0 8px;
  align-items: center !important;
}}
.topbar-name {{ display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }}
.topbar-name .nm {{ font-size: 0.95rem; font-weight: 600; }}
.topbar-name .meta {{ font-size: 11px; color: var(--muted); }}
.topbar-run {{ font-family: var(--font-mono); font-size: 10.5px; color: var(--muted);
              text-align: right; line-height: 1.5; padding-top: 3px; }}
.topbar-run .ok {{ color: var(--up); }}
.topbar-run .bad {{ color: var(--down); }}

/* Inputs are square everywhere: radius 0 is the terminal's whole border language.
   Styled globally because a markdown-injected wrapper div is closed by the
   sanitiser before the widget mounts, so scoped wrappers never contain them. */
[data-baseweb="select"] > div {{
  border-radius: var(--radius) !important; border-color: var(--rule-strong);
  background: var(--panel);
  min-height: 30px; font-weight: 700; font-size: 13px;
  font-family: var(--font-mono);
}}
[data-baseweb="popover"] [data-baseweb="menu"] {{ border-radius: var(--radius); }}
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input {{
  border-radius: var(--radius) !important; border-color: var(--rule);
  background: var(--panel); color: var(--text);
  font-family: var(--font-mono); font-size: 12px; min-height: 30px;
}}
[data-testid="stTextInput"] > div, [data-testid="stDateInput"] > div {{
  border-radius: var(--radius) !important; background: var(--panel);
}}
[data-testid="stTextInput"] input:focus {{ border-color: var(--muted); }}

/* Section rule: a hairline and a caps label, never a card. */
.sec {{
  display: flex; align-items: baseline; justify-content: space-between;
  border-bottom: 1px solid var(--rule-strong);
  padding: 0 0 0.2rem; margin: 0;
}}
[data-testid="stElementContainer"]:has(.sec) {{ margin-top: 0.85rem; }}
[data-testid="stElementContainer"]:has(.sec) + [data-testid="stElementContainer"] {{
  margin-top: 1.4rem;
}}
.sec-label {{
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.09em;
  text-transform: uppercase; color: var(--text);
}}
.sec-count {{ font-size: 11px; color: var(--muted); font-family: var(--font-mono); }}

/* Identity strip (legacy, used by error paths before the top bar mounts). */
.ident {{ display: flex; align-items: baseline; gap: 0.55rem; flex-wrap: wrap; }}
.ident .tk {{ font-size: 1.25rem; font-weight: 700; letter-spacing: -0.02em; }}
.ident .nm {{ font-size: 0.95rem; }}
.ident .meta {{ font-size: 11px; color: var(--muted); }}

.rail {{ margin-top: 0.5rem; }}
/* The horizon SVG fills the rail column and scales to it, so it reads larger. */
.rail svg {{ width: 100%; height: auto; }}

/* Feed items: a typographic list, not a table. */
.feed {{ margin: 0.1rem 0 0.3rem; }}
.fitem {{
  display: grid; grid-template-columns: 84px 1fr auto auto; gap: 0.85rem;
  align-items: baseline; padding: 0.34rem 0;
  border-bottom: 1px solid var(--rule);
}}
.fitem:last-child {{ border-bottom: none; }}
.fitem .d {{ font-family: var(--font-mono); font-size: 11px; color: var(--muted); }}
.fitem .t {{ font-size: 12.5px; line-height: 1.35; }}
.fitem .s {{ font-size: 10px; letter-spacing: 0.07em; text-transform: uppercase;
            color: var(--muted); white-space: nowrap; }}
.fitem .s.high {{ color: var(--down); font-weight: 700; }}
.fitem .m {{ font-weight: 600; }}
.fitem .m.small {{ color: var(--orange-book); }}
.fitem .m.bio {{ color: var(--purple-book); }}
/* The materiality reason, when a feed line carries one. */
.fitem .why {{ font-size: 10px; color: var(--flag); letter-spacing: 0.04em;
              text-transform: uppercase; white-space: nowrap; }}

/* Deals: a type badge, a body of party, value and area, and the date. */
.deals {{ margin: 0.1rem 0 0.3rem; }}
.deal {{
  display: grid; grid-template-columns: 104px 1fr auto; gap: 0.8rem;
  align-items: baseline; padding: 0.4rem 0; border-bottom: 1px solid var(--rule);
}}
.deal:last-child {{ border-bottom: none; }}
.deal .db {{ font-size: 9.5px; letter-spacing: 0.06em; text-transform: uppercase;
            font-weight: 700; color: var(--muted); white-space: nowrap;
            align-self: center; }}
.deal.dt-acquisition .db {{ color: var(--down); }}
.deal.dt-licensing .db {{ color: var(--purple-book); }}
.deal.dt-collaboration .db {{ color: var(--up); }}
.deal.dt-divestiture .db {{ color: var(--orange-book); }}
.deal .dbody {{ font-size: 12.5px; line-height: 1.4; }}
.deal .dp {{ font-weight: 600; }}
.deal .dv {{ font-family: var(--font-mono); font-weight: 600; }}
.deal .da {{ color: var(--muted); }}
.deal .dd {{ font-family: var(--font-mono); font-size: 11px; color: var(--muted);
            white-space: nowrap; align-self: center; }}

/* Portfolio: one card per approved product, a modality stripe down the left, the
   figures in mono. A near-term loss of exclusivity reads in the down colour. */
.pf {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
      gap: 8px; margin: 0.4rem 0 0.3rem; }}
.pf-card {{ background: var(--panel); border: 1px solid var(--rule);
           border-left: 3px solid var(--rule-strong); padding: 0.5rem 0.65rem; }}
.pf-card.small {{ border-left-color: var(--orange-book); }}
.pf-card.bio {{ border-left-color: var(--purple-book); }}
.pf-head {{ display: flex; align-items: baseline; justify-content: space-between;
           gap: 0.5rem; }}
.pf-brand {{ font-size: 13px; font-weight: 600; letter-spacing: -0.01em; }}
.pf-mod {{ font-size: 8.5px; letter-spacing: 0.06em; text-transform: uppercase;
          color: var(--muted); white-space: nowrap; }}
.pf-generic {{ font-size: 10.5px; color: var(--muted); margin: 1px 0 5px;
              line-height: 1.25; }}
.pf-row {{ display: flex; justify-content: space-between; align-items: baseline;
          font-size: 11px; padding: 1px 0; }}
.pf-k {{ color: var(--muted); }}
.pf-v {{ font-family: var(--font-mono); }}
.pf-v.none {{ color: var(--muted); }}
.pf-v.near {{ color: var(--down); font-weight: 600; }}

/* Trial readouts: a mark and sign, the phase, the drug, and the quote. */
.readouts {{ margin: 0.1rem 0 0.3rem; }}
.readout {{
  display: grid; grid-template-columns: 16px 92px 1fr auto; gap: 0.6rem;
  align-items: baseline; padding: 0.42rem 0; border-bottom: 1px solid var(--rule);
}}
.readout:last-child {{ border-bottom: none; }}
.readout .rm {{ font-weight: 700; align-self: center; }}
.readout .rh {{ font-size: 10px; letter-spacing: 0.05em; text-transform: uppercase;
               font-weight: 700; white-space: nowrap; align-self: center; }}
.readout.rd-pos .rm, .readout.rd-pos .rh {{ color: var(--up); }}
.readout.rd-neg .rm, .readout.rd-neg .rh {{ color: var(--down); }}
.readout .rp {{ font-weight: 600; font-size: 12.5px; }}
.readout .rq {{ font-size: 11.5px; color: var(--muted); line-height: 1.35; }}
.readout .rd {{ font-family: var(--font-mono); font-size: 11px; color: var(--muted);
               white-space: nowrap; align-self: center; }}

/* Chart mounts: a chart is a fixed-width SVG. By default it centres in its column and an
   over-wide one shrinks to fit; the "stretch" variant fills the column edge to edge, used
   where a chart is meant to span its space. The horizon rail keeps its own class. */
.chart-mount {{ margin: 0.3rem 0 0.1rem; }}
.chart-mount svg {{ display: block; max-width: 100%; height: auto; margin: 0 auto; }}
.chart-mount.stretch svg {{ width: 100%; }}

/* Position strip. */
.pos {{ display: flex; gap: 2rem; flex-wrap: wrap; padding: 0.1rem 0 0.5rem; }}
.pos .k {{ font-size: 10px; letter-spacing: 0.07em; text-transform: uppercase;
          color: var(--muted); display: block; }}
.pos .v {{ font-size: 1.15rem; font-weight: 600; letter-spacing: -0.01em;
          font-family: var(--font-mono); }}
.pos .v.none {{ color: var(--muted); font-weight: 400; font-size: 1rem;
               font-family: var(--font-ui); }}
.pos .v.up {{ color: var(--up); }}
.pos .v.down {{ color: var(--down); }}
.pos .sub {{ font-size: 10.5px; color: var(--muted); display: block; margin-top: 1px; }}

/* Stat strip. */
.stats {{ display: flex; gap: 2.1rem; padding: 0.5rem 0 0.1rem; margin-bottom: 0.8rem;
         border-bottom: 1px solid var(--rule); flex-wrap: wrap; }}
.stat .k {{ font-size: 10.5px; letter-spacing: 0.07em; text-transform: uppercase;
           color: var(--muted); display: block; }}
.stat .v {{ font-size: 1.05rem; font-weight: 600; font-family: var(--font-mono); }}
.stat .v.none {{ color: var(--muted); font-weight: 400; }}
.stat .v.risk {{ color: var(--down); }}

/* The note is the one piece of prose, so it gets the reading face. */
.note {{ font-family: var(--font-prose); font-size: 15.5px; line-height: 1.55;
        max-width: none; margin: 0.35rem 0 0.2rem; }}
.note h4 {{ font-family: var(--font-ui); font-size: 10.5px; letter-spacing: 0.09em;
           text-transform: uppercase; color: var(--muted); margin: 0.7rem 0 0.1rem; }}
.note ul {{ margin: 0.1rem 0; padding-left: 1.1rem; }}
.note li {{ margin: 0.05rem 0; }}
.byline {{ font-size: 11px; color: var(--muted); margin-top: 0.35rem; }}
/* A passage added to a filing section, quoted full width for review. */
.rf-add {{ font-size: 12px; line-height: 1.42; border-left: 2px solid var(--flag);
          padding: 2px 0 2px 10px; margin: 5px 0; }}

/* The full trial description, shown when a pipeline row is clicked. */
.trial-detail {{ font-size: 13px; line-height: 1.45;
                 border-left: 2px solid var(--rule-strong);
                 padding: 0.35rem 0 0.35rem 0.7rem; margin-top: 0.5rem; }}
.trial-detail .nct {{ font-family: var(--font-mono); font-size: 11.5px;
                      color: var(--muted); margin-right: 0.5rem; }}

/* Identifiers are codes, so they take the mono face. */
.mono {{ font-family: var(--font-mono); font-size: 11.5px; letter-spacing: -0.01em; }}
.neg {{ color: var(--down); }}

/* Annotations: the analyst's own line, attached to the item it belongs to. */
.anno {{ border-left: 2px solid var(--flag); background: var(--panel);
        padding: 0.35rem 0.6rem; margin: 0.25rem 0; font-size: 12px;
        line-height: 1.4; max-width: 70ch; }}
.anno .who {{ font-family: var(--font-mono); font-size: 10px; color: var(--muted);
             display: block; margin-bottom: 1px; }}

/* Pinned spine selection: sits above the tabs, the cross-link from a spine click. */
.pinned {{ border-left: 3px solid var(--up); background: var(--panel);
          padding: 6px 12px; margin: 4px 0 8px; }}
.pin-head {{ display: flex; justify-content: space-between; align-items: baseline; }}
.pin-tag {{ font-size: 9px; letter-spacing: 0.09em; text-transform: uppercase;
           color: var(--muted); }}
.pin-clear {{ font-size: 10px; color: var(--muted); text-decoration: none;
             border-bottom: 1px solid var(--rule-strong); }}
.pin-clear:hover {{ color: var(--text); }}
.pin-body {{ font-size: 13px; margin-top: 2px; }}
.pin-body .d {{ font-family: var(--font-mono); color: var(--muted);
               margin-right: 6px; }}
.pin-body .why {{ font-size: 10px; color: var(--flag); text-transform: uppercase;
                 letter-spacing: 0.04em; margin-left: 6px; }}
.pin-detail {{ font-size: 11.5px; color: var(--muted); margin-top: 3px;
              line-height: 1.4; }}
/* A spine anchor is a link but must not look like body text underlined. */
.rail a {{ text-decoration: none; cursor: pointer; }}
.rail a:hover line {{ stroke-width: 2.4; }}
/* Coverage small-multiple panels are links to the clicked company; outline on hover. */
.chart-mount a {{ cursor: pointer; }}
.chart-mount a:hover rect {{ stroke: var(--muted); stroke-width: 1; }}

/* Time machine banner: unmissable, the whole terminal is historical while it shows. */
.asof-banner {{
  background: var(--flag); color: var(--ground);
  font-weight: 700; font-size: 12.5px; letter-spacing: 0.04em;
  padding: 6px 12px; margin: 4px 0 8px;
}}

/* Designed empty and error states. */
.state {{ border-left: 2px solid var(--rule-strong); padding: 0.4rem 0 0.4rem 0.7rem;
         margin: 0.3rem 0; max-width: 68ch; }}
.state.err {{ border-left-color: var(--down); }}
.state .t {{ font-weight: 600; font-size: 12.5px; }}
.state .d {{ font-size: 12px; color: var(--muted); margin-top: 0.1rem; }}
.state.err .t {{ color: var(--down); }}

/* Tables: hairlines, no card, no radius. Tabular data takes the mono face and
   right alignment; headers take the narrow face. */
[data-testid="stDataFrame"] {{ border: 1px solid var(--rule); border-radius: var(--radius); }}
[data-testid="stDataFrame"] * {{ font-family: var(--font-mono) !important; font-size: 11.5px; }}

/* Statement grid. */
.fin-wrap {{ overflow-x: auto; margin: 0.2rem 0 0.1rem; }}
.fin {{
  width: 100% !important; table-layout: fixed; min-width: 30rem; max-width: none;
  border-collapse: collapse; font-variant-numeric: tabular-nums;
}}
.fin th.l, .fin td.l {{ width: 27%; text-align: left; padding-left: 0; }}
.fin th, .fin td {{ border-left: 0; border-right: 0; border-top: 0; }}
.fin th {{
  font-family: var(--font-ui-narrow);
  font-size: 10.5px; letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--muted); font-weight: 600; text-align: right; white-space: nowrap;
  padding: 0 0 0.3rem 1.1rem; border-bottom: 1px solid var(--rule-strong);
}}
.fin td {{
  font-family: var(--font-mono);
  font-size: 12px; text-align: right; white-space: nowrap;
  padding: 0.26rem 0 0.26rem 1.1rem; border-bottom: 1px solid var(--rule);
}}
.fin td.l {{ font-family: var(--font-ui); font-size: 12.5px; }}
.fin td.now, .fin th.now {{ color: var(--text); font-weight: 600; }}
.fin tr:last-child td {{ border-bottom: none; }}
.fin tr.subtotal td, .fin tr.total td {{ font-weight: 600; }}
.fin tr.total td {{ border-top: 1px solid var(--rule-strong); }}
.fin tr.memo td.l {{ color: var(--muted); }}
.fin td.neg {{ color: var(--down); }}
.fin td.gap {{ color: var(--muted); }}
.fin .der {{
  text-decoration: underline dotted; text-decoration-color: var(--muted);
  text-underline-offset: 3px;
}}
.fin .lu {{ color: var(--muted); font-size: 11px; }}
.fin-note {{ font-size: 11px; color: var(--muted); margin: 0.45rem 0 0; max-width: 70ch; }}

/* Chart mount: the SVG always draws at its own declared size. */
.trend {{ margin: 0.35rem 0 0.1rem; }}
.trend svg {{ display: block; }}
/* Pure-CSS hover on SVG charts: a transparent band per x slot reveals its readout. */
.hoverband .tip {{ display: none; }}
.hoverband:hover .tip {{ display: block; }}

/* Catalyst calendar. */
.cal {{
  display: grid; grid-template-columns: repeat(auto-fill, minmax(224px, 1fr));
  grid-auto-rows: 1fr;
  gap: 1px; background: var(--rule); border: 1px solid var(--rule);
  margin: 0.3rem 0 0.2rem;
}}
.cal-month {{
  background: var(--ground); padding: 0.45rem 0.6rem 0.55rem; min-height: 96px;
  position: relative;
}}
.cal-month.empty {{ background: var(--panel); }}
.cal-month.now {{ box-shadow: inset 2px 0 0 var(--up); }}
.cal-head {{
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 10px; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase;
  color: var(--muted); padding-bottom: 0.3rem;
}}
.cal-month.now .cal-head {{ color: var(--up); }}
.cal-n {{ font-weight: 600; letter-spacing: 0; }}
.cal-item {{
  display: grid; grid-template-columns: 20px 1fr; gap: 0.4rem;
  align-items: baseline; padding: 0.22rem 0; border-top: 1px solid var(--rule);
  position: relative; cursor: default;
}}
.cal-item:hover {{ background: var(--panel); }}
.cal-item.uncurated .cal-day {{ color: var(--flag); }}
.cal-pop {{
  display: none; position: absolute; left: 0; top: calc(100% + 4px); z-index: 40;
  width: max(100%, 280px); padding: 0.5rem 0.6rem;
  background: var(--panel); border: 1px solid var(--rule-strong);
  font-size: 11.5px; line-height: 1.4; color: var(--text);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
}}
.cal-item:hover .cal-pop {{ display: block; }}
.cal-pop b {{ font-family: var(--font-mono); font-size: 11px; font-weight: 600; }}
.cal-pop-k {{
  display: block; font-size: 9.5px; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--muted); margin: 0.1rem 0 0.3rem;
}}
.cal-item:nth-last-child(1) .cal-pop {{ top: auto; bottom: calc(100% + 4px); }}
.cal-day {{
  font-family: var(--font-mono); font-size: 11px; font-weight: 600; text-align: right;
  color: var(--text);
}}
.cal-day.none {{ color: var(--muted); font-weight: 400; }}
.cal-title {{ font-size: 11.5px; line-height: 1.3; color: var(--text); }}
.cal-kind {{
  grid-column: 2; font-size: 9.5px; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--muted);
}}

/* Tabs as a plain text strip. */
.stTabs [data-baseweb="tab-list"] {{ gap: 1.1rem; border-bottom: 1px solid var(--rule-strong); }}
.stTabs [data-baseweb="tab"] {{
  height: auto; padding: 0.3rem 0; background: transparent;
  font-size: 12px; font-weight: 500; letter-spacing: 0.01em; color: var(--muted);
}}
.stTabs [aria-selected="true"] {{ color: var(--text); font-weight: 700; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: var(--up); height: 2px; }}

/* Controls: square, quiet, legible; hover, focus and disabled states. */
.stButton button {{
  border-radius: var(--radius); border: 1px solid var(--rule-strong);
  background: var(--panel);
  color: var(--text); font-size: 12px; font-weight: 600; padding: 0.2rem 0.7rem;
}}
.stButton button:hover {{ background: var(--rule); border-color: var(--muted); }}
.stButton button:disabled {{ color: var(--muted); border-color: var(--rule); }}
/* The two note actions sit beside the position strip as secondary controls, so they
   are smaller and quieter than a primary button. */
.st-key-gen_note button, .st-key-gen_sheet button {{
  min-height: 22px; padding: 0.02rem 0.4rem; font-size: 10.5px; line-height: 1.2;
}}
.st-key-gen_note {{ margin-bottom: 3px; }}
section[data-testid="stSidebar"] {{ background: var(--panel);
  border-right: 1px solid var(--rule-strong); }}
section[data-testid="stSidebar"] .block-container {{ padding-top: 1.2rem; }}

/* Radios and pills follow the same quiet square language. */
.stRadio [role="radiogroup"] label, .stPills [data-baseweb] {{ border-radius: var(--radius); }}

/* Quality floor: focus must be visible, and motion is opt-out. */
*:focus-visible {{ outline: 2px solid var(--text); outline-offset: 1px; }}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation-duration: 0.001ms !important; animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important; scroll-behavior: auto !important;
  }}
}}
@media (max-width: 1400px) {{
  .stats {{ gap: 1.4rem; }}
  .block-container {{ padding-left: 8px; padding-right: 8px; }}
}}
</style>
"""


# --- Ordinal ramps -------------------------------------------------------
# Steps are spaced in Oklab rather than in sRGB, because even sRGB steps are not even
# to the eye: the dark end of a ramp bunches up and the light end spreads out.
def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c):
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def _to_rgb(value: str):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _oklab(value: str):
    r, g, b = (_srgb_to_linear(c) for c in _to_rgb(value))
    long = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    med = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    short = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * long + 0.7936177850 * med - 0.0040720468 * short,
            1.9779984951 * long - 2.4285922050 * med + 0.4505937099 * short,
            0.0259040371 * long + 0.7827717662 * med - 0.8086757660 * short)


def _from_oklab(lightness, green_red, blue_yellow):
    long = (lightness + 0.3963377774 * green_red + 0.2158037573 * blue_yellow) ** 3
    med = (lightness - 0.1055613458 * green_red - 0.0638541728 * blue_yellow) ** 3
    short = (lightness - 0.0894841775 * green_red - 1.2914855480 * blue_yellow) ** 3
    channels = (4.0767416621 * long - 3.3077115913 * med + 0.2309699292 * short,
                -1.2684380046 * long + 2.6097574011 * med - 0.3413193965 * short,
                -0.0041960863 * long - 0.7034186147 * med + 1.7076147010 * short)
    return "#" + "".join(f"{round(_linear_to_srgb(c) * 255):02X}" for c in channels)


def _mix(start: str, end: str, position: float) -> str:
    first, second = _oklab(start), _oklab(end)
    return _from_oklab(*(first[i] + (second[i] - first[i]) * position
                         for i in range(3)))


def _relative_luminance(value: str) -> float:
    r, g, b = (_srgb_to_linear(c) for c in _to_rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio between two colours."""
    high, low = sorted((_relative_luminance(first), _relative_luminance(second)),
                       reverse=True)
    return (high + 0.05) / (low + 0.05)


# WCAG 1.4.11 asks 3:1 of any graphical object carrying meaning.
GRAPHIC_CONTRAST = 3.0


def _oklch(value: str):
    lightness, green_red, blue_yellow = _oklab(value)
    return (lightness, math.hypot(green_red, blue_yellow),
            math.atan2(blue_yellow, green_red))


def _from_oklch(lightness: float, chroma: float, hue: float) -> str:
    """Back to sRGB, giving up chroma rather than accuracy when out of gamut."""
    for attempt in range(24):
        candidate = chroma * (1 - attempt / 24)
        hexv = _from_oklab(lightness, candidate * math.cos(hue),
                           candidate * math.sin(hue))
        if all(0.0005 < channel < 0.9995 for channel in _to_rgb(hexv)) or attempt == 23:
            return hexv
    return _from_oklab(lightness, 0, 0)


def ordinal_ramp(steps: int, palette: "Palette" = None) -> list:
    """``steps`` evenly spaced tints, every one visible against the ground.

    Lightness varies; chroma and hue are held at the data colour's. The floor is
    placed by contrast: WCAG 1.4.11 asks 3:1 of a graphical object carrying meaning.
    """
    palette = palette or P
    if steps < 2:
        return [palette.data]
    top, chroma, hue = _oklch(palette.data)
    ground = _oklch(palette.ground)[0]

    low, high = 0.0, 1.0
    for _ in range(32):
        middle = (low + high) / 2
        lightness = ground + (top - ground) * middle
        if contrast(_from_oklch(lightness, chroma, hue), palette.ground) \
                < GRAPHIC_CONTRAST:
            low = middle
        else:
            high = middle
    floor = ground + (top - ground) * high

    return [_from_oklch(floor + (top - floor) * index / (steps - 1), chroma, hue)
            for index in range(steps)]


MINUS = "−"  # true minus, digit-width under tabular figures


def _missing(value) -> bool:
    """True for None and for pandas NaN, which is what an absent figure becomes."""
    return value is None or value != value


def num(value, decimals: int = 1, dash: str = "—") -> str:
    """A figure at fixed precision. Missing renders as a dash, never as zero."""
    if _missing(value):
        return dash
    text = f"{abs(value):,.{decimals}f}"
    return f"{MINUS}{text}" if value < 0 else text


def pct(value, decimals: int = 1, dash: str = "—") -> str:
    if _missing(value):
        return dash
    return f"{num(value, decimals)}%"
