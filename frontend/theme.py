"""Design system: palette, type, chart theme, and number formatting.

One rule governs the palette in both modes. Ground and ink build every piece of chrome;
hue is spent only on encoded meaning: modality, direction, severity, staleness, and the
data itself. The data hue is not an exception to that rule. It means "this is a measured
series", which is why every line, bar, point, and heatmap step carries it and no piece of
chrome ever does. Without it the dark theme was cream on olive throughout and read flat.

The two book colours are inherited from the source datasets rather than invented. FDA
exclusivity data ships as the Orange Book (small molecules) and the Purple Book
(biologics), so modality reads in the colours the agency already uses. Dark mode lifts
both to hold their chroma against a deep ground; it does not reassign them.

Light stays the reasoned default: this tool sits beside Excel and 10-K PDFs all day, and
a dark island forces pupil re-adaptation on every glance. Dark is offered because the
book colours carry much harder against ink, not because dark is better here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import altair as alt


@dataclass(frozen=True)
class Palette:
    """One set of colour roles. Both modes fill the same roles, never new ones."""

    name: str
    ground: str          # the absence of signal
    ink: str             # text, rules, axes, all non-negative figures
    data: str            # a plotted series: lines, bars, points, the phase ramp
    orange_book: str     # small-molecule modality
    purple_book: str     # biologic modality
    oxblood: str         # negative direction and high severity, single pole
    stale: str           # a value past its source TTL
    rule: str            # hairline, derived from ink, never a new hue
    rule_strong: str
    raised: str          # sidebar and hover, one step off the ground
    # Phase is ordinal, so it takes a single-hue ramp rather than separate hues. The
    # ramp climbs to the data colour, which keeps a heatmap the same material as a line
    # chart. Modality stays the only categorical use of hue.
    phase_tints: tuple

    @property
    def modality(self) -> dict:
        return {"small molecule": self.orange_book, "biologic": self.purple_book}

    @property
    def severity(self) -> dict:
        # No severity glyph. The colour of the word is the encoding; a dot beside it
        # would say the same thing twice, in a glyph belonging to no part of this palette.
        return {"high": self.oxblood, "medium": self.ink, "low": self.stale}

    @property
    def muted(self) -> str:
        """Body text one step down from ink. Captions and secondary labels."""
        return self.stale if self.name == "dark" else "#5A564E"


# stale and the modality colours carry real caption and table text, so both palettes are
# tuned to clear 4.5:1 against their ground. The earlier values sat at 2.57:1 in light
# and 4.10:1 in dark, which is recessive to the point of being unreadable.
LIGHT = Palette(
    name="light", ground="#F2EFE9", ink="#1C1B19", data="#116765",
    orange_book="#B04E0C", purple_book="#5B4B8A", oxblood="#8C2F39", stale="#6E6A61",
    rule="#DCD7CC", rule_strong="#B9B3A6", raised="#EDE9E1",
    phase_tints=("#DCE8E7", "#A9CFCD", "#6FAFAC", "#37827F", "#116765"),
)

DARK = Palette(
    name="dark", ground="#0E1116", ink="#E6E9EF", data="#4CC2C4",
    orange_book="#F08A3C", purple_book="#A78BFA", oxblood="#F2545B", stale="#78838F",
    rule="#1E242C", rule_strong="#333C48", raised="#141A21",
    # Ordinal ramp from just off the ground up to the data colour, so a heatmap reads
    # as the same material as a line chart rather than as grey chrome.
    phase_tints=("#16202A", "#1D3A44", "#256069", "#34909A", "#4CC2C4"),
)

# Mode is read once at import. Streamlit's own chrome, and in particular the canvas
# dataframe, takes its colours from .streamlit/config.toml rather than from injected
# CSS, so the two have to agree and the switch is a restart rather than a toggle.
MODE = os.getenv("ER_THEME", "dark").strip().lower()
P = DARK if MODE == "dark" else LIGHT

# --- Type ---------------------------------------------------------------
# Display is scoped to the note prose, the one part of the app that is writing.
# Body is Public Sans, the face of US federal digital services, and this app runs
# almost entirely on US federal data. Mono is scoped to identifiers, not to numbers:
# quantities align better in proportional tabular figures than in any monospace.
DISPLAY = "'Newsreader', 'Iowan Old Style', Georgia, serif"
BODY = "'Public Sans', -apple-system, 'Segoe UI', system-ui, sans-serif"
MONO = "'Spline Sans Mono', ui-monospace, 'SF Mono', Menlo, monospace"

_FONT_URL = ("https://fonts.googleapis.com/css2"
             "?family=Newsreader:opsz,wght@6..72,400;6..72,500"
             "&family=Public+Sans:wght@400;500;600;700"
             "&family=Spline+Sans+Mono:wght@400;500"
             "&display=swap")


def css() -> str:
    """Scoped stylesheet. Density, rules, focus, and motion all live here."""
    return f"""
<style>
@import url('{_FONT_URL}');

:root {{
  --ground: {P.ground}; --ink: {P.ink}; --rule: {P.rule}; --rule-strong: {P.rule_strong};
  --stale: {P.stale}; --oxblood: {P.oxblood};
  --orange-book: {P.orange_book}; --purple-book: {P.purple_book}; --data: {P.data};
}}

html, body, [class*="css"], .stApp {{
  background: var(--ground);
  color: var(--ink);
  font-family: {BODY};
  font-size: 13px;
  -webkit-font-smoothing: antialiased;
}}

/* Every figure in the app holds its column when values change on refresh. */
.stApp, table, td, th, .stMetric, [data-testid="stMetricValue"], .num, .mono {{
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1, "lnum" 1;
}}

/* Streamlit's header is 48px at z-index 999990 and paints an opaque band. It cannot
   be collapsed reliably, and it carries the sidebar toggle, so it stays. Making it
   transparent and starting content below it is what keeps the identity strip visible. */
header[data-testid="stHeader"] {{ background: transparent !important; }}
[data-testid="stToolbar"] {{ right: 0.6rem; }}

/* Density. The template answer is generous padding; this is an analyst tool.
   Streamlit's generated class wins the cascade on padding, so this one is forced. */
[data-testid="stMainBlockContainer"], .block-container {{
  padding: 3.1rem 1.4rem 3rem !important; max-width: 100% !important;
}}

/* The company picker sits in the identity strip, not behind a collapsed sidebar. */
.pick [data-baseweb="select"] > div {{
  border-radius: 0; border-color: {P.rule_strong}; background: {P.ground};
  min-height: 30px; font-weight: 700; font-size: 13px;
}}
.pick [data-testid="stSelectbox"] {{ margin-top: -2px; }}
[data-testid="stVerticalBlock"] {{ gap: 0.45rem; }}
[data-testid="stHorizontalBlock"] {{ gap: 0.9rem; }}
h1, h2, h3, h4, h5 {{
  font-family: {BODY}; font-weight: 600; letter-spacing: -0.01em;
  color: var(--ink); margin: 0 0 0.15rem;
}}
h1 {{ font-size: 1.15rem; }}
h2 {{ font-size: 1.0rem; }}
h3 {{ font-size: 0.9rem; }}

/* Section rule: a hairline and a caps label, never a card.
   The box stays tight and the rhythm lives on Streamlit's element wrapper. Streamlit
   sizes that wrapper itself, so padding on .sec made it overflow its own container and
   the space below the rule collapsed: the Refresh button sat 1px under it. Keeping
   .sec the same height as its wrapper puts the margins back in the layout flow. */
.sec {{
  display: flex; align-items: baseline; justify-content: space-between;
  border-bottom: 1px solid var(--rule-strong);
  padding: 0 0 0.2rem; margin: 0;
}}
/* Streamlit collapses the rule's own container to 8px while .sec draws 21px, so
   neither padding on .sec nor margin on that container reaches the layout. The
   element after the rule is a normal item in the flex flow, so the gap goes there. */
[data-testid="stElementContainer"]:has(.sec) {{ margin-top: 0.85rem; }}
/* The collapsed container swallows roughly 8px of this, so the visible gap is about
   half what is set here. One systematic correction, not a per-element nudge. */
[data-testid="stElementContainer"]:has(.sec) + [data-testid="stElementContainer"] {{
  margin-top: 1.4rem;
}}
.sec-label {{
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.09em;
  text-transform: uppercase; color: var(--ink);
}}
.sec-count {{ font-size: 11px; color: var(--stale); }}

/* Identity strip */
.ident {{ display: flex; align-items: baseline; gap: 0.55rem; flex-wrap: wrap; }}
.ident .tk {{ font-size: 1.25rem; font-weight: 700; letter-spacing: -0.02em; }}
.ident .nm {{ font-size: 0.95rem; }}
.ident .meta {{ font-size: 11px; color: var(--stale); }}

/* The horizon rail clears the section rule above it. Its first segment label sits at
   the very top of the SVG, so without this it touches the HORIZON hairline. */
.rail {{ margin-top: 0.5rem; }}

/* Feed items are a typographic list, not a table. Two or three rows in a grid widget
   is all chrome and no content: headers, borders, and a canvas to render one fact. */
.feed {{ margin: 0.1rem 0 0.3rem; }}
.fitem {{
  display: grid; grid-template-columns: 84px 1fr auto; gap: 0.85rem;
  align-items: baseline; padding: 0.34rem 0;
  border-bottom: 1px solid var(--rule);
}}
.fitem:last-child {{ border-bottom: none; }}
.fitem .d {{ font-family: {MONO}; font-size: 11px; color: var(--stale);
            font-variant-numeric: tabular-nums; }}
.fitem .t {{ font-size: 12.5px; line-height: 1.35; }}
.fitem .s {{ font-size: 10px; letter-spacing: 0.07em; text-transform: uppercase;
            color: var(--stale); white-space: nowrap; }}
.fitem .s.high {{ color: var(--oxblood); font-weight: 700; }}
.fitem .m {{ font-weight: 600; }}
.fitem .m.small {{ color: var(--orange-book); }}
.fitem .m.bio {{ color: var(--purple-book); }}

/* Position strip: what is true about this company right now, before any diff. */
.pos {{ display: flex; gap: 2rem; flex-wrap: wrap; padding: 0.1rem 0 0.5rem; }}
.pos .k {{ font-size: 10px; letter-spacing: 0.07em; text-transform: uppercase;
          color: var(--stale); display: block; }}
.pos .v {{ font-size: 1.15rem; font-weight: 600; font-variant-numeric: tabular-nums;
          letter-spacing: -0.01em; }}
.pos .v.none {{ color: var(--stale); font-weight: 400; font-size: 1rem; }}
.pos .v.up {{ color: var(--data); }}
.pos .v.down {{ color: var(--oxblood); }}
.pos .sub {{ font-size: 10.5px; color: var(--stale); display: block; margin-top: 1px; }}

/* Stat strip: one dense line, not four cards. The bottom margin is structural, not a
   nudge: a chart directly below draws its topmost axis label at its own top edge, and
   with the strip flush against it the label lands on the figures. */
.stats {{ display: flex; gap: 2.1rem; padding: 0.5rem 0 0.1rem; margin-bottom: 0.8rem;
         border-bottom: 1px solid var(--rule); flex-wrap: wrap; }}
.stat .k {{ font-size: 10.5px; letter-spacing: 0.07em; text-transform: uppercase;
           color: var(--stale); display: block; }}
.stat .v {{ font-size: 1.05rem; font-weight: 600; font-variant-numeric: tabular-nums; }}
.stat .v.none {{ color: var(--stale); font-weight: 400; }}
.stat .v.risk {{ color: var(--oxblood); }}

/* The note is the one piece of prose, so it gets the reading face. */
.note {{ font-family: {DISPLAY}; font-size: 15px; line-height: 1.5;
        max-width: 62ch; margin: 0.35rem 0 0.2rem; }}
.note h4 {{ font-family: {BODY}; font-size: 10.5px; letter-spacing: 0.09em;
           text-transform: uppercase; color: var(--stale); margin: 0.7rem 0 0.1rem; }}
.note ul {{ margin: 0.1rem 0; padding-left: 1.1rem; }}
.note li {{ margin: 0.05rem 0; }}
.byline {{ font-size: 11px; color: var(--stale); margin-top: 0.35rem; }}

/* Identifiers are codes, so they take the mono face. Quantities do not. */
.mono {{ font-family: {MONO}; font-size: 11.5px; letter-spacing: -0.01em; }}
.neg {{ color: var(--oxblood); }}

/* Designed empty and error states. An empty state says what to do next. */
.state {{ border-left: 2px solid var(--rule-strong); padding: 0.4rem 0 0.4rem 0.7rem;
         margin: 0.3rem 0; max-width: 68ch; }}
.state.err {{ border-left-color: var(--oxblood); }}
.state .t {{ font-weight: 600; font-size: 12.5px; }}
.state .d {{ font-size: 12px; color: {P.muted}; margin-top: 0.1rem; }}
.state.err .t {{ color: var(--oxblood); }}

/* Tables: hairlines, no card, no radius, numerics right-aligned. */
[data-testid="stDataFrame"] {{ border: 1px solid var(--rule); border-radius: 0; }}
[data-testid="stDataFrame"] * {{ font-family: {BODY} !important; }}

/* Statement grid. Built as a real table rather than a dataframe widget: the canvas
   dataframe cannot hold a dotted rule under one cell, weight a subtotal row, or keep
   the label column from being scrolled away from its figures. */
.fin-wrap {{ overflow-x: auto; margin: 0.2rem 0 0.1rem; }}
/* Streamlit's markdown stylesheet sizes tables to their content, which leaves a
   statement huddled in the left third of the column. Fixed layout also keeps every
   period column the same width, so figures line up down the grid and across it. */
.fin {{
  width: 100% !important; table-layout: fixed; min-width: 30rem;
  /* Wide enough for six periods, capped so the columns do not sprawl across a large
     monitor. A statement is read by scanning across a row; spread too far, the eye
     loses the line it is on. */
  max-width: 52rem;
  border-collapse: collapse; font-variant-numeric: tabular-nums;
}}
.fin th.l, .fin td.l {{ width: 27%; text-align: left; padding-left: 0; }}
/* Streamlit's markdown stylesheet puts a box border on every cell, which draws a grid
   this table does not want. Only the horizontal hairlines are ours. */
.fin th, .fin td {{ border-left: 0; border-right: 0; border-top: 0; }}
.fin th {{
  font-size: 10.5px; letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--stale); font-weight: 600; text-align: right; white-space: nowrap;
  padding: 0 0 0.3rem 1.1rem; border-bottom: 1px solid var(--rule-strong);
}}
.fin td {{
  font-size: 12.5px; text-align: right; white-space: nowrap;
  padding: 0.26rem 0 0.26rem 1.1rem; border-bottom: 1px solid var(--rule);
}}
/* The most recent period is the one being read; the rest are context for it. */
.fin td.now, .fin th.now {{ color: var(--ink); font-weight: 600; }}
.fin tr:last-child td {{ border-bottom: none; }}
.fin tr.subtotal td, .fin tr.total td {{ font-weight: 600; }}
.fin tr.total td {{ border-top: 1px solid var(--rule-strong); }}
.fin tr.memo td.l {{ color: {P.muted}; }}
.fin td.neg {{ color: var(--oxblood); }}
.fin td.gap {{ color: var(--stale); }}
/* Computed from two reported lines rather than tagged by the filer. Marked on the
   figure itself, so it travels with the number instead of needing a legend column. */
.fin .der {{
  text-decoration: underline dotted; text-decoration-color: var(--stale);
  text-underline-offset: 3px;
}}
.fin .lu {{ color: var(--stale); font-size: 11px; }}
.fin-note {{ font-size: 11px; color: var(--stale); margin: 0.45rem 0 0; max-width: 70ch; }}

/* Tabs as a plain text strip. */
.stTabs [data-baseweb="tab-list"] {{ gap: 1.1rem; border-bottom: 1px solid var(--rule-strong); }}
.stTabs [data-baseweb="tab"] {{
  height: auto; padding: 0.3rem 0; background: transparent;
  font-size: 12px; font-weight: 500; letter-spacing: 0.01em; color: {P.muted};
}}
.stTabs [aria-selected="true"] {{ color: var(--ink); font-weight: 700; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: var(--ink); height: 2px; }}

/* Controls: square, quiet, and legible. */
.stButton button {{
  border-radius: 0; border: 1px solid var(--rule-strong); background: var(--ground);
  color: var(--ink); font-size: 12px; font-weight: 600; padding: 0.2rem 0.7rem;
}}
.stButton button:hover {{ background: {P.raised}; border-color: var(--ink); }}
section[data-testid="stSidebar"] {{ background: {P.raised}; border-right: 1px solid var(--rule-strong); }}
section[data-testid="stSidebar"] .block-container {{ padding-top: 1.2rem; }}

/* Quality floor: focus must be visible, and motion is opt-out. */
*:focus-visible {{ outline: 2px solid var(--ink); outline-offset: 1px; }}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation-duration: 0.001ms !important; animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important; scroll-behavior: auto !important;
  }}
}}
/* Holds down to a laptop screen. */
@media (max-width: 1400px) {{
  .stats {{ gap: 1.4rem; }}
  .block-container {{ padding-left: 1rem; padding-right: 1rem; }}
}}
</style>
"""


# --- Charts -------------------------------------------------------------
# One theme, registered once, applied to every chart in the app. The five views
# should read as siblings rather than as five library demos.
@alt.theme.register("er_terminal", enable=True)
def _chart_theme() -> alt.theme.ThemeConfig:
    axis = {
        "labelFont": "Public Sans", "labelFontSize": 10, "labelColor": P.muted,
        "titleFont": "Public Sans", "titleFontSize": 10, "titleColor": P.stale,
        "titleFontWeight": 600, "titlePadding": 8,
        "domainColor": P.rule_strong, "domainWidth": 1,
        "tickColor": P.rule_strong, "tickSize": 3,
        "gridColor": P.rule, "gridWidth": 1, "gridDash": [],
        "labelPadding": 4,
    }
    return alt.theme.ThemeConfig({
        "config": {
            "background": P.ground,
            "font": "Public Sans",
            # No continuousWidth: charts size to their container instead.
            "view": {"stroke": None, "continuousHeight": 260},
            # One axis treatment for every chart. Labels stay horizontal and Vega drops
            # whichever would collide rather than rotating or overprinting them.
            "axisX": {**axis, "grid": False, "labelAngle": 0, "labelOverlap": "greedy",
                      "labelSeparation": 6, "labelLimit": 96},
            "axisY": {**axis, "grid": True, "ticks": False, "domain": False,
                      "labelOverlap": "greedy", "labelSeparation": 4, "labelLimit": 96},
            "line": {"color": P.data, "strokeWidth": 1.6},
            "bar": {"color": P.data},
            "point": {"color": P.data, "size": 14},
            "rule": {"color": P.rule_strong},
            "legend": {
                "labelFont": "Public Sans", "labelFontSize": 10, "labelColor": P.ink,
                "titleFont": "Public Sans", "titleFontSize": 10, "titleColor": P.stale,
                "titleFontWeight": 600, "symbolType": "square", "symbolSize": 70,
                "orient": "top", "direction": "horizontal", "offset": 6,
                "padding": 0, "titlePadding": 6,
            },
            "title": {
                "font": "Public Sans", "fontSize": 11, "fontWeight": 700,
                "color": P.ink, "anchor": "start", "offset": 8,
                "subtitleFont": "Public Sans", "subtitleColor": P.stale, "subtitleFontSize": 10,
            },
            "range": {"category": [P.data, P.orange_book, P.purple_book, P.oxblood, P.ink]},
        }
    })


# --- Numbers ------------------------------------------------------------
# Consistent precision per column, units in the header, one negative treatment.
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
