# Strategy lab: plan

Drafted 2026-11-17. Not built. This is the plan to agree before any code.

## What it is for

The book values every asset on its own evidence and adds them up by owner. A deal moves
assets from one owner to another, so most of a deal's arithmetic is already in the book:
the target's cash flows, the buyer's discount rate, both balance sheets, the buyer's
exclusivity cliffs. The lab puts a buyer and a target side by side and answers four
questions a deal team asks first:

1. What is the target worth to this buyer, and what is the most it can pay?
2. What does the buyer look like afterwards: revenue, value a share, debt?
3. How wrong can the assumptions be before the deal stops paying?
4. Who else would want it, and what could they pay?

It is a view beside the valuation, as the development cost and the cash profile are.
Nothing on the value path imports it, and a test holds that.

## What exists to build on

| Need | Already in the book |
|---|---|
| The target's cash flows by asset and year | `forecast_view.company_verdict`: each modelled asset's `pnl_share`, `years`, `wacc`, `pos`, `rnpv_share`, `loe_year` |
| The buyer's discount rate, cash, debt, shares, price | the same verdict's `sotp` block: `cost_of_equity`, `cash`, `net_cash`, `enterprise`, `equity_per_share`, `diluted_shares`, `close` |
| The buyer's revenue path and its cliffs | `sotp.revenue_path`, each asset's `loe_year` and regional dates |
| What acquirers have paid | `data/precedent_transactions.csv`: 70 or so deals since 2015 with filed premium, enterprise value and trailing revenue, each quoted with its accession |
| Return and payback on dated flows | `cash_profile.irr` and its cumulative curve (built 2026-11-17) |
| The value at which an assumption breaks the answer | `breakpoints.py`, which solves one lever at a time against a price |
| Moving levers without saving | `forecast_view.whatif`: volume, net price, PoS, WACC |
| Therapy area per product | `product_areas.area_for` |
| Partial ownership | `economics_share` on each asset; upfront and milestone terms in `deal_terms.py` |
| Charts | `components/charts.py`: line, waterfall, tornado, heat map, football field |

What does not exist: any deal arithmetic, a pro forma, a bidder screen, IRR at a price.

## Version 1: one buyer, one target

### Inputs the reader sets

- **Buyer**: any company in the universe.
- **Target**: a company in the universe, or one asset of a company, or a share of one asset.
- **Price**: a price a share, or a premium to the last close. It opens on the median filed
  premium in the precedents file, labelled as that, with the quartiles shown beside it.
- **How it is paid**: cash on hand first, then debt, then new shares, as shares of the price.
- **Costs**: the target's own cost ratios (the default, which assumes no savings) or the
  buyer's. Restating at the buyer's ratios is the only synergy the lab states, and it is a
  switch, not a number someone typed.

### What it computes

All in the buyer's reporting currency, at the buyer's share where an asset is shared.

- **Value to the buyer.** The target's modelled cash flows, asset by asset, rediscounted at
  the buyer's rate and weighted by each asset's probability, plus the target's net cash.
- **Value created.** Value to the buyer less the price paid. Per buyer share: for cash and
  debt, value created over the buyer's shares; for stock, the combined equity over the
  enlarged share count less today's value a share.
- **Breakeven price.** The price at which value created is nil: the most this buyer can pay
  on the model. Stated a target share and as a premium to the close.
- **Room.** Breakeven less the precedent median bid. Negative room says the model does not
  support a bid at the going rate.
- **Return.** The internal rate of return on the price against the target's risk-weighted
  cash flows, and the year the price is earned back.
- **Pro forma.** Combined revenue by year against the buyer alone, with the buyer's
  exclusivity losses marked: the share of the revenue the buyer loses in the next five
  years that the target replaces. Net debt before and after, against combined cash flow.

### What it shows

One page, controls down the left.

- Four figures across the top: value created a share, breakeven price, room against
  precedent, return.
- A bridge (waterfall): buyer today, plus target at the buyer's rate, less price, less
  financing cost, to buyer after.
- Pro forma revenue: buyer alone, target, combined, cliffs marked.
- The deal's cash profile: price out, cash back, cumulative.
- The target's assets as rows: value to the seller, value to the buyer, the difference.

### What it refuses

- A target whose modelled revenue covers too little of what it reports (the verdict's
  `coverage`): the lab says the book does not value enough of the company and stops,
  never fills the gap.
- A currency with no rate on file.
- A buyer or target with no close.
- Savings anyone types in. Only the cost-ratio switch.

## Version 2: the stress lab

The same deal with levers on the target (volume, net price, probability, discount rate)
and on the deal (price, financing mix), recomputed without saving.

- A grid of value created across two levers the reader picks.
- Break-points: for each lever, the value at which the deal breaks even, beside the
  model's own. "The deal pays while the lead asset's peak stays above 62% of the model's."
- The same for the breakeven price itself: how far it moves for a fifth either way on
  each lever, as a tornado. This is the notes' "sensitivity of the breakeven".

## Version 3: who should bid

For one target, every company in the universe as the buyer, one row each:

- value to that buyer and its breakeven price;
- the share of that buyer's revenue losses in five years the target replaces;
- whether the buyer sells in the target's therapy areas;
- the price as a share of the buyer's market value, and of its cash;
- room against precedent.

Sortable on any column. No single score by default: a score is a blend of judgements and
the book's rule is that a number traces to a source. If a combined rank is wanted it is
labelled a convention, with its weights printed and editable.

## Version 4: stakes and licences

A share of one asset for an upfront payment and milestones: each milestone paid at the
chance its gate is passed, the buyer taking its share of the asset's cash flows. Uses
`deal_terms.py`'s vocabulary so a filed deal can be replayed.

## How it is checked

- Unit tests on the arithmetic with hand-built companies: a deal at the breakeven price
  creates nil; a stock deal at a fair exchange ratio creates nil; restating at a cheaper
  rate raises the breakeven.
- The value-path test: nothing the valuation imports may import the lab.
- Three replays against filed terms, as worked examples in the doc rather than as tests,
  since their targets have since been folded into their buyers: Vertex and Crinetics
  ($85.00 a share), BioMarin and Amicus, Lilly and Sangamo's ST-506.
- House style and "a null is never a zero" tests on every visible string, as the
  catalysts tab has.

## Order of work

1. `backend/strategy_lab.py`: the deal arithmetic for a whole company, with tests.
2. `GET /strategy/deal`: the payload. Then the tab, version 1.
3. One asset and a share of one asset as the target.
4. The stress lab.
5. Who should bid.
6. Stakes and licences.

Steps 1 and 2 are one session. Each later step is a session of its own.

## Decisions to make before step 1

1. **Savings.** The plan allows one switch, the buyer's cost ratios. Is that enough, or is
   a typed savings figure wanted, shown as the reader's own assumption?
2. **A score.** The notes ask for attractiveness out of 100. The plan shows the components
   and offers a labelled convention. Is a headline score wanted anyway?
3. **Targets outside the universe.** The lab can only price what the book models. Private
   targets would need a manual entry form. In scope, or later?
4. **Where it lives.** A tab on each company (that company as buyer or target), or one
   page at the universe level. The plan assumes the universe level, opened from a
   company with that company filled in.
