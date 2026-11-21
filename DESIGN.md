---
name: Novatalis Lens
description: An equity research terminal for biopharma, built as a measuring instrument.
colors:
  ground: "#0C1417"
  panel: "#131E22"
  rule-faint: "#162125"
  rule: "#1F2E33"
  rule-strong: "#2E4249"
  text: "#E8EDEA"
  muted: "#7E9098"
  up: "#4C9A7A"
  down: "#C4553B"
  flag: "#D9B26B"
  phase-preclinical: "#2E4A52"
  phase-1: "#3E6B72"
  phase-2: "#5A9089"
  phase-3: "#93AE77"
  phase-filed: "#D9B26B"
  phase-approved: "#E8EDEA"
  orange-book: "#C98A4B"
  purple-book: "#8B7FC7"
  engine-biotech: "#D4883F"
  fda: "#5B9BE6"
  fda-bio: "#4FB3BF"
  active-wash: "color-mix(in oklab, #131E22 86%, #4C9A7A)"
  flag-wash: "color-mix(in oklab, #131E22 88%, #D9B26B)"
  up-wash: "color-mix(in oklab, #0C1417 84%, #4C9A7A)"
  down-wash: "color-mix(in oklab, #0C1417 84%, #C4553B)"
typography:
  display:
    fontFamily: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: "28px"
    fontFeature: "'tnum' 1, 'lnum' 1"
  headline:
    fontFamily: "'Archivo', -apple-system, 'Segoe UI', system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 600
    lineHeight: "28px"
  title:
    fontFamily: "'Archivo', -apple-system, 'Segoe UI', system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: "20px"
  section-label:
    fontFamily: "'Archivo', -apple-system, 'Segoe UI', system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 700
    letterSpacing: "0.055em"
  body:
    fontFamily: "'Archivo', -apple-system, 'Segoe UI', system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: "20px"
  label:
    fontFamily: "'Archivo', -apple-system, 'Segoe UI', system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: "16px"
  micro-label:
    fontFamily: "'Archivo', -apple-system, 'Segoe UI', system-ui, sans-serif"
    fontSize: "9.5px"
    fontWeight: 400
    letterSpacing: "0.07em"
  col-head:
    fontFamily: "'Archivo Narrow', 'Archivo', 'Arial Narrow', sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: "16px"
  figure:
    fontFamily: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace"
    fontSize: "17px"
    fontWeight: 500
    lineHeight: "22px"
    fontFeature: "'tnum' 1, 'lnum' 1"
  meta:
    fontFamily: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: "14px"
    fontFeature: "'tnum' 1, 'lnum' 1"
  prose:
    fontFamily: "'Newsreader', 'Iowan Old Style', Georgia, serif"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  none: "0px"
  small: "2px"
spacing:
  sp-4: "4px"
  sp-8: "8px"
  sp-12: "12px"
  sp-16: "16px"
  sp-24: "24px"
  sp-32: "32px"
components:
  button:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.small}"
    padding: "0 10px"
    height: "26px"
  button-hover:
    backgroundColor: "{colors.rule-strong}"
  button-pressed:
    backgroundColor: "{colors.active-wash}"
  segmented-item:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.muted}"
    rounded: "{rounded.none}"
    padding: "0 8px"
    height: "26px"
  segmented-item-selected:
    backgroundColor: "{colors.active-wash}"
    textColor: "{colors.text}"
  chip:
    textColor: "{colors.muted}"
    typography: "{typography.label}"
    rounded: "{rounded.small}"
    padding: "0 6px"
    height: "18px"
  input:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.text}"
    rounded: "{rounded.none}"
    padding: "0 8px"
    height: "26px"
  tab:
    textColor: "{colors.muted}"
    typography: "{typography.label}"
    padding: "0.3rem 0"
  tab-selected:
    textColor: "{colors.text}"
  lead-box:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.none}"
    padding: "0.35rem 0.6rem"
  tooltip:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.small}"
    padding: "8px 10px"
  state-block:
    textColor: "{colors.text}"
    padding: "8px 12px"
  state-block-flag:
    backgroundColor: "{colors.flag-wash}"
  state-block-down:
    backgroundColor: "{colors.down-wash}"
---

# Design System: Novatalis Lens

## Overview

**Creative North Star: "The Instrument"**

Novatalis Lens is drawn as a measuring instrument. Every mark on the screen is a
reading: a figure, a date, a bar, a tick. The chrome is two dark surfaces and a hairline,
and it carries no hue at all. Colour is spent only where it encodes something: the
direction of a move, how far a compound is from market, which FDA book a product sits
in, and whether a value still needs review. The stylesheet says it in its own words:
"an instrument, not a landing page".

The system is dense and flat. A full tab fits one 1440 px screen with little scrolling,
at a 14 px base with most labels between 9.5 and 12.5 px. Sections are separated by a
rule and a caps label, never by a card. Three type roles do three separate jobs:
Archivo for structure, IBM Plex Mono for anything measured, and Newsreader for the one
thing that is written rather than computed, the analyst note.

One surface breaks the density on purpose: the front door. It is a single wheel of three
drawn motifs, one per engine, with the NOVATALIS wordmark and no figures. Everything
behind it is the instrument.

**Key Characteristics:**
- Dark only. Deep petrol ground, one raised panel tone, hairlines in three weights.
- Hue means something or it is absent. Chrome is neutral.
- Square corners. Radius is 0, or 2 px on small controls.
- Figures in tabular mono so columns hold when values refresh.
- A missing value is drawn as missing (a dash, a hatch, a broken line), never as zero.
- Every chart is a hand-built SVG from the token set.

## Colors

A cold, low-chroma petrol ground with warm paper-white text, and a small set of muted
hues that each carry one meaning.

### Primary
- **Measured Green** (`up`): the positive direction and the measured series in a chart.
  It is also the selection colour: the 2 px tab underline, a chosen segment, the focal
  row's rail. Because it means "up" as well, selection is always paired with a border,
  a weight change or a glyph.

### Secondary
- **Cliff Red** (`down`): the negative direction, a stopped trial, an error block. One
  pole only; it has no lighter or darker sibling.
- **Review Amber** (`flag`): a material change, an uncurated or unannounced item, an
  analyst-edited input, a value whose source is not on file. It reads "look at this",
  not "bad".

### Tertiary
- **Phase ramp** (`phase-preclinical`, `phase-1`, `phase-2`, `phase-3`, `phase-filed`,
  `phase-approved`): ordinal, brightness rising toward market, from dim petrol through
  sage to amber at filing and paper white at approval. Seamless phases take the colour
  of the phase they reach (Phase 2/3 is drawn as Phase 3).
- **Orange Book Ochre** (`orange-book`) and **Purple Book Violet** (`purple-book`):
  small molecule and biologic. Violet also marks clinical and pipeline content in the
  research primitives.
- **Burnt Orange** (`engine-biotech`): the biotech engine's identity on the front door
  only.
- **FDA Blue** (`fda`) and **BLA Teal** (`fda-bio`): approvals, PDUFA and decision dates
  on the Universe tab; blue for an NDA, teal for a biologic's BLA.

### Neutral
- **Deep Petrol** (`ground`): the page. The absence of signal.
- **Raised Petrol** (`panel`): controls, lead boxes, overlays, a table row on hover.
- **Hairline** (`rule`): gridlines, table row borders. **Structural Hairline**
  (`rule-strong`): section rules, control borders, axis domains. **Faint Grid**
  (`rule-faint`): the full mesh behind a dense price chart, so the grid does not compete
  with the series.
- **Paper White** (`text`): text, the focus ring, an approved phase.
- **Slate** (`muted`): labels, axis text, units, timestamps, stale values.

### Derived washes
Four tints mixed from tokens with `color-mix(in oklab, ...)`, never written as literals:
`active-wash` (focal row, chosen control), `flag-wash` (flagged cell, warning block),
`up-wash` and `down-wash` (an operating trend above or below zero, an error block). On
any wash, Slate fails AA, so secondary text on a wash turns to Paper White.

### Named Rules
**The Two Files Rule.** A colour or spacing value is written in
`frontend/assets/tokens.css` and `frontend/components/tokens.py` and nowhere else. A
test keeps the two in step. Everything else reads a token or a `color-mix()` of tokens.

**The Second Signal Rule.** Colour is never the only signal. Every coloured mark also
carries a label, a glyph or a position. A down chip draws its own triangle; a phase
colour sits beside the phase name.

**The Spoken-For Rule.** A hue that already means something is not borrowed for
something else. Amber is "filed" on the phase ramp and "needs review" everywhere else,
which is why a panel vote takes ochre and the biotech engine got its own orange.

## Typography

**Structure Font:** Archivo (with -apple-system, Segoe UI, system-ui), and Archivo
Narrow for dense column heads
**Figure Font:** IBM Plex Mono (with ui-monospace, SF Mono, Menlo)
**Prose Font:** Newsreader (with Iowan Old Style, Georgia)

All three ship locally in `frontend/assets/fonts` and are inlined as base64
`@font-face` rules. Nothing loads from a CDN.

**Character:** A plain grotesque for labels, a mono with tabular lining numerals for
every reading, and a text serif reserved for sentences a person is meant to read as
research. The pairing sorts content by kind: structure, measurement, judgement.

### Hierarchy
- **Display** (Plex Mono 600, 24px/28px): the one figure a conclusion banner states.
  Never coloured up or down.
- **Headline** (Archivo 600, 21px/28px): the sentence beside that figure.
- **Title** (Archivo 600, 15px/20px): a section title inside the research tabs.
- **Section label** (Archivo 700, 12.5px, 0.055em, uppercase): the caps label on a
  section rule across the shell.
- **Body** (Archivo 400, 14px/20px): the base size and the rem root.
- **Label** (Archivo 500, 12px/16px, Slate): KPI, form, chip and tab labels.
- **Micro label** (Archivo, 9.5px to 10.5px, 0.07em to 0.08em, uppercase, Slate): the
  key above a tile's value, a basis tag, a control-group key.
- **Column head** (Archivo Narrow 600, 12px/16px): dense table headers.
- **Figure** (Plex Mono 500 to 600, 17px/22px, tabular): KPI and tile values. Table
  cells use the same face at 11px to 12px.
- **Meta** (Plex Mono 400, 11px/14px, Slate): units, timestamps, period lines.
- **Prose** (Newsreader 400, 13.5px, line-height 1.5, max 68ch): the morning note.
  Short prose leads elsewhere run 14px to 15px, capped near 74ch.

In the research primitives every size is `calc(<px> * var(--ts))`, so a text-size
setting of 13, 14 or 15 scales the whole view together.

### Named Rules
**The Measured In Mono Rule.** Anything measured or identified is Plex Mono with
tabular lining numerals: figures, tickers, dates, application numbers. A negative uses a
true minus (U+2212), not a hyphen.

**The One Written Voice Rule.** Newsreader is for prose a person wrote or the note
engine composed. It never sets a label, a heading or a figure.

**The Caps Are Labels Rule.** Uppercase belongs to section labels, micro labels,
tickers and marker letters. A sentence, a headline and a money figure keep their own
case.

## Layout

A desktop instrument, full width, sized for 1440 px. The page container has 16 px side
padding and no max width. The base unit is 8 px and every gap is a multiple of it, with
a 4 px half step: 8 px between stacked blocks, 16 px between columns, 24 px between
sections, 12 px inside a card.

- **Top bar:** sticky, on the ground colour with a structural hairline under it. Ticker
  selector, company name and filing basis, jump-to search, engine switch, last refresh
  in mono, Refresh all.
- **Tab strip:** plain text under the top bar. The tab set depends on the company's
  engine.
- **Page width:** every tab takes the page's full width. A right-hand horizon rail
  (the time spine, one vertical axis in three scales) is retired: a rule meant to drop
  it on Universe hid it on every tab once a page had loaded, and it showed only while
  the page was loading. The `no-rail` marker survives as the spacing of a full-width
  tab (Forecast and Comps among them), and the spine's builders are kept.
- **Sections:** a hairline with a caps label on the left, an optional mono count on the
  right, and an optional boxed basis tag that states the period the figures cover. A
  label sits close to its content (about 0.55rem) and further from what came before
  (about 0.9rem), so the gap between sections does the separating.
- **Density:** table rows are 30 px by default, 26 px compact, 36 px comfortable.
  Controls are 26 px high, chips 18 px.
- **Responsive:** the shell tightens at 1400 px (container padding to 8 px, fewer lead
  boxes per row). The Universe tab is built to fit one 1440 by 780 screen and stacks
  under 1180 px. Further steps at 1100, 900 and 700 px collapse multi-column bands.
  There is no phone layout.

## Elevation & Depth

Flat. Depth is tonal and linear: ground, one raised panel tone, and hairlines. Sections
are not boxed. Overlays (popover, menu, tooltip, drawer) are a panel fill with a 1 px
structural border and no shadow, stacked by z-index alone.

### Shadow Vocabulary
- **Focal rail** (`box-shadow: inset 2px 0 0 var(--up)`): an inset line, not a shadow.
  Marks the company or row in focus, together with `active-wash`. Variants run along
  the top or bottom edge of a selected cell.
- **Floating card** (`box-shadow: 0 10px 28px color-mix(in oklab, var(--ground) 70%, transparent)`):
  the only cast shadow, used on the Universe tab for a card that floats over the board.
  It is mixed from the ground, not from black.

### Named Rules
**The Hairline Rule.** A section is a rule and a caps label, never a card. Structure
comes from `rule-strong`; rows and grids from `rule`; the mesh behind dense data from
`rule-faint`.

## Shapes

Square. The radius scale has two steps: 0 for inputs, selects, lead boxes, tables and
every shell button, and 2 px for small controls in the research primitives (buttons,
chips, tags, key hints, tooltips, the outer corners of a segmented control). Full
circles appear only as data marks: chart points, timeline dots, the engine wheel.

Borders are 1 px. A 2 px left border is an accent rail that names a kind: on a lead box
it carries the event's colour, on a state block the severity, on a clinical chip the
violet. Excluded cells and loading skeletons use a 135 degree hairline hatch, and a
null bar in a chart takes the same hatch.

## Components

### Buttons
Quiet and square. A button is a bordered panel, not a filled accent.
- **Shape:** 26 px high, 2 px radius in the research primitives; shell buttons are
  radius 0 at 12 px, weight 600.
- **Default:** Raised Petrol fill, Paper White text, 1 px structural border.
- **Hover:** fill steps to the structural hairline colour, 100 ms linear.
- **Primary:** the same button with a Measured Green border. There is no filled primary.
- **Pressed or expanded:** green border and `active-wash` fill.
- **Link:** text only in Measured Green, underlined on hover.
- **Disabled:** 50% opacity, `not-allowed`.

### Segmented controls
Joined buttons, 26 px high, 12.5 px weight 600. Unselected items are Slate on panel;
the selected item takes a green border, `active-wash` and Paper White text. Only the
outer corners are rounded (2 px).

### Chips
- **Style:** 18 px high, transparent, 1 px structural border, Slate label at 12 px
  weight 500, 2 px radius.
- **Tones:** active (green border and text), flag (amber border and text), up and down
  (coloured border plus a triangle the chip draws itself, label in Paper White),
  clinical (2 px violet left border), analyst (amber border), basis (10 px mono).
- **Markers:** a fixed 12 px slot after a number holds a tag letter: A reported, E
  street estimate, G guidance, M model. An empty slot keeps decimal points aligned.

### Lead boxes
The headline and forward-view unit on Universe and Key insights. A native disclosure on
the panel colour with a 1 px border and a 2 px left rail in the kind's colour (deal,
approval, PDUFA, readout hit or miss, panel, filing, LOE). Closed: a mono chip naming
the kind, a mono date on the right, the headline below with the ticker leading. Open:
spans two columns and shows a terms table and the verbatim source quote. Hover lifts 1
px and strengthens the border over 120 ms.

### Tiles and KPI strips
Not cards. Rows that stand one above another share one grid of eight tracks, a tile
taking one or two, so every tile edge in one row is an edge in the others (the
Financials tab). A row of cells divided by 1 px hairlines: a micro label, a mono value at
about 17 px weight 600 with its unit small and Slate beside it, an optional delta in
mono, and a muted note line. A missing value drops to weight 400 in Slate. In a KPI
strip the primary cell takes one and a half shares and a green top border.

### Tables
Two tables exist and they differ in the head. The reference table (terms, lenses,
fair value) has collapsed borders and a 12 px body; its header cells are mono, 10 px,
weight 600, 0.06em, in Slate on the panel colour, with a structural rule below. The
statement grid on Financials sets its period heads in Archivo Narrow at 10.5 px with
no fill, its labels in Archivo at 12.5 px and its figures in mono at 12 px, and has no
row hover yet. In both, keys are Slate or text on the left and values are mono and
right-aligned. Rows are divided by `rule` and take
the panel colour on hover. A total row is weight 700 with a structural rule above it.

### Inputs
- **Style:** 26 px high in the primitives (30 px on Streamlit's own widgets), radius 0,
  1 px border, mono text for anything numeric, placeholder in Slate.
- **Analyst-edited:** dashed amber bottom border with an "Analyst" chip beside it.
- **Focus:** the global ring.

### Navigation
A plain text tab strip on a structural hairline. Tabs are 12 px weight 500 in Slate
with a 1.1rem gap; the selected tab is Paper White at weight 700 with a 2 px Measured
Green underline. No pills, no icons.

### State blocks
A 2 px left bar and two lines of 13 px text, with an optional action on the right.
Info: Slate bar, no fill. Flag: amber bar on `flag-wash`. Error: red bar on
`down-wash`.

### Focus
One ring everywhere: `outline: 2px solid` Paper White, offset 1 px, inset 2 px inside
table cells. It is never removed.

### Motion
State changes only. The research primitives cap at 100 ms linear (`--motion`); the
shell uses 120 ms to 140 ms for a hover lift or a chevron turn. The front door alone
runs longer, 300 ms to 400 ms on its caption. `prefers-reduced-motion` zeroes all of
it.

### Charts
Every chart is a pure function from data to an SVG string in
`frontend/components/charts.py`, drawn at an explicit width and height and inlined into
the page. Axis text is Slate at about 10 px; series take token colours; a legend or
direct label always accompanies colour. A null breaks the line, hatches the bar or
leaves the heatmap cell as ground.

### The time spine
A continuous vertical axis, three compressed scales stacked without a break, with ticks
at the real catalyst and expiry dates. It was written as the signature component, a
rail on the right of single-company tabs, and it is built (`charts.timeline_spine`) but
not on the page: see Page width above. Putting it back takes a quarter of the width
from every tab it stands beside, so it is a decision and not a repair.

### The front door
One wheel of three wedges, each a drawn motif in its engine's colour (green, violet,
burnt orange), on the bare ground. The NOVATALIS wordmark sits top left in Archivo 700,
0.95rem, 0.26em caps. The wheel is the hit area; hovering a wedge shows it is live. It
carries no figures.

## Do's and Don'ts

### Do:
- **Do** take every colour from a token or a `color-mix()` of tokens, and add a new
  token to both `tokens.css` and `tokens.py` when a new meaning needs one.
- **Do** pair every use of colour with a label, a glyph or a position.
- **Do** set figures, tickers, dates and identifiers in IBM Plex Mono with tabular
  numerals, right-aligned in tables, with a true minus.
- **Do** draw a missing value as missing: a dash in Slate, a hatched band, a broken
  line. State why in place where the reason is known ("no free data").
- **Do** open a section with a hairline and a caps label, and put the period its
  figures cover in the boxed basis tag when two sections on a page differ.
- **Do** build charts through `frontend/components/charts.py` as inline SVG.
- **Do** set `font-family` on the class of any text injected through Streamlit
  markdown. Streamlit's markdown container sets its own face, so a class that relies on
  inheriting Archivo from the page renders in Streamlit's default sans.
- **Do** keep the focus ring and honour `prefers-reduced-motion`.

### Don't:
- **Don't** write a colour literal or a spacing constant outside the two token files.
- **Don't** use a radius above 2 px. Streamlit's native segmented control still ships
  its own rounded corners; the house segmented control is square with 2 px outer
  corners.
- **Don't** wrap a section in a card or give a resting surface a shadow.
- **Don't** spend hue on chrome. A button, a border or a heading that is green, amber
  or red is making a claim about data.
- **Don't** reuse a hue that already carries a meaning for a second meaning.
- **Don't** plot a null as zero.
- **Don't** set labels, headings or figures in Newsreader, or prose in mono.
- **Don't** use native Streamlit or Altair charts. A chart rendered inside a hidden
  Streamlit tab is measured at a few pixels and collapses.
- **Don't** design a light theme against this file. The light palette in `theme.py` is
  kept for tests only; the running app is always dark.
