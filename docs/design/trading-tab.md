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

## What was built, 2026-11-23

Steps 1 to 5, on branch `claude/trading-tab`. Steps 6 to 15 are not built.

The tab sits beside Ask. The board holds three kinds of panel, What changed, Company news
and Dated ahead, picked from a row of pills and laid out one, two or three across for the
company in the top bar. The Ask box sits in a column beside it, with a switch to put it
away, and a question asked there goes with the names of the open panels.

Measured on Lilly at 1440 by 900: two across beside the Ask box shows the first row of
two panels whole and about half of the next; three across shows all three. A panel's body
is 340 px and scrolls inside itself. The board's two reads of the API (`/news` and
`/catalysts`) each answer in about a millisecond from the response cache, and the board
holds each for a minute, so a full run of the page with the board hidden adds no read
within the minute and two short ones after it.

Decisions taken while building:

- **Dated ahead is a list, not the Catalysts tab's month grid.** The grid is built for
  the page's full width and a panel has half of it or less. The list is one line an
  event, soonest first, and a month the registry gives with no day is shown as the month
  and marked "month only", never as the first of it.
- **A list is measured against its own panel.** Three across beside the Ask box left a
  headline a few characters wide in the feed's four columns. A narrow row is the date and
  the headline, with the qualifier and the tag on a line under them; from about 35rem it
  is the feed's columns. This is a container query on the panel's body.
- **A panel is a section, not a card.** A rule and a caps label from the house's own
  `section`, with the company in the basis tag. The design system has no cards.
- **A private panel is never named to the model**, whatever `CHAT_ALLOW_PORTFOLIO` says.
  The plan had the switch let it through. The switch offers a tool the model has to ask
  for; naming a holdings panel beside a ticker would tell it unasked. So `desk_chat`'s
  list holds no private panel at all, and a test holds that list to the frontend's.
- **What is on screen is read when the question is sent**, from the session, not passed
  when the box is drawn. The board and the box are separate fragments, and a value
  passed at draw time would be the board as it stood at the last full run of the page.
- **The Ask box's slot goes after the part of each key the stylesheet matches**
  (`ask_box_td_LLY`, not `td_ask_box_LLY`), so the second box takes the same styles with
  no change to `theme.py`.
- **The registry lists only what is built.** The picker offers what works; the table
  above is the plan for the rest.
- **The board's held reads are cleared through `api_get.clear`**, the call every handler
  that changes the book already makes. It did nothing since the page stopped caching;
  now it drops the board's minute of reads.

Not checked yet:

- The whole suite (`make verify`). Another session's suite was running, and one heavy
  thing runs at a time. The eight test files this work touches pass: 129 tests.
- A question asked end to end against a model with the board's sentence in the prompt.
  The copy's page was run against the API of the real checkout, which does not have the
  new field and ignores it. `test_desk_chat.py` pins the prompt and `test_ask_route.py`
  the route.
