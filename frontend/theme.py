"""Design system: palette, type, chart theme, and number formatting.

One rule governs the palette. Paper and ink build every piece of chrome; hue is spent
only on encoded meaning. If something carries colour it is because the colour is data:
modality, direction, severity, or staleness.

The two book colours are inherited from the source datasets rather than invented. FDA
exclusivity data ships as the Orange Book (small molecules) and the Purple Book
(biologics), so modality reads in the colours the agency already uses.
"""

from __future__ import annotations

import altair as alt

# --- Palette ------------------------------------------------------------
PAPER = "#F2EFE9"        # ground, and the absence of signal
INK = "#1C1B19"          # text, rules, axes, all non-negative figures
ORANGE_BOOK = "#C2570F"  # small-molecule modality
PURPLE_BOOK = "#5B4B8A"  # biologic modality
OXBLOOD = "#8C2F39"      # negative direction and high severity, single pole
STALE = "#9A968C"        # a value past its source TTL

# Chrome derived from ink, never a new hue.
RULE = "#DCD7CC"
RULE_STRONG = "#B9B3A6"
PAPER_RAISED = "#EDE9E1"

# Phase is ordinal, so it takes an ink tint ramp rather than a hue ramp. Hue stays
# reserved for modality, which is the categorical distinction that carries meaning.
PHASE_TINTS = ["#DCD7CC", "#BAB3A6", "#8A8378", "#4A463F", "#1C1B19"]

MODALITY_COLOUR = {"small molecule": ORANGE_BOOK, "biologic": PURPLE_BOOK}
SEVERITY_COLOUR = {"high": OXBLOOD, "medium": INK, "low": STALE}
# No severity glyph. The colour of the word is the encoding; a dot beside it would say
# the same thing twice and in a glyph that belongs to no part of this palette.

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
  --paper: {PAPER}; --ink: {INK}; --rule: {RULE}; --rule-strong: {RULE_STRONG};
  --stale: {STALE}; --oxblood: {OXBLOOD};
  --orange-book: {ORANGE_BOOK}; --purple-book: {PURPLE_BOOK};
}}

html, body, [class*="css"], .stApp {{
  background: var(--paper);
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
  border-radius: 0; border-color: {RULE_STRONG}; background: {PAPER};
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

/* Section rule: a hairline and a caps label, never a card. */
.sec {{
  display: flex; align-items: baseline; justify-content: space-between;
  border-bottom: 1px solid var(--rule-strong);
  padding: 0.75rem 0 0.2rem; margin: 0.5rem 0 0.35rem;
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

/* Freshness strip. Staleness is structural, not a footnote. */
.fresh {{ display: flex; gap: 1.1rem; flex-wrap: wrap; padding: 0.3rem 0 0; }}
.fresh i {{ font-style: normal; font-size: 11px; color: var(--stale); }}
.fresh b {{ font-weight: 600; font-size: 11px; color: var(--ink); }}
.fresh .warn b {{ color: var(--oxblood); }}
.fresh .unk b {{ color: var(--stale); font-weight: 400; }}

/* Stat strip: one dense line, not four cards. */
.stats {{ display: flex; gap: 2.1rem; padding: 0.5rem 0 0.1rem;
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
.state .d {{ font-size: 12px; color: #5A564E; margin-top: 0.1rem; }}
.state.err .t {{ color: var(--oxblood); }}

/* Tables: hairlines, no card, no radius, numerics right-aligned. */
[data-testid="stDataFrame"] {{ border: 1px solid var(--rule); border-radius: 0; }}
[data-testid="stDataFrame"] * {{ font-family: {BODY} !important; }}

/* Tabs as a plain text strip. */
.stTabs [data-baseweb="tab-list"] {{ gap: 1.1rem; border-bottom: 1px solid var(--rule-strong); }}
.stTabs [data-baseweb="tab"] {{
  height: auto; padding: 0.3rem 0; background: transparent;
  font-size: 12px; font-weight: 500; letter-spacing: 0.01em; color: #6B675F;
}}
.stTabs [aria-selected="true"] {{ color: var(--ink); font-weight: 700; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: var(--ink); height: 2px; }}

/* Controls: square, quiet, and legible. */
.stButton button {{
  border-radius: 0; border: 1px solid var(--rule-strong); background: var(--paper);
  color: var(--ink); font-size: 12px; font-weight: 600; padding: 0.2rem 0.7rem;
}}
.stButton button:hover {{ background: {PAPER_RAISED}; border-color: var(--ink); }}
section[data-testid="stSidebar"] {{ background: {PAPER_RAISED}; border-right: 1px solid var(--rule-strong); }}
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
        "labelFont": "Public Sans", "labelFontSize": 10, "labelColor": "#6B675F",
        "titleFont": "Public Sans", "titleFontSize": 10, "titleColor": STALE,
        "titleFontWeight": 600, "titlePadding": 8,
        "domainColor": RULE_STRONG, "domainWidth": 1,
        "tickColor": RULE_STRONG, "tickSize": 3,
        "gridColor": RULE, "gridWidth": 1, "gridDash": [],
        "labelPadding": 4,
    }
    return alt.theme.ThemeConfig({
        "config": {
            "background": PAPER,
            "font": "Public Sans",
            # No continuousWidth: charts size to their container instead.
            "view": {"stroke": None, "continuousHeight": 260},
            "axisX": {**axis, "grid": False},
            "axisY": {**axis, "grid": True, "ticks": False, "domain": False},
            "line": {"color": INK, "strokeWidth": 1.4},
            "bar": {"color": INK},
            "point": {"color": INK, "size": 14},
            "rule": {"color": RULE_STRONG},
            "legend": {
                "labelFont": "Public Sans", "labelFontSize": 10, "labelColor": INK,
                "titleFont": "Public Sans", "titleFontSize": 10, "titleColor": STALE,
                "titleFontWeight": 600, "symbolType": "square", "symbolSize": 70,
                "orient": "top", "direction": "horizontal", "offset": 6,
                "padding": 0, "titlePadding": 6,
            },
            "title": {
                "font": "Public Sans", "fontSize": 11, "fontWeight": 700,
                "color": INK, "anchor": "start", "offset": 8,
                "subtitleFont": "Public Sans", "subtitleColor": STALE, "subtitleFontSize": 10,
            },
            "range": {"category": [INK, ORANGE_BOOK, PURPLE_BOOK, OXBLOOD, STALE]},
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


def age(iso: str | None) -> tuple[str, str]:
    """(label, state) for a timestamp. State is fresh, warn, or unk.

    The API reports a last-fetch time for prices only, so every other source resolves
    to unk until a refresh runs in this session. Showing unk is the honest answer; an
    invented age would be worse than none.
    """
    if not iso:
        return "not reported", "unk"
    import datetime as _dt
    try:
        stamp = _dt.datetime.fromisoformat(str(iso).replace("Z", "").strip())
    except ValueError:
        return "not reported", "unk"
    delta = _dt.datetime.now() - stamp
    mins = delta.total_seconds() / 60
    if mins < 60:
        return f"{int(mins)}m", "fresh"
    if mins < 60 * 24:
        return f"{int(mins // 60)}h", "fresh"
    days = int(mins // (60 * 24))
    return f"{days}d", "warn" if days >= 7 else "fresh"
