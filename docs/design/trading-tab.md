# Trading tab: a thesis board with the Ask box beside it

Drafted 2026-11-23. What is built, and where it differs from this, is in the last section.

## What the page is for

One place to dig into every side of a company on the way to an investment thesis. The
reader puts up any set of panels, each for the top bar's company or pinned to another,
asks the book about what is in front of them, and saves the arrangement by name.

It is a research view over reads the book already has. Nothing on it is a signal, an
order or advice.

## The problem today

Forming a view of one company means walking twelve tabs. Each tab is built for one
subject. Three reads the API serves have no page at all: company news
(`/companies/{t}/news`), the filings list (`/companies/{t}/filings`) and positioning
(`/companies/{t}/positioning`). The Ask box sits alone on the last tab, away from
anything a reader would want to look at while asking.

## The page

```
[ board: Readout prep v ] [Save] [Save as] [+ Add panel v] [Columns 1 2 3] [Ask beside: on]
+---------------------------------------------------+---------------------------+
| Price  LLY                    (wide)              |  Ask the book             |
|  live chart, fixed height                         |  the same conversation    |
+-------------------------+-------------------------+  as the Ask tab, per      |
| What changed  LLY       | Company news  LLY       |  company                  |
+-------------------------+-------------------------+                           |
| Latest results  LLY     | Price  NVO (pinned)     |  [ question box ]         |
+-------------------------+-------------------------+---------------------------+
No signal in the register has passed the test (read from /signals).
```

- **Choosing panels.** "Add panel" lists the registry by group. Each panel's header has a
  small menu: company (follow the top bar, or pin a ticker), wide or normal, move up,
  move down, remove.
- **The company.** A panel follows the top bar unless pinned. Pinning is how several
  companies sit side by side. There is no second mode and no second top bar.
- **How many fit.** A panel body is capped in height with its own scroll; the price panel
  has a fixed height. A board holds up to 12 panels, at most 4 of them live price charts.
- **Remembered.** Named boards in `backend/cache/trading_layouts.json`, read and written
  through the API, with the open board's name in the address as `?board=`.
- **Historical mode.** The board is the live book. With a sidebar date set it says so in
  one line and draws nothing else.

## The panels

Every panel is one entry in `frontend/trading_view.PANELS`: id, title, group, size, cost,
the reads it makes, and whether it is private. A new panel is a registry entry, a builder
and a test.

| Group | Panel | Reads | Cost |
|---|---|---|---|
| Market | Price chart, live | `/prices`, `/prices/live`, `/approvals`, `/forecast-history`, `/why-moved` | live |
| Market | Price against the call | `/prices`, `/fair-value`, `/street` | heavy when cold |
| Market | Against the sector | `/relative` | light |
| Market | Compare prices | `/prices` for each ticker | light |
| News | Company news | `/companies/{t}/news` | light |
| News | What changed | `/changes?ticker=` | free for the top bar's company |
| News | Sector news | `/pulse?days=14` | light |
| News | Deals | `/companies/{t}/deals` | light |
| Fiscal | Latest results | `/report` | light |
| Fiscal | Filings | `/filings` | light |
| Fiscal | Guidance and street | `/street` | heavy when cold |
| Fiscal | Statement trend | `/statements` | light |
| Fiscal | Cash and runway | `/cashflow`, `/runway` | light |
| Catalysts | Dated ahead | `/catalysts?within_days=&ticker=` | light |
| Catalysts | At stake | `/catalysts/stakes`, `/gate-odds` | heavy when cold |
| Catalysts | Readouts landed | `/readout-reports` | light |
| Catalysts | Pipeline | `/programmes` | light |
| Catalysts | Trials | `/trials` | light |
| Catalysts | Loss of exclusivity | `/exclusivities` | light |
| The book's view | Fair value range | `/fair-value` | heavy when cold |
| The book's view | What breaks it | `/breakpoints` | heavy when cold |
| The book's view | The book's dated calls | `/calls/{t}` | light |
| Positioning | Short interest, insiders, holders | `/positioning?parts=short,insiders,holders` | light after the first read |
| Positioning | Options | `/positioning?parts=options` | a live call each press |
| Your record | Theses logged | `/theses` | light |
| Your record | My position | `/portfolio/mine` | private, live |
| Free-form | Desk read | any read tool in `mcp_tools.TOOLS` | as the tool |

"Fiscal news" is the Fiscal group. Latest results and Filings answer what the company
just reported; the other three are the context for reading them.

Not offered as panels:

- **The Comps frame and the redesigned Catalysts frame.** Each is one full-screen frame
  with its own workspace. The board points to their tabs.
- **The Forecast tab.** It is an editor that writes assumptions. The board reads only.
- **Signals.** `/signals` reports that none has passed. The board says that in one
  standing line built from the route's own verdicts and offers no signal panel.

## The Ask box on the board

- The same box as the Ask tab, drawn a second time under a key prefix. The conversation
  is kept per company, so both places show the same exchange.
- The model is told which panels are open: a list of panel ids and tickers, never a
  figure, a row or a panel's contents. `desk_chat` keeps its own list of known ids and
  drops anything else, so no free text from the page reaches the system prompt.
- A private panel is left out of that list unless `CHAT_ALLOW_PORTFOLIO=1`. The frontend
  leaves it out and `desk_chat` drops it again. The tool gate is unchanged.

## How it behaves

- **The board is a fragment** and the Ask column is its sibling. A click on the board
  reruns the board; asking reruns the box; neither reruns the other tabs.
- **A hidden board costs almost nothing.** The page runs every tab on every rerun, so the
  board's reads go through one reader held for 60 seconds and cleared by a refresh.
- **The live price** reads `/prices/live`, which the API holds for 55 seconds and which
  writes nothing. Each pinned ticker adds two Yahoo requests a minute while its market
  is open, which is the reason for the cap of four.
- **A heavy panel does not hold the page.** It reads with a short limit. On a cold cache
  it says the book is still working the figure out and offers to try again; the failure
  is held for 30 seconds so a rerun does not stack a second valuation behind the first.
- **Options** are read only when the button is pressed.
- **Saving a board clears no cache.** `/desk/` is in `NEVER_PATHS` and `QUIET_WRITES`, and
  the file sits outside `data/` and the database, so the stamp does not move.

## What it refuses

- No order entry, no broker action, no account change. The broker fetcher is GET only and
  `test_broker_read_only.py` holds it there.
- No advice: no buy, sell or target wording in any title, byline or empty state.
- No signal shown as a signal, and no score that combines reads.
- No write to the book. The board's one write is its own layout file.
- No tearsheet or brief button: both are writes that clear the whole cache.

## How it is checked

- `test_trading_view.py`: the registry, the packing, each builder on plain dicts, the
  house style over every word printed, and that the module touches no Streamlit, network
  or clock.
- `test_desk_chat.py`: the on-screen sentence, the ids it drops, the private panel.
- `test_ask_route.py`, `test_desk_layout.py`, `test_response_cache.py`: the route, the
  boards file, and that a save clears nothing.
- `test_trading_page_ui.py`: the board drawn offline on fixtures, and no widget key
  shared with the Ask tab or the Prices tab.
- `test_broker_read_only.py`: the fetcher's source, and that no route takes an order.

## Order of work

1. This note, and the broker guard.
2. The registry and the packing.
3. The tab, with What changed, Company news and Dated ahead.
4. The Ask box beside the board.
5. The model is told which panels are open.
6. The fiscal panels.
7. The price block becomes a function; the live price panel.
8. Boards saved on this machine.
9. A panel can be pinned to a company.
10. The book's view, and the standing line from `/signals`.
11. Positioning.
12. Your record.
13. The second set of panels.
14. Any desk read as a panel.
15. The record of what was built.

## Decisions taken before step 1

1. One company by default, several by pinning a panel.
2. "Fiscal news" is five panels, led by Latest results and Filings.
3. The tab sits before Ask, and the Ask tab stays.
4. Twelve panels a board, four live price charts.
5. Options behind a button, because every read of it is a live call to Cboe.
6. Working notes are left out until where to keep them is settled. Not the database: a
   write there moves the stamp every valuation is held against.

## What was built, 2026-11-23 and 24

Steps 1 to 9, on branch `claude/trading-tab`. Steps 10 to 15 are not built.

The tab sits beside Ask. A board holds up to twelve panels of seven kinds: Price chart,
What changed, Company news, Latest results, Growth and margin, Filings and Dated ahead.
Three menus sit above it. Boards saves the board on screen under a name, opens a saved
one and deletes the open one. Add panel lists the kinds by group and takes the company
the panel is for. Arrange is the board as rows: whose each panel is, whether it takes the
full width, a place earlier or later, and off. The Ask box sits in a column beside the
board, and a question asked there goes with the names of the open panels.

Measured on Lilly at 1440 by 900, two across beside the Ask box: the price chart across
the board's width, and the top half of the row under it. A panel's body is 340 px and
scrolls inside itself; the price chart is 300 px and does not grow. The board's reads of
the API each answer in about a millisecond from the response cache, and the board holds
each for a minute, so a full run of the page with the board hidden adds no read within
the minute. The live price is the exception: it is asked on every run, of an API that
holds its answer for about 55 seconds.

Decisions taken while building:

- **A panel leads with a figure, not a list.** The first board was three lists of dated
  rows and the reader asked for something better to look at. What is dated, said, filed
  or changed is drawn on a time grid first (`charts.unit_lanes`: a row a lane, a column a
  period, a square an event), the few items that matter are named under it, and the
  whole list is folded beneath, one click away. A lane with nothing in it is still drawn,
  because an empty Phase 3 row is a finding.
- **What each figure is.** Dated ahead: 24 months by month, a row a phase in the phase
  ramp's colours. Company news: a year by month, a row a source. Filings: two years by
  month, a row a form, annual filled and quarterly an outline. What changed: 30 days by
  day, a row a rating, the review amber on the top rating alone.
- **A phase is read from the start of the registry title** ("Phase 3, a study of ..."),
  which is where the calendar's derivation writes it. A row whose title does not start
  with one sits in Other; nothing is guessed.
- **A month-only date is a month.** The calendar stores such a readout as "2026-12". It
  was being dropped as no date at all. It is placed in its month and never printed with
  a day, and how far off it is is counted in months.
- **The pulse takes the review amber** and the label "Pulse (AI)", since amber is the
  app's "uncurated, look at this" and a model's summary of the trade press is that.
- **The price panel is a second composition of the Prices tab's builders, and the Prices
  tab is untouched.** The plan had its closure cut out into a shared function. The logic
  already lives in `price_chart.py`; what would have been shared is glue, at the cost of
  a refactor of a page that works. The panel is daily bars only, with a window and line
  or candle. The intraday views, the fair value line and why the price moved stay on
  the Prices tab.
- **The chart component has a height it keeps** (`fill=False`), and a fixed-height chart
  fits its bars again when its width changes. Drawn in a hidden tab it is a few pixels
  wide, and the bars stayed bunched at the right edge when the tab was shown.
- **The board is one value in the session and no widget is the record.** Every control
  changes it through a callback, which runs before the page is drawn, and each widget is
  set from the board on every run. A row of the arranger is keyed by its place, and a
  place holds a different panel after a move.
- **The API holds a board's shape and the frontend knows the kinds.** A board saved by
  another version opens without the panels this one lacks and says which.
- **The open board's name is not in the address.** The plan had `?board=`. The board
  that opens next time is remembered with the boards, which is what was asked for.
- **A list is measured against its own panel**, by a container query on the panel's
  body: narrow, a row is the date and the headline with the qualifier under them.
- **A panel is a section, not a card.** A rule and a caps label from the house's own
  `section`, with the company in the basis tag and "pinned" where it is.
- **A private panel is never named to the model**, whatever `CHAT_ALLOW_PORTFOLIO` says.
  The plan had the switch let it through. The switch offers a tool the model has to ask
  for; naming a holdings panel beside a ticker would tell it unasked.
- **What is on screen is read when the question is sent**, from the session, since the
  board and the box are separate fragments.
- **The board's held reads are cleared through `api_get.clear`**, the call every handler
  that changes the book already makes.

Not in this version:

- Cash and runway. Its block on Financials makes an unheld read of its own on every run
  of the page, which is what the board is built to avoid.
- The book's view, positioning, your record, the second set of panels and the desk read
  (steps 10 to 14), and the standing line from `/signals`.
- Working notes.

Not checked:

- Saving a board end to end in the running app. The copy's page was run against the API
  of the real checkout, which has no `/desk/layouts`, and the Boards menu says so there.
  The routes are tested through the app's own test client and the menu on stand-ins.
- A question asked of a model with the board's sentence in the prompt, for the same
  reason. `test_desk_chat.py` pins the prompt and `test_ask_route.py` the route.
- The price panel's one-minute tick with a market open. It was drawn with New York
  closed, and with the market open only on a stand-in.

## Panels you take hold of, 2026-11-24

Asked for the same day: panels you grab and move, and size by dragging a corner. The plan
had ruled drag and drop out ("Streamlit has none without a custom component"); this is
that component.

- **The board is a grid twelve columns wide**, rows of 24 px with the house's 16 px
  between rows and columns. A panel has a place and a size in cells, kept with the board
  and saved with it. The page lays the panels out with CSS grid, one rule a panel
  (`trading_view.grid_css`), so a board draws where it was left before any script runs.
- **Moving and sizing.** A panel is moved by its heading and sized by any of its four
  corners. While it is held, an outline snapped to the grid's cells shows where it will
  land. On release the place goes to Python, and `trading_view.place` settles the board:
  a panel in the way is pushed down, then every panel rises as far as the one above it
  allows, so no two overlap and the board has no holes. A panel dragged down into empty
  space therefore rises to the first free row: the board keeps no gaps.
- **The frame (`components/boardgrid`) draws only in a layer of its own** laid over the
  panels by measuring them, and never adds to or changes what Streamlit draws: a script
  that wrote into Streamlit's own elements would fight its rendering. It is under the
  page's sticky top bar, hides its handles while the tab is closed, and takes its layer
  and listeners away when its frame goes.
- **A drag is applied once.** The frame keeps returning the last drag on every run, so
  each carries the frame's token and a count, and the last one applied is remembered.
- **Panels are keyed by an id** (`p1`, `p2`, ...), not by where they sit, so a panel
  moved keeps its own settings, such as the price chart's window.
- **A new panel goes in the first place it fits**, reading from the top left.
- **Arrange keeps a keyboard way** to do what a drag does: a place earlier or later in
  reading order, and off; and it lays the whole board out afresh one, two or three
  across. The "N across" control and the "Wide" switch are gone: size is now what the
  corners set.
- **A board saved before the grid** opens laid out as it was drawn then.
- **A panel's height is what it is made.** Each body scrolls inside its panel, and the
  price chart takes the panel's height less what is drawn round it.

Checked in the copy at 1440 by 900: the price chart shrunk to half width by its bottom
right corner and the panels under it rose into the free half; Company news moved by its
heading to the top left and the chart pushed below it; the snapped outline shown
mid-drag; the bottom left corner dragged to put the chart on the right. The script itself
is not run by the suite (no `node`); its rules are held by reading it.

## What a reader wants to see, 2026-11-24

The reader found the board hard to use: the price chart's controls took more room than
the chart, the chart was a line, and the other panels were full of records that do not
move a price. Changed:

- **The price chart is candles**, a day a candle up to six months, a week for a year and a
  month for five (`trading_view.candles`), so a candle's body can always be read. It opens
  on six months. The line-or-candle switch is gone, and the window is a row of five
  two-letter choices the height of a chip, on one line with the last close, the window's
  change and its range. The live status moves from the rule into the notes.
- **A Fundamentals panel** opens second, the board's width: one grid of tiles, the figure
  first and large. Growth (the last quarter's revenue and its growth, net margin, EPS
  against the street, the move on the day it reported), the outlook (revenue guidance and
  whether it was raised, the street's EPS for this year and the growth to the next, the
  street's target against the close with its rating count as the street gives it),
  valuation and the balance sheet (the close over the street's EPS, free cash flow and its
  margin, net debt to EBITDA, runway where it is counted, revenue losing exclusivity
  within five years), and the price against its sector fund. Every figure is a read's
  own, or a ratio of two named on its tile; a ratio across currencies is not drawn; an
  optional tile with no figure is left out.
- **Material changes** replaces What changed: only readouts, approvals and regulatory
  steps, results, deals and financings, a trial stopped or redesigned, a leader named, and
  exclusivity, over 90 days by week (`trading_view.material`). Revenue lines restated,
  filings indexed and registry dates nudged, most of the feed, are left to Universe.
- **Dated ahead** shows the events that move a price: Phase 3 readouts and regulatory
  decisions, or the Phase 2 readouts where there are none (`trading_view.moving`).
- **The default board** is the price chart, Fundamentals, Dated ahead and Material changes.
  Company news, Filings, Latest results and Growth and margin stay in Add panel.
- **A heavy read that fails is held for half a minute**, so a cold book does not make
  every click wait for the street's estimates again.

## Content that follows the panel, 2026-11-24

Asked for the same day: a panel's content should resize as the panel is dragged.

- **The board is laid out live while a panel is held.** The frame settles the board by
  Python's own rule, copied line for line into its script, and sets each panel's place
  on the grid in the page as the pointer moves: the held panel grows, shrinks or moves
  under the pointer, the panels round it make way, and every panel's content reflows as
  it goes. On release the place goes to Python, which settles the board itself; the live
  places are taken away a frame after Python's draw is in, so nothing jumps back. A drag
  that changes nothing, or is cancelled, takes them away at once. This is the one thing
  the frame sets on what Streamlit draws, and a test reads its script to hold it there.
- **A panel's body fills its panel at any size.** Python sets the body's height from the
  panel's rows on the first draw; a stylesheet rule makes it take whatever height is left
  under the rule after that, so the body follows the panel during a drag and not only on
  the next draw. Figures were already drawn to their panel's width.
- **The price chart follows its panel's height.** In a panel the chart takes the panel's
  height below it, less the legend and notes under it, and watches the panel's size, so
  it grows and shrinks with the drag. On the Prices tab it still fills the window.

Checked in the copy: the price chart's corner dragged from 12 by 13 cells to 6 by 10, the
chart redrawn at that size mid-drag and Fundamentals moved up under it before release;
after release Python's layout matched and the live places were cleared. The scripts are
not run by the suite; their rules are held by reading them.

## The Ask box as a panel, and two panels gone, 2026-11-24

Asked for the same day: take Dated ahead and Material changes away, make the Ask box
plainer to look at with no suggested questions, and let it be moved like the rest.

- **Dated ahead and Material changes are gone**, from the default board and from Add
  panel, with the builders and tests only they used. A board saved with either opens
  without it and says so. Every dated event is still on Catalysts and the change feed on
  Universe.
- **The Ask box is a panel**, "Ask the book", moved and sized like any other. The column
  beside the board and its switch are gone, and the board takes the page's width. One
  box a board; it is never named to the model as a panel on screen.
- **It opens on a blank box and one line** saying what it is for; the three suggested
  questions are gone. A question sits right-aligned on the raised tone, the answer is
  prose under a green rail with what it was read from folded under it, a failed answer
  has a red rail and the reason. The conversation scrolls inside the panel with the
  newest at its foot (the drag frame keeps it scrolled there), and the box sits square at
  the bottom with Clear beside it once there is something to clear. It is the Ask tab's
  conversation for the company, and the Ask tab is unchanged.
- **The default board fits one 1440 by 900 screen**: the price chart (8 by 11 cells) and
  Fundamentals (8 by 6) under it on the left, the Ask box (4 by 17) down the right.

## Five minutes, and news without a figure, 2026-11-24

- **The price chart has a five-minute view**, "5m", first among its choices: the latest
  session on file in five-minute candles, the book's stored five-minute bars with Yahoo's
  live ones laid over them (the live bar wins where both have one). Its figures are that
  session's last, change and range, named by the session's date. Approvals are not marked
  on it, and it ticks each minute while the session is open, as the daily view does.
- **Company news has no figure.** It leads with the newest six items as cards, each opening
  its source, and the rest are in the folded list. The figure by month and source, and
  the builders behind it, are gone.
