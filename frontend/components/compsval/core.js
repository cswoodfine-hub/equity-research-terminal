/**
 * core.js: the pure core of the Comps valuation view.
 *
 * Contract: docs/design/comps-valuation.md, section 3, with the column catalogue of 4.2 and the
 * presets of 4.5 exported as data, as revised by section 12 (revision 3: the simplified page,
 * Drivers and risks fed by the focal context, the bridge-only mode, the whole-cohort peer set).
 * Where section 12 and sections 0 to 11 disagree, section 12 holds.
 * Pure ES module: no DOM, no window, no storage, no Date.now().
 * Callers pass time (`now`) in actions. `null` means absent and is never coerced to 0.
 *
 * Percentile method (3.2): `quantile` sorts a copy of the finite values and interpolates linearly
 * between closest ranks, R type 7 (numpy's default, Excel PERCENTILE.INC):
 * h = (n - 1) p, lo = floor(h), x[lo] + (h - lo)(x[lo + 1] - x[lo]); n = 1 returns the value.
 * `percentileRank` is the mid-rank percent over the peer values, focal excluded:
 * (below + 0.5 equal) / n x 100. It is reported as a number only and never decides a quartile;
 * `quartileSide` compares against the same p25 and p75 the summary rows show.
 *
 * ---------------------------------------------------------------------------------------------
 * View (3.15): what every renderer consumes. Renderers never read the payload directly except
 * `payload.companies[i].detail`, which reaches them as `view.detail.detail`.
 *
 * `deriveView(payload, state, {context, mode})` (12.10). `context` is the focal company's
 * comps-context body (12.2), `{ticker, error}` when the read failed, or null while it is on its way.
 * `mode` is "full" (default) or "bridge". In bridge mode the view carries `mode`, `error`, `focal`,
 * `ctx`, `primary`, `bridge`, `bridgeLine`, the bridge's own `states` and `analysis`; every other
 * section is null (`kpis` and `states` stay arrays).
 *
 * @typedef {Object} View
 * @property {1} schema
 * @property {"full"|"bridge"} mode           12.5
 * @property {StateMsg|null} error            Whole-frame error (schema mismatch, focal missing).
 * @property {{ticker:string,name:string,type:string,preRevenue:boolean,record:Object}} focal
 * @property {{basis:string,basisLabel:string,currency:string,currencyLabel:string,
 *            dataState:"Standardised"|"As reported",earnings:string,earningsLabel:string,
 *            fxText:string,basisText:string,displayCurrency:string}} ctx
 * @property {{ticker:string,name:string,listingText:string,subsectorText:string,stageText:string,
 *            stageChip:Chip,subsectorChip:Chip,typeChip:Chip|null,reportingText:string,
 *            reportingShort:string,peerSet:{full:string,short:string,noun:string,tooltip:string},
 *            basis:{text:string,nonDefault:boolean,tooltip:string},
 *            dataAsOf:{text:string,short:string,tone:"neutral"|"flag",lines:string[]},
 *            live:boolean,liveChip:Chip|null}} header
 *   `basis` (12.6): "Basis", or "Basis: EUR, ex amort." naming each choice that is not the default.
 *   `peerSet.tooltip` (12.8): what the system set is ("Every big pharma company at the commercial
 *   stage. ..."); "" for a saved or edited set.
 * @property {Conclusion} conclusion           3.11
 * @property {Kpi[]} kpis                      exactly 6; kpis[5].link opens the Forecast tab (12.5)
 * @property {{colId:string|null,label:string,basisLabel:string,basis:string|null,state:string,
 *            reasonText:string,fallbackFrom:string|null,
 *            candidates:{colId:string,label:string,enabled:boolean,premium:boolean,
 *                        reason:string|null,n:number}[]}} primary
 * @property {{counts:{n:number,k:number,text:string},
 *            items:{id:string,kind:"exclusion"|"filter"|"group"|"outliers"|"warning",text:string,
 *                   tooltip:string,removable:boolean,priority:number,ticker?:string,
 *                   colId?:string,action?:Object}[]}} scope
 * @property {TableView} table
 * @property {DotplotView} dotplot
 * @property {ScatterView} scatter
 * @property {Bridge} bridge                   3.9
 * @property {{text:string,linkLabel:string,storageLine:string}} bridgeLine   12.5, the context line
 *   of the bridge-only frame: "AZN against Big pharma, commercial, 17: peer median P/E (NTM) of
 *   15.4×, 14 of 17 peers with a value."; "{T} against {set}." while the bridge is disabled
 * @property {{premium:Obs[],discount:Obs[],notAssessed:string[],suppressed:Object[]}} observations
 *   3.10, unchanged: it feeds the banner's support, "Look next" and "Why?"
 * @property {Insight|null} insight            12.3: what the Drivers and risks panel draws
 * @property {{text:string,tone:"neutral"|"flag",buttonLabel:string,anchor:"sources"}} footer   12.6;
 *   the `!` of the flag tone is the renderer's
 * @property {{rows:PeerRow[],candidates:PeerRow[],savedSets:Object[],subgroups:Object[],
 *            cohorts:CohortRow[],cohortOptions:{id:string,label:string}[],
 *            mixed:StateMsg|null,weak:StateMsg|null,setLabel:Object,n:number,k:number,
 *            open:boolean,search:boolean,title:string}} peers
 *   `open` is the peer drawer (12.6); `search` is true when it was opened at its search box
 * @property {{sections:{id:string,title:string,body:string[],items?:Object[]}[]}} method
 * @property {DetailView|null} detail
 * @property {StateMsg[]} states               every state of section 8 that applies
 * @property {Object} lineage
 * @property {{label:string}|null} undo
 * @property {Object<string,StateMsg>} sectionErrors  section id -> red StateMsg; that section is null
 * @property {Object} analysis                 internal: read by conclusion(), confidence() and
 *                                             paletteExtras(); renderers should not rely on it
 *
 * Helpers for renderers beside the View: paletteExtras(view, state) (7.3 generated entries),
 * matchCommands, handleKey, normKey, COMMANDS, KEYMAP, canPin(state, colId, {layout, boxWidth}),
 * toCSV, toTSV, csvFilename, summaryText, flagText, fmt* formatters, COLUMNS, PRESETS, and for
 * revision 3 flagMarks, mergeBridge, indicationTitle, indicationProse, fmtPatients,
 * CONTEXT_NA_TEXT, INSIGHT_COPY and the constants of 12.0.
 *
 * State (12.10): `ui` holds `peers: boolean`, `peersSearch: boolean` and
 * `insightTab: "catalysts"|"competition"`; `ui.lowerTab` is gone and `ui.laptopTab` serves
 * laptop, wide and ultrawide. Actions added: OPEN_PEERS {search?}, CLOSE_PEERS,
 * SET_INSIGHT_TAB {tab}, ADOPT_PERSISTED {local, session}. SET_LOWER_TAB is gone. One right-side
 * surface is open at a time: OPEN_DETAIL, OPEN_PEERS and OPEN_METHOD each close the other two.
 *
 * @typedef {Object} Insight   (12.3)
 * @property {string} ticker
 * @property {"ok"|"pending"|"error"} state   pending: no context yet, or another company's;
 *   error: the context carries `error`, or its schema is not CONTEXT_SCHEMA
 * @property {StateMsg|null} message          the pending or error block
 * @property {string|null} notice             line above both groups while the model is not computed
 * @property {{premium:InsightItem[],discount:InsightItem[],notAssessed:string[],
 *            premiumHeading:string,discountHeading:string,emptyText:string,maxMetric:number}} valuation
 *   a side lists its metric items by strength (the panel shows `maxMetric`, then "Show {n} more"),
 *   then the catalyst item, then the competition items in row order; those always show
 * @property {{state:"ok"|"empty"|"pending"|"error",title:string,countText:string,rows:CatalystRow[],
 *            note:string,empty:StateMsg|null,link:Link,linkLabel:string}} catalysts
 * @property {{state:"ok"|"empty"|"not_covered"|"pending"|"error",title:string,countText:string,
 *            rows:CompetitionRow[],note:string,empty:StateMsg|null,lead:string|null,
 *            link:Link|null,linkLabel:string,columns:string[]}} competition
 *   `empty` is the state block that replaces the rows whenever `state` is not "ok"; `lead` is the
 *   line above the rows when they are ordered by contest; `columns` are the five headings
 *
 * @typedef {{id:string,kind:"metric"|"catalyst"|"competition",side:"premium"|"discount",text:string,
 *   tag:string,strength:number,severity:"info"|"amber"|"red",provenance:"C"|"M",twoSided:boolean,
 *   chips:Chip[],link:Link,linkLabel:string}} InsightItem
 *   ids: a 3.10 rule id, "catalyst_stake", "catalyst_value", "pool_rationed:{indicationId}",
 *   "pool_lead:{indicationId}"
 * @typedef {{kind:"column",colId:string}|{kind:"tab",tab:"Catalysts"|"Forecast"}|
 *   {kind:"indication",indicationId:number,name:string}} Link
 * @typedef {{id:string,assetId:number|null,tier:0|1|2|3|4,dateIso:string,dateShort:string,
 *   dateText:string,estimated:boolean,label:string,indicationText:string|null,
 *   indicationNa:string|null,moreText:string|null,modelText:string|null,
 *   modelKind:"stake"|"asset_value"|null,naText:string|null,side:"discount"|null,chips:Chip[],
 *   link:Link,sourceUrl:string|null,tooltip:string[]}} CatalystRow    id is "cat-{catalyst id}"
 * @typedef {{id:string,indicationId:number,name:string,storedName:string,valueText:string|null,
 *   valueNa:string|null,own:StageCounts,rivals:StageCounts&{companies:number},ownText:string,
 *   rivalsText:string,poolText:string|null,poolNa:string|null,shareText:string|null,
 *   shareNa:string|null,side:"premium"|"discount"|"both"|null,provenance:"M"|"S",link:Link,
 *   tooltip:string[]}} CompetitionRow    id is "ind-{indication id}"
 * @typedef {{n:number,marketed:number,phase3:number,phase2:number,other:number}} StageCounts
 *
 * @typedef {Object} Conclusion
 * @property {"ok"|"low_confidence"|"too_few"|"no_multiple"|"no_peers"|"error"} state
 * @property {string} headline                 at most MAX_HEADLINE_CHARS
 * @property {string} support                  at most two sentences
 * @property {string} supportShort             at most MAX_SUPPORT_SHORT_CHARS
 * @property {{text:string,caption:string,dir:"up"|"down"|null}} token   always text colour
 * @property {string} label
 * @property {string} labelShort
 * @property {{level:"high"|"medium"|"low"|null,score:number|null,reasons:string[],
 *            points:{text:string,points:number}[]}} confidence
 * @property {"active"|"flag"|"down"} bar
 * @property {Chip[]} chips
 * @property {{text:string,target:{kind:"cell"|"dotplot"|"scatter"|"peers",colId:string|null,
 *            ticker:string|null}}} lookNext
 * @property {{groups:{title:string,items:{text:string,colId:string|null,provenance:string}[]}[]}} why
 * @property {string|null} metric   prose label, e.g. "P/E"
 * @property {number|null} value  @property {number|null} median  @property {number|null} premium
 * @property {number|null} pct    @property {number} n
 * @property {string[]} notes      banner support notes, e.g. missing estimates
 * @property {{label:string,command:string}|null} action
 *
 * @typedef {{id:string,label:string,value:string,v:number|null,valueDir:"up"|"down"|null,
 *   unit:string|null,period:string,provenance:"sourced"|"calc."|"model",compare:string,
 *   compareDir:"up"|"down"|null,tooltip:string,flag:"amber"|null,strip:PositionStrip|null,
 *   link:Link|null}} Kpi
 *   `period` ends with the provenance word; `compare` already carries its arrow glyph.
 *
 * @typedef {{domain:[number,number],p25:number|null,median:number|null,p75:number|null,
 *   focal:number|null,clamped:"lo"|"hi"|null,description:string}} PositionStrip
 *
 * @typedef {Object} TableView
 * @property {ColView[]} columns   starts with the five frozen base columns exp, incl, rel,
 *   company, ticker (frozen: true), then manual pins (frozen: true), then the primary column when
 *   the preset lacks it (autoPinned: true, frozen: false), then the preset's columns. The primary
 *   column always carries autoPinned: true; table.js freezes it after the ticker at laptop and
 *   narrow widths only.
 * @property {{id:string,label:string,span:number}[]} groups   consecutive runs over `columns`
 * @property {RowView[]} rows      focal first, then peer rows in view order (filters applied)
 * @property {{id:"mean"|"median"|"p25"|"p75"|"n",label:string,
 *            cells:Object<string,SummaryCell>}[]} summary
 * @property {string[]} summaryVisible  all five when summary rows are on, else ["n"]; at laptop
 *   and narrow the table shows median and n unless state.summaryExpanded[layout]
 * @property {{colId:string,dir:"asc"|"desc"}|null} sort
 * @property {string} cfMode  @property {string} density  @property {number} textSize
 * @property {string} preset  @property {number} hiddenCount  @property {string[]} hidden
 * @property {number} frozenWidth  base block plus pins at wide (332 + pins)
 * @property {string} caption
 * @property {number} filteredOut  peer rows hidden by filters
 * @property {StateMsg|null} empty   no peers, or filters hide every row
 * @property {{id:string,label:string}[]} presets
 * @property {{count:number,lines:string[],label:string}} viewBadge   12.7: the "View" button reads
 *   `label` ("View", or "View · {count}"); `lines` name each setting away from its default
 *
 * @typedef {{id:string,group:string,label:string,unitText:string,
 *   basisChip:{text:string,mixed:boolean,tooltip:string|null}|null,provenance:"S"|"C"|"M",
 *   provenanceWord:"sourced"|"calc."|"model",tooltip:string,width:number,frozen:boolean,
 *   autoPinned:boolean,align:"left"|"right",sortDir:"asc"|"desc"|null,filter:Object|null,
 *   fmt:string,dir:"+"|"-"|"n",numeric:boolean,isPrimary:boolean,unitLine:string}} ColView
 *
 * @typedef {{ticker:string,name:string,isFocal:boolean,excluded:boolean,expanded:boolean,
 *   outlier:null|"mild"|"extreme",source:"system"|"analyst"|"saved"|null,pool:"A"|"B"|"C"|null,
 *   reason:string|null,relevance:{score:number,level:string,components:Object,
 *   missing:{id:string,reason:string}[]}|null,note:string,
 *   cells:Object<string,Cell&{pct:number|null,vsMedian:number|null,cf:Object|null}>,
 *   error:string|null,tickerFlags:string[],tickerLines:string[]}} RowView
 *   `tickerFlags` (12.7): the `!` after a ticker shows only when it is not empty. Focal row: the
 *   flags that cost the confidence point; peer row: derived operating income on its primary cell
 *   while the derived-share penalty is in force; any row: a failed VIEW_SOURCES source and a
 *   failed calculation. `cells.ticker` carries the same codes in `marks`. Every other flag of the
 *   company is in `DetailView.flags`.
 *
 * @typedef {{v:number|null,text:string,n:number,lowN:boolean,reason:string|null}} SummaryCell
 * @typedef {{id:string,severity:"info"|"amber"|"red",where:string[],title:string,detail:string,
 *   action:{label:string,command:string}|null}} StateMsg
 * @typedef {{id:string,text:string,tone:"neutral"|"active"|"flag"|"down"|"up"|"clinical",
 *   tooltip:string}} Chip
 *
 * @typedef {{v:number|null,status:"ok"|"na"|"nm"|"nb"|"err",text:string,reason:string|null,
 *   tag:"A"|"E"|"G"|"M"|null,period:string|null,tagDiffers:boolean,unit:string|null,
 *   flags:string[],marks:string[],ticker:string|null,brief:string|null,flagLines:string[],
 *   amber:boolean,red:boolean,tone?:string,series?:number[]|null,periodKey:string|null}} Cell
 *   `flags` are the codes that touch the cell (`flagTouches`): the logic reads them. `marks` are
 *   the codes that bear on the printed value (`flagMarks`, 12.7): `amber`, `red` and `flagLines`
 *   follow `marks` alone, so a marker and its tooltip show only there.
 *
 * @typedef {Object} DotplotView
 * @property {string|null} colId  @property {string} label  @property {string} unit
 * @property {boolean} isPrimary  @property {boolean} premiumEligible
 * @property {"linear"|"log"} scale
 * @property {[number,number]|null} domain   padded 8 % (in log space for log scale)
 * @property {[number,number]|null} extent   min to max of plotted values, extremes left out
 * @property {{id:string,label:string,n:number,median:number|null,p25:number|null,
 *            p75:number|null,points:DotPoint[]}[]} lanes
 * @property {{nm:number,na:number}} notPlotted
 * @property {{lo:number,hi:number}|null} target  analyst target range
 * @property {string} description  @property {string|null} disabledReason
 * @property {string} subtitle     e.g. the low-confidence note
 * @property {StateMsg|null} disabledState   the .u-state block to show instead of the plot
 * @property {string|null} tag  "Primary", "Position only" or null  @property {boolean} useAsPrimary
 * @property {string} notPlottedText  "Not plotted: {k} not meaningful, {j} with no value" or ""
 * @typedef {{ticker:string,v:number,x:number,text:string,isFocal:boolean,excluded:boolean,
 *   outlier:null|"mild"|"extreme",clamped:"lo"|"hi"|null,label:string|null,pct:number|null,
 *   hover:string,announce:string}} DotPoint   x is v clamped to the extent; label set when clamped
 *
 * @typedef {Object} ScatterView  (3.8 scatterModel output plus the controls)
 * @property {Object[]} points  {ticker,x,y,px,py,r,size,isFocal,excluded,inStats,engine,stage,shape,
 *   hollow,clampedX,clampedY,showLabel,xText,yText,announce}; px/py clamped to the extent, r in px
 * @property {{slope:number,intercept:number,r2:number,n:number}|null} trend
 * @property {"trend"|"median"|null} reference @property {number|null} rel
 * @property {{id:string,label:string}|null} region
 * @property {string} interpretation  @property {string} description
 * @property {{x:[number,number],y:[number,number]}|null} domain
 * @property {string|null} disabledReason
 * @property {string} x @property {string} y @property {string} size @property {string} colorBy
 * @property {boolean} logY @property {boolean} trendOn @property {boolean} logYOffered
 * @property {{id:string,label:string,x:number,y:number}[]} regions  data coordinates
 * @property {number|null} medianX @property {number|null} medianY
 * @property {{id:string,label:string}[]} xOptions @property {{id:string,label:string}[]} yOptions
 * @property {StateMsg|null} disabledState  the .u-state block to show instead of the chart
 *
 * @typedef {Object} DetailView
 * @property {string} ticker @property {string} name @property {boolean} isFocal
 * @property {Object} record @property {Object|null} detail   (2.7 detail record, verbatim)
 * @property {boolean} inPeers @property {boolean} excluded @property {Object|null} relevance
 * @property {string|null} source @property {string|null} reason
 * @property {{id:string,label:string,peer:string,focal:string,better:"peer"|"focal"|null}[]} against
 * @property {Object} overTime  {labels, series: {revenue_growth: {peer, focal}, net_margin: {...}}}
 * @property {{text:string,updated:string}|null} note
 * @property {Chip[]} chips
 * @property {{code:string,severity:"info"|"amber"|"red",text:string,cells:string[]}[]} flags
 *   12.7 "Data flags": every flag of the company, red first, with the column labels it marks
 */

// ---------------------------------------------------------------------------------------------
// 3.1 Constants
// ---------------------------------------------------------------------------------------------

export const SCHEMA = 1;
export const STORAGE_KEY = "er.compsval.v1";          // localStorage
export const SESSION_KEY = "er.compsval.session.v1";  // sessionStorage
export const BASES = ["NTM", "FY1", "FY2", "FY0", "LTM"];
export const CURRENCIES = ["USD", "EUR", "GBP", "CHF", "DKK", "REPORTED"];
export const MIN_PEERS = 5;                 // fewer valid values: low confidence
export const MAX_DEFAULT_PEERS = 15;
export const MIN_DEFAULT_RELEVANCE = 40;    // also the floor for an "appropriate" peer
export const MIN_MEDIAN_RELEVANCE = 50;     // confidence penalty under this
export const MIN_REVENUE_USD_M = 100;       // revenue multiples, margins and R&D share below this are n.m.
export const MIN_GROWTH_BASE_USD_M = 10;    // revenue growth and CAGR n.m. when either end is below this
export const MIN_EBITDA_GROWTH_BASE_USD_M = 10;  // EBITDA growth n.m. when abs(base) is below this
export const MIN_EPS_GROWTH_BASE = 0.10;    // EPS growth and CAGR n.m. when abs(base EPS) is below this
export const MAX_ABS_GROWTH = 5.0;          // abs(growth) over 500 % is n.m., every growth column
export const MAX_REVENUE_MULTIPLE = 100;    // EV/Revenue and market cap / revenue over 100x are n.m.
export const MIN_MARGIN = -1.0;             // margins below -100 % are n.m.
export const MIN_EPS_FOR_DISPERSION = 0.10; // abs(mean EPS) below USD 0.10: dispersion n.m.
export const IN_LINE_PCT = 5;               // in line when the premium rounds to under 5 whole percent
export const NEAR_TREND_BAND = 0.10;        // abs(relative residual) under 10 %: near trend
export const MIN_SCATTER_PEERS = 3;         // fewer peers with both values: no scatter
export const TUKEY_K = 1.5, TUKEY_EXTREME_K = 3.0;
export const MAX_DISPERSION_RATIO = 0.6;    // iqr / median above this costs a confidence point
export const MAX_DERIVED_SHARE = 0.25;      // share of peer values on derived operating income
export const WIDE_RANGE_MIN_ESTIMATES = 5;  // estimate_range_wide counts for confidence under this n
export const WIDE_RANGE_MAX = 1.0;          // ... or above this dispersion
export const MAX_HEADLINE_CHARS = 160, MAX_SUPPORT_SHORT_CHARS = 90, MAX_LOOK_NEXT_CHARS = 60;
export const SHORT_FRAME_PX = 720, COLLAPSE_AT_PX = 120, EXPAND_BELOW_PX = 40;
export const FROZEN_MAX_SHARE = 0.40;       // frozen columns may cover at most this share of the table box
export const UNDO_MS = 5000;
export const RELEVANCE_WEIGHTS = {subsector: 0.25, model: 0.20, scale: 0.20,
                                  profitability: 0.15, growth: 0.15, geography: 0.05};
// Metrics a premium or discount can be stated on. Every other metric shows a position only.
export const PREMIUM_METRICS = ["pe", "ev_ebitda", "ev_revenue", "price_to_sales",
                                "price_to_book", "fcf_yield", "peg", "mcap_to_cash"];
export const BRIDGEABLE = ["pe", "ev_revenue", "ev_ebitda", "price_to_sales",
                           "price_to_book", "fcf_yield", "mcap_to_cash"];
export const BANNED_WORDS = ["additionally", "highlight", "underscore", "pivotal", "showcase", "testament"];
export const VIEW_SOURCES = ["prices", "consensus_nasdaq", "financials", "fx"];
// The dot plot switcher, in order (3.5).
export const METRIC_CANDIDATES = ["pe", "ev_ebitda", "ev_revenue", "price_to_sales", "price_to_book",
  "fcf_yield", "peg", "mcap_to_cash", "market_cap", "ev", "cash_to_mcap", "runway_months",
  "pt_upside", "ev_per_late_trial", "pipeline_to_ev"];
export const NULL_GLYPH = "—";

// Revision 3 (section 12.0).
export const CATALYST_MIN_PCT = 0.05;        // stake, or an unapproved asset's modelled value, as a share of price
export const POOL_KEEP_MAX = 0.90;           // a company keeping at most this share of its own forecasts is rationed
export const POOL_LEAD_MIN_SHARE = 0.25;     // largest share of the modelled starts, and at least this
export const POOL_LEAD_MIN_COMPANIES = 3;
export const COMPETITION_MIN_PCT = 0.02;     // the company's modelled value in the indication, share of price
export const INSIGHT_ROWS = 5;               // rows an evidence group shows before "Show {n} more"; also the metric items a side shows
export const WHOLE_COHORT_MAX = 20;          // R3.7: a cohort of this many other companies or fewer is the default set, whole
export const MAX_PRESET_COLUMNS = 9;         // R3.6: columns a built-in preset holds after the frozen block
export const REGULATORY_KINDS = ["PDUFA", "regulatory decision", "AdCom", "EMA decision"];
export const LATE_PHASES = ["Phase 3", "Phase 2/3"];
export const CONTEXT_SCHEMA = 1;
export const GOTO_KEY = "er.compsval.goto";  // sessionStorage, 12.5
export const MODES = ["full", "bridge"];

const NULL = NULL_GLYPH;
const MINUS = "−";
const TIMES = "×";
const UP_GLYPH = "▲";
const DOWN_GLYPH = "▼";
const ELLIPSIS = "…";
const MID = " · ";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];
const DEFAULT_ENGINE_LABELS = {pharma: "Big pharma", biotech: "Biotech", cellgene: "Cell and gene"};

/**
 * `usesFiledFigures(colId, basis)`: true when the column rests on filed statements, so a mix of
 * IFRS and US GAAP filers costs a confidence point (3.1, 3.11).
 */
export function usesFiledFigures(colId, basis) {
  if (colId === "pe") return basis === "FY0" || basis === "LTM";
  return ["ev_ebitda", "price_to_book", "fcf_yield", "gross_margin", "ebitda_margin",
    "operating_margin", "net_margin", "roic", "rd_pct"].includes(colId);
}

// ---------------------------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------------------------

function isNum(v) { return typeof v === "number" && Number.isFinite(v); }
function get(obj, path) {
  if (obj == null) return undefined;
  let cur = obj;
  for (const k of String(path).split(".")) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = cur[k];
  }
  return cur;
}
function numAt(obj, path) { const v = get(obj, path); return isNum(v) ? v : null; }
function ucfirst(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
function lcfirst(s) {
  if (!s) return s;
  // Keep acronyms and tickers as they are: "EV/EBITDA", "P/E NTM", "NTM EPS", "AZN".
  if (/^[A-Z0-9&]{2,}(\b|\/)/.test(s) || /^[A-Z]\//.test(s)) return s;
  return s.charAt(0).toLowerCase() + s.slice(1);
}
function stripStop(s) { return s ? String(s).replace(/\.\s*$/, "") : s; }
function fill(tpl, params) {
  return String(tpl).replace(/\{(\w+)\}/g, (m, k) => (params && params[k] != null ? String(params[k]) : m));
}
function uniq(arr) { return Array.from(new Set(arr)); }
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function plural(n, one, many) { return n === 1 ? one : many; }
/** "a" or "an" before a whole number read aloud: an 8, an 11, an 18, an 80. */
function article(n) {
  const s = String(Math.round(Math.abs(n)));
  return s.startsWith("8") || s === "11" || s === "18" || /^1[18]\d{3}$/.test(s) ? "an" : "a";
}
function wholePct(p) { return Math.round(Math.abs(p) * 100 + 1e-9); }
function signedWholePct(p) {
  const w = wholePct(p);
  if (w === 0) return "0%";
  return (p > 0 ? "+" : MINUS) + w + "%";
}
function cutAt(s, max) {
  if (!s || s.length <= max) return s;
  const cut = s.slice(0, max - 1);
  const sp = cut.lastIndexOf(" ");
  return (sp > max * 0.5 ? cut.slice(0, sp) : cut).replace(/[,;:\s]+$/, "") + ELLIPSIS;
}
function shallowEqualArr(a, b) {
  if (a === b) return true;
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

// ---------------------------------------------------------------------------------------------
// 3.2 Statistics
// ---------------------------------------------------------------------------------------------

export function finite(values) {
  return (values || []).filter((v) => typeof v === "number" && Number.isFinite(v));
}

export function quantile(values, p) {
  const x = finite(values).slice().sort((a, b) => a - b);
  const n = x.length;
  if (n === 0) return null;
  if (n === 1) return x[0];
  const h = (n - 1) * p;
  const lo = Math.floor(h);
  if (lo >= n - 1) return x[n - 1];
  if (lo < 0) return x[0];
  return x[lo] + (h - lo) * (x[lo + 1] - x[lo]);
}

export function median(values) { return quantile(values, 0.5); }

export function mean(values) {
  const x = finite(values);
  if (!x.length) return null;
  return x.reduce((s, v) => s + v, 0) / x.length;
}

export function summarize(values) {
  const x = finite(values);
  if (!x.length) return null;
  const p25 = quantile(x, 0.25), p75 = quantile(x, 0.75);
  return {n: x.length, mean: mean(x), median: quantile(x, 0.5), p25, p75, iqr: p75 - p25,
          min: Math.min(...x), max: Math.max(...x)};
}

export function percentileRank(value, values) {
  if (!isNum(value)) return null;
  const x = finite(values);
  if (!x.length) return null;
  let below = 0, equal = 0;
  for (const v of x) { if (v < value) below++; else if (v === value) equal++; }
  return (below + 0.5 * equal) / x.length * 100;
}

export function quartileSide(value, values) {
  if (!isNum(value)) return null;
  const x = finite(values);
  if (x.length < MIN_PEERS) return null;
  if (value >= quantile(x, 0.75)) return "top";
  if (value <= quantile(x, 0.25)) return "bottom";
  return null;
}

export function premium(value, reference, direction) {
  if (!direction || !isNum(value) || !isNum(reference)) return null;
  if (value <= 0 || reference <= 0) return null;
  if (direction === "richer_up") return value / reference - 1;
  if (direction === "richer_down") return reference / value - 1;
  return null;
}

export function isInLine(p) {
  if (!isNum(p)) return false;
  return Math.round(Math.abs(p) * 100 + 1e-9) < IN_LINE_PCT;
}

export function fences(values, k = TUKEY_K) {
  const x = finite(values);
  if (x.length < 5) return null;
  const p25 = quantile(x, 0.25), p75 = quantile(x, 0.75), iqr = p75 - p25;
  return {lo: p25 - k * iqr, hi: p75 + k * iqr};
}

export function outlierClass(value, values) {
  if (!isNum(value)) return null;
  const f3 = fences(values, TUKEY_EXTREME_K), f1 = fences(values, TUKEY_K);
  if (!f3 || !f1) return null;
  if (value < f3.lo || value > f3.hi) return "extreme";
  if (value < f1.lo || value > f1.hi) return "mild";
  return null;
}

export function ols(points) {
  const pts = (points || []).map((p) => (Array.isArray(p) ? {x: p[0], y: p[1]} : p))
    .filter((p) => p && isNum(p.x) && isNum(p.y));
  const n = pts.length;
  if (n < 5) return null;
  const mx = pts.reduce((s, p) => s + p.x, 0) / n;
  const my = pts.reduce((s, p) => s + p.y, 0) / n;
  let sxx = 0, sxy = 0, syy = 0;
  for (const p of pts) { sxx += (p.x - mx) ** 2; sxy += (p.x - mx) * (p.y - my); syy += (p.y - my) ** 2; }
  if (sxx === 0) return null;
  const slope = sxy / sxx, intercept = my - slope * mx;
  let ssres = 0;
  for (const p of pts) ssres += (p.y - (intercept + slope * p.x)) ** 2;
  const r2 = syy === 0 ? 0 : 1 - ssres / syy;
  return {slope, intercept, r2, n};
}

// ---------------------------------------------------------------------------------------------
// 3.13 Formatting
// ---------------------------------------------------------------------------------------------

export function fmtNumber(v, decimals = 0, opts = {}) {
  if (!isNum(v)) return NULL;
  const d = Math.max(0, Math.min(10, decimals | 0));
  const abs = Math.abs(v).toFixed(d);
  const isZero = Number(abs) === 0;
  const [ip, fp] = abs.split(".");
  const withSep = ip.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const body = fp !== undefined ? withSep + "." + fp : withSep;
  let sign = "";
  if (v < 0 && !isZero) sign = MINUS;
  else if (opts && opts.signed && v > 0 && !isZero) sign = "+";
  return sign + body;
}

export function fmtMultipleProse(v) { return isNum(v) ? fmtNumber(v, 1) + TIMES : NULL; }
export function fmtPctProse(v, d = 1) { return isNum(v) ? fmtNumber(v * 100, d) + "%" : NULL; }

/** `fmtMoneyProse(usdM, cur, fx)`: "$260.0bn", "$5.2bn", "$950m" under 1bn; "EUR 228.5bn". */
export function fmtMoneyProse(usdM, cur = "USD", fx = null) {
  if (!isNum(usdM)) return NULL;
  const code = cur || "USD";
  let rate = 1;
  if (code !== "USD") {
    rate = fx && fx.usd_per_unit ? fx.usd_per_unit[code] : null;
    if (!isNum(rate) || rate <= 0) return NULL;
  }
  const v = usdM / rate;
  const abs = Math.abs(v);
  const sign = v < 0 && abs >= 0.5 ? MINUS : "";
  const prefix = code === "USD" ? "$" : code + " ";
  if (abs >= 999.95) return sign + prefix + fmtNumber(abs / 1000, 1) + "bn";
  return sign + prefix + fmtNumber(abs, 0) + "m";
}

function parseIsoDate(iso) {
  if (!iso || typeof iso !== "string") return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return null;
  return {y: Number(m[1]), m: Number(m[2]), d: Number(m[3])};
}
export function fmtDate(iso) {
  const p = parseIsoDate(iso);
  if (!p) return NULL;
  return `${p.d} ${MONTHS[p.m - 1]} ${p.y}`;
}
export function fmtDateShort(iso) {
  const p = parseIsoDate(iso);
  if (!p) return NULL;
  return `${p.d} ${MONTHS[p.m - 1]}`;
}
export function fmtTime(ts) {
  if (!ts || typeof ts !== "string") return NULL;
  const m = /T(\d{2}):(\d{2})/.exec(ts);
  return m ? `${m[1]}:${m[2]}` : NULL;
}
function isoToCompact(iso) {
  const p = parseIsoDate(iso);
  if (!p) return "";
  return `${p.y}${String(p.m).padStart(2, "0")}${String(p.d).padStart(2, "0")}`;
}
function daysBetween(a, b) {
  const pa = parseIsoDate(a), pb = parseIsoDate(b);
  if (!pa || !pb) return null;
  return Math.round((Date.UTC(pb.y, pb.m - 1, pb.d) - Date.UTC(pa.y, pa.m - 1, pa.d)) / 86400000);
}

export function ordinal(n) {
  if (!isNum(n)) return NULL;
  const k = Math.round(n);
  const t = Math.abs(k) % 100;
  if (t >= 11 && t <= 13) return k + "th";
  switch (Math.abs(k) % 10) {
    case 1: return k + "st";
    case 2: return k + "nd";
    case 3: return k + "rd";
    default: return k + "th";
  }
}

const STATUS_RANK = {ok: 0, nm: 1, nb: 2, na: 3, err: 4};
/**
 * `compareCells(a, b, dir)`: ok values by v (or text for text cells), then nm, nb, na, err,
 * always last whatever `dir`; ties by ticker (cells carry `ticker`).
 */
export function compareCells(a, b, dir = "desc") {
  const ra = STATUS_RANK[a && a.status] ?? 3, rb = STATUS_RANK[b && b.status] ?? 3;
  if (ra !== rb) return ra - rb;
  const sgn = dir === "asc" ? 1 : -1;
  if (ra === 0) {
    if (isNum(a.v) && isNum(b.v)) {
      if (a.v !== b.v) return sgn * (a.v - b.v);
    } else if (!isNum(a.v) && !isNum(b.v)) {
      const c = String(a.text || "").localeCompare(String(b.text || ""));
      if (c !== 0) return sgn * c;
    } else {
      return isNum(a.v) ? -1 : 1;
    }
  }
  return String((a && a.ticker) || "").localeCompare(String((b && b.ticker) || ""));
}

// ---------------------------------------------------------------------------------------------
// 3.12 Copy tables
// ---------------------------------------------------------------------------------------------

export const NA_TEXT = {
  no_free_data: "No free data source carries this.",
  not_filed: "Not in the filings on file.",
  not_tagged: "The filer does not tag this line.",
  no_debt_line: "No debt line filed within a year and no stated nil, so enterprise value is not computed.",
  no_shares: "No share count on file.",
  share_count_scale: "The weighted diluted share count on file is out of scale with the cover count (it looks filed in thousands), so it is not used.",
  no_consensus: "No consensus estimates on file.",
  no_consensus_otc: "No consensus on the free feed for this OTC listing.",
  no_fy2_consensus: "No FY2 consensus, so a twelve-month forward figure is not built.",
  no_ltm_20f: "No LTM figure: 20-F filers' 6-K interims carry no XBRL, and workbook filers publish no interims here.",
  no_ltm: "No interim filing after the fiscal year end.",
  no_guidance: "No numeric guidance for this year.",
  guidance_in_words: "Guidance is stated in words, not a number.",
  guidance_product_scope: "Guidance covers product revenue only, not total revenue.",
  guidance_cer: "Guidance is at constant currency, so it is not set against reported revenue.",
  non_positive_base: "The base is zero or negative, so growth is not meaningful.",
  one_year_only: "Only one fiscal year on file, so no growth.",
  no_tax_rate: "Pre-tax income is zero, negative or not filed, so there is no tax rate and no ROIC.",
  not_modelled: "No forecast model for this company.",
  model_not_computed: "Model values are still being computed. Reload in a minute.",
  model_failed: "The model could not value this company.",
  no_prices: "No price history on file.",
  insufficient_history: "Not enough price history.",
  not_burning: "Not burning cash on trailing operating cash flow.",
  no_cash_flow: "No operating cash flow on file, so burn and runway are not computed.",
  no_cash: "No cash or investments on file.",
  no_product_revenue: "No product revenue on file.",
  no_trials: "No mapped trials.",
  no_rate: "No ECB rate for this currency.",
  none_on_file: "No claims outside cash and debt on file.",
  standard_not_recorded: "The accounting standard is not recorded for this 20-F filer yet. It fills on the next financials refresh.",
  domicile_unknown: "This 20-F filer is stored with a US country code, so its region is not known.",
  calc_failed: "Calculation failed for this company.",
};
const NO_SOURCE_TEXT = "No free data for this measure.";
const CALC_FAILED_CELL = "Calculation failed for this company.";

export const FLAG_SEVERITY = {
  stale_price: "amber", stale_consensus: "amber", stale_balance_sheet: "amber",
  stale_fiscal_year: "amber", source_failed: "amber", fx_converted: "info",
  currency_mismatch: "amber", fiscal_year_end: "amber", ifrs_filer: "info", non_sec_filer: "info",
  includes_minorities: "amber", market_cap_diluted_route: "info", stale_shares: "amber",
  cover_count_exception: "info", market_cap_disagreement: "amber",
  derived_operating_income: "amber", no_consensus: "amber", thin_estimates: "amber",
  estimate_range_wide: "amber", eps_sign_change: "amber", guidance_fx_unstated: "amber",
  burn_flattered: "amber", calc_failed: "red",
  // client flags (3.4)
  no_tagged_addbacks: "info", derived_no_addback: "amber",
};

const DERIVED_NO_ADDBACK_TEXT = "Operating income here is derived from revenue less cost of sales, R&D and SG&A, which already leaves out separately presented amortisation and IPR&D, so nothing is added back.";
const NO_ADDBACKS_TEXT = "No tagged amortisation or IPR&D, so the figure equals GAAP/IFRS.";

function fyYear(rec) {
  const lbl = get(rec, "periods.FY0.label");
  const m = /FY(\d{4})/.exec(lbl || "");
  return m ? m[1] : "";
}
function fmtEps(v) { return isNum(v) ? fmtNumber(v, 2) : NULL; }

/**
 * `flagText(flag, record?)` -> {chip, text} for every code of 2.5 and the client flags of 3.4.
 * `flag` is `{code, params}` or a bare code string. `record` fills fiscal-year words when given.
 */
export function flagText(flag, rec = null) {
  const f = typeof flag === "string" ? {code: flag, params: {}} : (flag || {});
  const p = f.params || {};
  const yr = fyYear(rec);
  const fyWord = yr ? `FY${yr}` : "FY";
  switch (f.code) {
    case "stale_price":
      return {chip: "Stale price", text: oneDay(`Price is from ${fmtDate(p.as_of)}, ${p.trading_days ?? p.days ?? "some"} trading days old.`)};
    case "stale_consensus":
      return {chip: "Stale consensus", text: `Consensus last checked ${fmtDate(p.checked_at)}, ${p.days} days ago.`};
    case "stale_balance_sheet":
      return {chip: "Stale balance sheet", text: `Balance sheet from ${fmtDate(p.as_of)}, ${p.days} days old. Enterprise value uses it as filed.`};
    case "stale_fiscal_year":
      return {chip: "Stale fiscal year", text: `Latest filed fiscal year is ${p.label || fyWord}, more than 15 months old.`};
    case "source_failed":
      return {chip: "Failed source", text: `${p.run_id != null ? `Refresh run ${p.run_id}` : "The latest refresh run"}: ${p.source || "a source"} failed for this company. Its figures are from the previous successful fetch.`};
    case "fx_converted":
      return {chip: "Converted", text: `Converted from ${p.from} at the ECB reference rate of ${fmtDate(p.as_of)}: 1 ${p.from} = ${isNum(p.rate) ? fmtNumber(p.rate, 4) : p.rate} USD.`};
    case "currency_mismatch": {
      const units = Array.isArray(p.row_units) ? p.row_units.join(" and ") : (p.row_units || "another unit");
      return {chip: "Currency mismatch", text: `Filed figures are in ${units} while the company record says ${p.company_currency}. Figures use the unit on each filed row.`};
    }
    case "fiscal_year_end": {
      const mn = isNum(p.month) ? MONTH_NAMES[p.month - 1] : (p.month || "another month");
      return {chip: "Non-December year end", text: `Fiscal year ends in ${mn}. Fiscal years are not calendarised, so FY figures cover a different twelve months from December filers.`};
    }
    case "ifrs_filer":
      return {chip: "IFRS filer", text: "Reports under IFRS. Filed figures are not reconciled to US GAAP."};
    case "non_sec_filer":
      return {chip: "Non-SEC filer", text: "Not an SEC registrant. Financials come from the company's own annual report workbook."};
    case "includes_minorities":
      return {chip: "Includes minorities", text: `IFRS ${p.line || "profit"} here includes non-controlling interests; the share attributable to shareholders is not stored for this filer.`};
    case "market_cap_diluted_route":
      return {chip: "Diluted shares", text: `No cover-page share count on file, so market cap uses ${fyWord} weighted diluted shares, per US-listed share.`};
    case "stale_shares":
      return {chip: "Stale share count", text: `The cover-page share count on file is from ${fmtDate(p.as_of)}, so market cap uses ${fyWord} weighted diluted shares.`};
    case "cover_count_exception":
      return {chip: "Share count exception", text: `${p.reason ? stripStop(p.reason) + "." : ""} Market cap uses ${fyWord} weighted diluted shares.`.trim()};
    case "market_cap_disagreement": {
      const pct = isNum(p.pct) ? (Math.abs(p.pct) <= 1.5 ? wholePct(p.pct) : Math.round(p.pct)) : p.pct;
      const a = isNum(p.primary) ? fmtMoneyProse(p.primary) : p.primary;
      const b = isNum(p.alt) ? fmtMoneyProse(p.alt) : p.alt;
      const BW = {shares_outstanding: "the cover-page share count", diluted_weighted: "FY weighted diluted shares"};
      const pb = BW[p.primary_basis] || p.primary_basis || "the primary count", ab = BW[p.alt_basis] || p.alt_basis || "the other count";
      return {chip: "Market cap routes disagree", text: `Market cap routes disagree by ${pct}%: ${a} from ${pb} and ${b} from ${ab}. ${ucfirst(pb)} is used: ${stripStop(p.reason || "it is the more recent count")}.`};
    }
    case "derived_operating_income":
      return {chip: "Derived operating income", text: "Operating income is derived as revenue less cost of sales, R&D and SG&A. It may leave out separately presented charges, so EBITDA and margins may be overstated."};
    case "no_consensus":
      return {chip: "No consensus", text: p.otc ? NA_TEXT.no_consensus_otc : NA_TEXT.no_consensus};
    case "thin_estimates":
      return {chip: "Thin estimates", text: `Only ${p.n} ${plural(p.n, "analyst covers", "analysts cover")} ${p.period || "this period's"} EPS.`};
    case "estimate_range_wide":
      return {chip: "Wide estimate range", text: `FY1 EPS estimates run from ${fmtEps(p.low)} to ${fmtEps(p.high)} around a mean of ${fmtEps(p.mean)}. The range may mix GAAP and adjusted estimates.`};
    case "eps_sign_change": {
      const a = p.fy1, b = p.fy2;
      const dir = isNum(a) && isNum(b) && a > 0 && b <= 0 ? "from a profit to a loss" : "from a loss to a profit";
      return {chip: "EPS sign change", text: `Consensus moves ${dir} within the next twelve months (FY1 EPS ${fmtEps(a)}, FY2 EPS ${fmtEps(b)}), so P/E NTM is not meaningful.`};
    }
    case "guidance_fx_unstated":
      return {chip: "Guidance currency unstated", text: "The guidance names no currency basis, so it is taken as reported."};
    case "burn_flattered":
      return {chip: "Burn flattered", text: "The trailing cash burn is flattered by inflows the runway row marks, so the runway may read long."};
    case "calc_failed":
      return {chip: "Calculation failed", text: `Calculation failed for this company${p.message ? ": " + stripStop(p.message) : ""}.`};
    case "no_tagged_addbacks":
      return {chip: "No add-backs", text: NO_ADDBACKS_TEXT};
    case "derived_no_addback":
      return {chip: "No add-back on derived", text: DERIVED_NO_ADDBACK_TEXT};
    default:
      return {chip: String(f.code || "Flag"), text: String(f.code || "")};
  }
}

/** Section 8 state catalogue: id -> {severity, where, title, detail, action}. Templates use {x}. */
export const STATE_COPY = {
  loading: {severity: "info", where: ["frame"], title: "Loading comps for {T}", detail: "Reading 70 companies from the book."},
  api_error: {severity: "red", where: ["frame"], title: "Comps did not load", detail: "The API at {api_base} did not answer /comps/valuation ({error}). Start the API, then reload the page."},
  schema: {severity: "red", where: ["frame"], title: "This view is out of date", detail: "It reads data schema {expected} and the API sent {got}. Reload the page to load the matching view."},
  focal_missing: {severity: "red", where: ["frame"], title: "No record for {T}", detail: "The payload has no company {T}. Pick another company."},
  no_peers: {severity: "amber", where: ["banner", "dotplot", "scatter", "table"], title: "No peers selected", detail: "Add a peer with A or from the peer panel, or restore the system set.", action: {label: "Restore system peers", command: "peers.restore"}},
  low_confidence: {severity: "amber", where: ["banner", "kpi5", "dotplot", "summary"], title: "Low confidence", detail: "Only {k} peers have a {metric}. A median of fewer than 5 is not a reliable reference, so no premium or discount is stated."},
  too_few: {severity: "amber", where: ["banner", "kpi5", "dotplot"], title: "No comparison for {T}", detail: "{T} has a {metric} of {v}, but {who} a value. Widen the set to adjacent subsectors, or add peers with A.", action: {label: "Add adjacent-subsector peers", command: "peers.addAdjacent"}},
  default_short: {severity: "amber", where: ["banner", "peers"], title: "Only {n} companies qualify as peers", detail: "{T}'s subsector and stage, with adjacent subsectors, hold {n} companies with data. Add peers with A."},
  padded: {severity: "amber", where: ["banner", "peers", "why"], title: "{k} of {n} peers added below relevance 40", detail: "They were added to reach five peers. Their multiples may not be comparable; review them in the peer panel."},
  weak: {severity: "amber", where: ["banner", "peers"], title: "Weak peer set", detail: "Only {a} of {n} peers score 40 or more on relevance. The median rests on less comparable companies."},
  mixed_models: {severity: "amber", where: ["banner", "peers", "why"], title: "Mixed business models", detail: "{k} of {n} peers are {other} while {T} is {focalType}. Their multiples may not be comparable."},
  no_multiple: {severity: "amber", where: ["banner", "kpis", "dotplot"], title: "No valuation multiple applies to {T}", detail: "{first}: {reason} The view shows {T}'s position on cash, runway and market cap instead."},
  loss_making: {severity: "info", where: ["context"], title: "Loss-making", detail: "Operating loss of {x} in {period}. P/E and EV/EBITDA are not meaningful, so the comparison uses {primary}."},
  sub_scale: {severity: "info", where: ["context"], title: "Revenue under $100m", detail: "Revenue of {x} in {period}, under the $100m floor for revenue multiples. The comparison uses {primary}."},
  pre_revenue: {severity: "info", where: ["context"], title: "Pre-revenue", detail: "No revenue on file for {period}. The comparison uses {primary}."},
  clinical: {severity: "info", where: ["context"], title: "Clinical", detail: "Clinical stage: no inventory or cost of sales on file, so revenue and earnings multiples are not used by default{revenue}."},
  negative_ebitda: {severity: "info", where: ["cells"], title: "Negative EBITDA", detail: "Not meaningful. EBITDA was {x} in {period}."},
  eps_sign_change: {severity: "amber", where: ["cells"], title: "EPS sign change", detail: "Consensus moves {dir} within the next twelve months (FY1 EPS {a}, FY2 EPS {b}), so P/E NTM is not meaningful."},
  missing_estimates: {severity: "amber", where: ["cells", "banner"], title: "Missing estimates", detail: "No consensus estimates for {T}, so the comparison uses reported {period} figures."},
  thin_estimates: {severity: "amber", where: ["cells"], title: "Thin estimates", detail: "Only {n} analysts cover {period} EPS."},
  stale_price: {severity: "amber", where: ["cells", "context", "scope"], title: "Stale price", detail: "Price is from {date}, {n} trading days old."},
  stale_price_universe: {severity: "amber", where: ["banner"], title: "Stale prices", detail: "Prices are from {date}, {n} trading days old. Refresh all in the top bar fetches new closes."},
  failed_source: {severity: "amber", where: ["context", "scope"], title: "Failed sources", detail: "Refresh run {id} ({status}, {date}): {source} failed for {tickers}. Their figures are from the previous successful fetch."},
  partial_run: {severity: "info", where: ["context"], title: "Partial refresh run", detail: "Refresh run {id} finished {date} with status {status}. The sources this view reads all succeeded."},
  stale_balance_sheet: {severity: "amber", where: ["cells"], title: "Stale balance sheet", detail: "Balance sheet from {date}, {days} days old. Enterprise value uses it as filed."},
  stale_consensus: {severity: "amber", where: ["cells"], title: "Stale consensus", detail: "Consensus last checked {date}, {days} days ago."},
  stale_fiscal_year: {severity: "amber", where: ["cells"], title: "Stale fiscal year", detail: "Latest filed fiscal year is {label}, more than 15 months old."},
  stale_shares: {severity: "amber", where: ["cells"], title: "Stale share count", detail: "The cover-page share count on file is from {date}, so market cap uses FY{year} weighted diluted shares."},
  cover_count_exception: {severity: "info", where: ["cells"], title: "Share count exception", detail: "{reason} Market cap uses FY{year} weighted diluted shares."},
  disagreement: {severity: "amber", where: ["cells"], title: "Data-source disagreement", detail: "Market cap routes disagree by {pct}%: {a} from {primary} and {b} from {alt}. {Primary} is used: {reason}."},
  includes_minorities: {severity: "amber", where: ["cells"], title: "Includes minorities", detail: "IFRS {line} here includes non-controlling interests; the share attributable to shareholders is not stored for this filer."},
  fx_converted: {severity: "info", where: ["cells", "context"], title: "Currency converted", detail: "Converted from {cur} at the ECB reference rate of {date}: 1 {cur} = {rate} USD."},
  currency_mismatch: {severity: "amber", where: ["cells"], title: "Currency mismatch", detail: "Filed figures are in {units} while the company record says {company}. Figures use the unit on each filed row."},
  standard_not_recorded: {severity: "info", where: ["context", "peers"], title: "Standard not recorded", detail: NA_TEXT.standard_not_recorded},
  fiscal_year_mismatch: {severity: "amber", where: ["cells", "scope"], title: "Non-December year ends", detail: "Fiscal year ends in {month}. Fiscal years are not calendarised, so FY figures cover a different twelve months from December filers."},
  extreme_outliers: {severity: "amber", where: ["dotplot", "scope", "why"], title: "Extreme outliers", detail: "Values more than three interquartile ranges beyond the quartiles. Statistics include them unless you exclude outliers (U)."},
  mixed_standards: {severity: "info", where: ["why", "method"], title: "Mixed reporting standards", detail: "{i} IFRS and {g} US GAAP filers. Reported figures are not reconciled between standards. Under IFRS 16 lease costs sit below EBITDA and lease payments in financing cash flow, which lifts IFRS filers' EBITDA and free cash flow."},
  street_vs_reported: {severity: "info", where: ["why", "method"], title: "Street against reported EPS", detail: "Forward earnings are street adjusted. Reported earnings are GAAP or IFRS. The two are never divided into each other."},
  mixed_periods: {severity: "info", where: ["table"], title: "Mixed periods", detail: "{n} companies have no LTM figure, so their cells show the last fiscal year, marked A."},
  derived_operating_income: {severity: "amber", where: ["cells"], title: "Derived operating income", detail: "Operating income is derived as revenue less cost of sales, R&D and SG&A. It may leave out separately presented charges, so EBITDA and margins may be overstated."},
  derived_no_addback: {severity: "amber", where: ["cells"], title: "No add-back on derived", detail: DERIVED_NO_ADDBACK_TEXT},
  guidance: {severity: "amber", where: ["cells"], title: "Guidance scope or currency", detail: "The guidance names no currency basis, so it is taken as reported."},
  wide_range: {severity: "amber", where: ["cells"], title: "Wide estimate range", detail: "FY1 EPS estimates run from {low} to {high} around a mean of {mean}. The range may mix GAAP and adjusted estimates."},
  scatter_disabled: {severity: "info", where: ["scatter"], title: "No valuation against growth chart", detail: "{detail}"},
  calc_failed_company: {severity: "red", where: ["row"], title: "Calculation failed", detail: "Calculation failed for {T}: {message}. Other rows are unaffected."},
  calc_failed_section: {severity: "red", where: ["section"], title: "This section could not be computed", detail: "{section} failed: {message}. The rest of the view is unaffected."},
  model_not_computed: {severity: "info", where: ["cells", "notes"], title: "Model not computed", detail: NA_TEXT.model_not_computed},
  time_machine: {severity: "amber", where: ["context"], title: "Live data", detail: "Live data. The time machine does not apply to this view."},
  storage_unavailable: {severity: "amber", where: ["notes"], title: "Storage unavailable", detail: "Notes, layouts and saved sets cannot be stored in this browser. They last until the page reloads."},
  filters_empty: {severity: "info", where: ["table"], title: "No rows match the filters", detail: "Clear filters with R."},
  bridge_not_bridgeable: {severity: "info", where: ["bridge"], title: "No bridge", detail: "No bridge for {metric}. Pick P/E, EV/Revenue, EV/EBITDA, market cap / revenue, P/B, FCF yield or market cap / cash."},
  bridge_nonpositive: {severity: "info", where: ["bridge"], title: "No bridge", detail: "{metric} is zero or negative for {T}, so a multiple of it gives no value."},
  bridge_no_net_debt: {severity: "info", where: ["bridge"], title: "No bridge", detail: "Enterprise value needs net debt, and {T} files no debt line within a year."},
  bridge_no_shares: {severity: "info", where: ["bridge"], title: "No bridge", detail: "No share count on file for {T}."},
  negative_equity: {severity: "amber", where: ["bridge"], title: "Negative implied equity", detail: "Implied equity is negative: net debt and claims exceed the implied enterprise value."},
  undo: {severity: "info", where: ["toast"], title: "Undo available", detail: "{label}. Undo"},
  single_keys_off: {severity: "info", where: ["help"], title: "Single-key shortcuts off", detail: "Single-key shortcuts are off. Use the palette (Cmd K or Ctrl K) or turn them on here."},
  // Revision 3 (12.3): the two evidence groups of Drivers and risks.
  context_pending: {severity: "info", where: ["catalysts", "competition"], title: "Loading catalysts and competition for {T}", detail: "They arrive with the page once the company changes."},
  context_error: {severity: "amber", where: ["catalysts", "competition"], title: "Catalysts and competition did not load", detail: "The API did not answer /companies/{T}/comps-context ({error}). Reload with the reload button."},
  no_catalysts: {severity: "info", where: ["catalysts"], title: "No dated catalysts in the next 12 months", detail: "No pending catalyst for {T} is dated between {from} and {to}. The Catalysts tab lists later events."},
  competition_not_covered: {severity: "info", where: ["competition"], title: "Competition by indication is not covered for {T}", detail: "The indication landscape and the pool model cover the {n} big pharma companies. {T} is read on the {engine} engine, so no rival counts or pool shares are stated."},
  no_indications: {severity: "info", where: ["competition"], title: "No indication to compare for {T}", detail: "No {T} candidate that is marketed or in Phase 2 or later is linked to an indication in the landscape."},
  ranked_by_contest: {severity: "info", where: ["competition"], title: "Ordered by contest", detail: "No modelled value for {T}, so indications are ordered by how many companies contest them."},
  absent_subsectors: {severity: "info", where: ["presets"], title: "Absent subsectors", detail: "No medtech or healthcare services companies are in the 70-company universe, so those presets are not offered. Cell and gene therapy takes their place."},
};

/** Build a StateMsg from STATE_COPY. */
/** "1 trading days old" reads "1 trading day old": the templates are written for the plural. */
function oneDay(text) {
  return typeof text === "string" ? text.replace(/(^|[^0-9.])1 trading days old/g, "$11 trading day old") : text;
}

export function stateMsg(id, params = {}, extra = {}) {
  const c = STATE_COPY[id];
  if (!c) return null;
  return {id, severity: extra.severity || c.severity, where: extra.where || c.where.slice(),
          title: fill(c.title, params), detail: oneDay(fill(c.detail, params)),
          action: extra.action !== undefined ? extra.action : (c.action ? {...c.action} : null)};
}

export const PRESET_FOOTNOTE = STATE_COPY.absent_subsectors.detail;
export const SYSTEM_LABEL = "System-generated summary from the table below. It states associations, not causes.";
export const SYSTEM_LABEL_SHORT = "System-generated";
export const STORAGE_LINE = "Peer sets, layouts, table settings and notes are saved in this browser only. Another browser or port starts empty.";
export const NOT_ASSESSED = [
  "Recurring revenue share: no comparable free data.",
  "Reimbursement exposure: no comparable free measure. IRA Part D gross spending exists but is not revenue at risk.",
];

// ---------------------------------------------------------------------------------------------
// 4.2 Column catalogue and 4.5 presets (data)
// ---------------------------------------------------------------------------------------------

export const COLUMN_GROUPS = [
  {id: "company", label: "Company"},
  {id: "valuation", label: "Valuation"},
  {id: "growth", label: "Growth"},
  {id: "profitability", label: "Profitability"},
  {id: "balance", label: "Balance sheet and risk"},
  {id: "healthcare", label: "Healthcare"},
];

function col(id, group, label, unit, fmt, bases, dir, prov, tooltip, extra = {}) {
  return {id, group, label, unit, fmt, bases, dir, prov, tooltip, signed: false, earnings: false,
          prose: null, width: 84, ...extra};
}

/** The five frozen base columns (4.1). */
export const FROZEN_BASE = [
  {id: "exp", group: "company", label: "", aria: "Expand row", width: 20},
  {id: "incl", group: "company", label: "", aria: "In statistics", width: 28},
  {id: "rel", group: "company", label: "Fit", width: 44,
   tooltip: "Relevance of the peer to the focal company, 0 to 100, from six weighted components."},
  {id: "company", group: "company", label: "Company", width: 176, tooltip: "Company name as stored in the company record."},
  {id: "ticker", group: "company", label: "Ticker", width: 64, tooltip: "US-listed ticker. A mark after it means the row carries a data flag."},
];
export const FROZEN_BASE_WIDTH = {wide: 332, ultrawide: 332, laptop: 384, narrow: 328};

export const COLUMNS = [
  // Company
  col("country", "company", "Country", null, "text", ["-"], "n", "S", "Country code as stored in the company record. For some foreign companies listed on Nasdaq it records the US listing, not the domicile.", {width: 72}),
  col("subsector", "company", "Subsector", null, "chip", ["-"], "n", "C", "Big pharma, Biotech or Cell and gene, from the terminal's engine rule, with commercial or clinical stage from inventory and cost of sales.", {width: 104}),
  col("currency", "company", "Filed in", null, "text", ["-"], "n", "S", "The currency of the filed accounts. Amounts are converted at the ECB reference rate; ratios use the filed figures.", {width: 72}),
  col("price", "company", "Price", "USD", "price2", ["-"], "n", "S", "Last close of the US-listed line, unadjusted. For foreign companies this is the ADR or US line, not the home listing.", {prose: "share price"}),
  col("change_1d", "company", "1 day", "%", "pct1", ["-"], "n", "C", "Change between the last two closes. Unadjusted, so an ex-dividend day reads as a fall.", {signed: true, prose: "1-day price change"}),
  col("ttm_price_change", "company", "12 months", "%", "pct1", ["-"], "n", "C", "Share price change over the trailing twelve months.", {signed: true, prose: "12-month price change"}),
  col("spark_90d", "company", "90 days", null, "spark", ["-"], "n", "S", "Daily closes over the last 90 days, ending on the last close.", {width: 96}),
  col("market_cap", "company", "Market cap", "{cur} bn", "money1", ["-"], "n", "C", "Price times shares. Shares outstanding from the latest cover page when it is under 400 days old; otherwise FY weighted diluted shares, per US-listed share. The cell tooltip names the route.", {prose: "market cap"}),
  col("ev", "company", "EV", "{cur} bn", "money1", ["-"], "n", "C", "Enterprise value: market cap plus net debt at the latest balance sheet. Excludes leases, pensions, minorities and other claims, which the bridge can apply separately.", {prose: "enterprise value"}),
  col("revenue", "company", "Revenue", "{cur} bn", "money1", ["FY0", "LTM"], "n", "S", "Revenue for the last fiscal year, or the last twelve months where interim filings allow, converted at the ECB reference rate.", {prose: "revenue"}),
  // Valuation
  col("ev_revenue", "valuation", "EV/Revenue", TIMES, "mult1", ["LTM", "FY0", "FY1"], "n", "C", "Enterprise value over revenue. LTM where interim filings allow, else the last fiscal year; FY1 uses the company's own total revenue guidance at reported rates.", {prose: "EV/Revenue"}),
  col("price_to_sales", "valuation", "Market cap / revenue", TIMES, "mult1", ["LTM", "FY0"], "n", "C", "Market cap over revenue. Needs no debt figure, so it covers companies whose enterprise value cannot be computed.", {prose: "market cap to revenue", width: 96}),
  col("ev_ebitda", "valuation", "EV/EBITDA", TIMES, "mult1", ["FY0"], "n", "C", "Enterprise value over EBITDA for the last fiscal year. EBITDA is operating income plus depreciation and amortisation as filed. Under IFRS 16 lease costs sit below EBITDA, which lifts IFRS filers' EBITDA against US GAAP peers. No free forward EBITDA exists.", {prose: "EV/EBITDA"}),
  col("pe", "valuation", "P/E", TIMES, "mult1", ["NTM", "FY1", "FY2", "FY0", "LTM"], "n", "C", "Price over earnings per share. Forward bases use Nasdaq street consensus, which is adjusted. FY0 and LTM use reported net income under GAAP or IFRS; IFRS profit can include minority interests where the attributable figure is not stored.", {prose: "P/E", earnings: true}),
  col("fcf_yield", "valuation", "FCF yield", "%", "pct1", ["FY0"], "n", "C", "Free cash flow (operating cash flow less capital expenditure) for the last fiscal year over market cap. Under IFRS 16 lease payments sit in financing cash flow, which lifts IFRS filers' free cash flow against US GAAP peers.", {prose: "FCF yield"}),
  col("price_to_book", "valuation", "P/B", TIMES, "mult1", ["-"], "n", "C", "Market cap over shareholders' equity at the latest balance sheet. IFRS equity can include minority interests.", {prose: "price to book"}),
  col("peg", "valuation", "PEG", TIMES, "mult2", ["NTM"], "n", "C", "NTM P/E over the street EPS growth rate from FY1 to FY3, in percent. Both on the street basis. FY3 often rests on one to three estimates.", {prose: "PEG", earnings: true}),
  col("mcap_to_cash", "valuation", "Market cap / cash", TIMES, "mult1", ["-"], "n", "C", "Market cap over cash, short-term and long-term investments at the latest balance sheet. Under 1× the market values the company below its cash.", {prose: "market cap to cash", width: 96}),
  col("pt_upside", "valuation", "Street target", "%", "pct1", ["-"], "n", "S", "Upside to the 12-month consensus price target from Nasdaq, per US-listed share.", {signed: true, prose: "upside to the street target"}),
  col("ev_per_late_trial", "valuation", "EV per late trial", "{cur} m", "money0m", ["-"], "n", "C", "Enterprise value per lead-sponsored Phase 3 or Phase 2/3 trial.", {prose: "EV per late-stage trial", width: 96}),
  col("pipeline_to_ev", "valuation", "Pipeline / EV", "%", "pct1", ["-"], "+", "M", "Risk-adjusted NPV of the modelled pipeline over enterprise value. Model output, for the 20 modelled companies.", {prose: "pipeline value to EV"}),
  // Growth
  col("revenue_growth", "growth", "Revenue growth", "%", "pct1", ["FY0", "FY1"], "+", "C", "Revenue growth over the prior fiscal year in the filing currency, or the company's guided total revenue growth for FY1 at reported rates.", {signed: true, prose: "revenue growth"}),
  col("revenue_cagr3", "growth", "Revenue CAGR 3y", "%", "pct1", ["FY0"], "+", "C", "Compound annual revenue growth over three fiscal years to FY0, in the filing currency.", {signed: true, prose: "revenue CAGR"}),
  col("ebitda_growth", "growth", "EBITDA growth", "%", "pct1", ["FY0"], "+", "C", "EBITDA growth over the prior fiscal year. Not meaningful when the prior year was small, zero or negative.", {signed: true, prose: "EBITDA growth"}),
  col("eps_growth", "growth", "EPS growth", "%", "pct1", ["NTM", "FY1", "FY2", "FY0"], "+", "C", "Forward: street EPS FY2 over FY1. FY0: reported diluted EPS over the prior year. The two bases are never mixed in one figure.", {signed: true, prose: "EPS growth", earnings: true}),
  col("eps_cagr", "growth", "EPS CAGR FY1 to FY3", "%", "pct1", ["NTM"], "+", "C", "Compound annual growth of street EPS from FY1 to FY3.", {signed: true, prose: "EPS CAGR", earnings: true, width: 96}),
  // Profitability
  col("gross_margin", "profitability", "Gross margin", "%", "pct1", ["FY0"], "+", "C", "Gross profit over revenue, last fiscal year. Gross profit as tagged, or revenue less cost of sales.", {prose: "gross margin"}),
  col("ebitda_margin", "profitability", "EBITDA margin", "%", "pct1", ["FY0"], "+", "C", "EBITDA over revenue, last fiscal year.", {prose: "EBITDA margin"}),
  col("operating_margin", "profitability", "Operating margin", "%", "pct1", ["FY0"], "+", "C", "Operating income over revenue, last fiscal year. The ex amortisation and IPR&D basis adds back those tagged lines, except where operating income is derived and never subtracted them.", {prose: "operating margin"}),
  col("net_margin", "profitability", "Net margin", "%", "pct1", ["FY0"], "+", "C", "Net income over revenue, last fiscal year, as filed.", {prose: "net margin"}),
  col("roic", "profitability", "ROIC", "%", "pct1", ["FY0"], "+", "C", "Operating income after tax at the effective rate (clamped 0 to 50 %) over equity plus debt less cash.", {prose: "ROIC"}),
  col("rd_pct", "profitability", "R&D / revenue", "%", "pct1", ["FY0"], "n", "C", "Research and development expense over revenue, last fiscal year.", {prose: "R&D share of revenue"}),
  // Balance sheet and risk
  col("net_debt", "balance", "Net debt", "{cur} bn", "money1", ["-"], "n", "C", "Debt less cash and investments at the latest balance sheet. Negative means net cash.", {signed: true, prose: "net debt"}),
  col("net_debt_ebitda", "balance", "Net debt / EBITDA", TIMES, "mult1", ["FY0"], "-", "C", "Net debt over last fiscal year EBITDA. Negative means net cash.", {signed: true, prose: "net debt to EBITDA", width: 96}),
  col("cash_to_mcap", "balance", "Cash / market cap", "%", "pct1", ["-"], "n", "C", "Cash, short-term and long-term investments at the latest balance sheet over market cap.", {prose: "cash to market cap", width: 96}),
  col("runway_months", "balance", "Cash runway", "months", "int", ["-"], "+", "C", "Cash and investments plus raises since the balance sheet, over trailing twelve-month operating cash burn.", {prose: "cash runway"}),
  col("beta", "balance", "Beta", null, "num2", ["-"], "n", "C", "Five-year weekly beta against the S&P 500, Blume-adjusted.", {prose: "beta"}),
  col("vol_1y", "balance", "Volatility 1y", "%", "pct0", ["-"], "n", "C", "Annualised standard deviation of daily log returns over one year.", {prose: "volatility"}),
  col("est_dispersion", "balance", "Estimate range", "% of mean", "pct0", ["FY1"], "-", "C", "High less low FY1 EPS estimate over the mean. The range may mix GAAP and adjusted estimates.", {prose: "estimate range"}),
  col("n_estimates", "balance", "Estimates", "count", "int", ["FY1"], "+", "S", "Number of analysts in the FY1 EPS consensus.", {prose: "estimate count"}),
  // Healthcare
  col("stage", "healthcare", "Stage", null, "chip", ["-"], "n", "C", "Commercial when the company carries inventory and cost of sales, otherwise clinical.", {width: 96}),
  col("lead_phase", "healthcare", "Lead phase", null, "chip", ["-"], "n", "C", "Marketed if any asset is marketed, otherwise the furthest trial phase.", {width: 96}),
  col("major_products", "healthcare", "Products over $1bn", "count", "int", ["FY0"], "+", "C", "Products with at least USD 1bn of revenue in the last fiscal year. Can include non-product lines a company reports beside products.", {prose: "products over $1bn", width: 96}),
  col("loe_share_5y", "healthcare", "Losing exclusivity 5y", "%", "pct1", ["-"], "-", "C", "Share of tagged product revenue losing US exclusivity within five years.", {prose: "revenue losing exclusivity", width: 96}),
  col("loe_unpriced_5y", "healthcare", "Unpriced losses 5y", "count", "int", ["-"], "-", "C", "Products losing exclusivity within five years whose revenue is not on file, so the share beside it cannot count them.", {prose: "unpriced exclusivity losses", width: 96}),
  col("top_product_share", "healthcare", "Top product", "%", "pct1", ["FY0"], "-", "C", "The largest product's share of tagged product revenue. A proxy for concentration.", {prose: "top product share"}),
  col("trial_concentration", "healthcare", "Top asset trials", "%", "pct1", ["-"], "-", "C", "The asset with the most active lead-sponsored trials, as a share of all of them. A proxy for pipeline concentration.", {prose: "top asset share of trials"}),
  col("late_trials", "healthcare", "Late-stage trials", "count", "int", ["-"], "+", "C", "Lead-sponsored Phase 3 and Phase 2/3 trials on file.", {prose: "late-stage trials"}),
  col("revenue_per_late_trial", "healthcare", "Revenue per late trial", "{cur} bn", "money1", ["FY0"], "n", "C", "Revenue over late-stage trials: how much of today's business each late-stage trial stands against.", {prose: "revenue per late-stage trial", width: 96}),
  col("catalysts_12m", "healthcare", "Catalysts 12m", "count", "int", ["-"], "n", "C", "Pending catalysts in the next twelve months. Almost all are derived from trial records with estimated dates.", {prose: "catalysts in 12 months"}),
  col("pipeline_ps", "healthcare", "Pipeline rNPV", "USD/share", "price2", ["-"], "+", "M", "Risk-adjusted NPV of the modelled pipeline per US-listed share. Model output.", {prose: "pipeline rNPV per share"}),
];
export const COLUMN_BY_ID = Object.fromEntries(COLUMNS.map((c) => [c.id, c]));
const FROZEN_IDS = new Set(FROZEN_BASE.map((c) => c.id));
const NUMERIC_FMTS = new Set(["mult1", "mult2", "pct1", "pct0", "money1", "money0m", "price2", "num2", "int"]);
const MONEY_FMTS = new Set(["money1", "money0m"]);
function isNumericCol(c) { return !!c && NUMERIC_FMTS.has(c.fmt); }
function isMoneyCol(c) { return !!c && MONEY_FMTS.has(c.fmt); }

export const PRESETS = [
  {id: "core", key: "1", label: "Core valuation", columns: ["market_cap", "ev", "pe", "ev_ebitda", "ev_revenue", "fcf_yield", "price_to_book", "pt_upside", "revenue_growth"]},
  {id: "growth", key: "2", label: "Growth and profitability", columns: ["revenue", "revenue_growth", "revenue_cagr3", "ebitda_growth", "eps_growth", "gross_margin", "operating_margin", "net_margin", "roic"]},
  {id: "balance", key: "3", label: "Balance sheet and risk", columns: ["market_cap", "net_debt", "net_debt_ebitda", "cash_to_mcap", "runway_months", "beta", "vol_1y", "est_dispersion", "n_estimates"]},
  {id: "pharma", key: "4", label: "Pharma", columns: ["market_cap", "pe", "ev_ebitda", "revenue_growth", "operating_margin", "loe_share_5y", "rd_pct", "late_trials", "pipeline_ps"]},
  {id: "biotech", key: "5", label: "Biotechnology", columns: ["market_cap", "ev_revenue", "price_to_sales", "mcap_to_cash", "revenue_growth", "runway_months", "lead_phase", "catalysts_12m", "pt_upside"]},
  {id: "cellgene", key: "6", label: "Cell and gene therapy", columns: ["market_cap", "mcap_to_cash", "runway_months", "lead_phase", "trial_concentration", "late_trials", "catalysts_12m", "vol_1y", "pt_upside"]},
  {id: "custom", key: "7", label: "Custom", columns: []},
];
export const PRESET_BY_ID = Object.fromEntries(PRESETS.map((p) => [p.id, p]));
const PRESET_IDS = PRESETS.map((p) => p.id);

/** Prose label of a column for sentences (3.11), for example "market cap to revenue". */
export function proseLabel(colId) {
  const c = COLUMN_BY_ID[colId];
  if (!c) return colId;
  return c.prose || lcfirst(c.label);
}

// ---------------------------------------------------------------------------------------------
// 3.3 Classification
// ---------------------------------------------------------------------------------------------

export const TYPE_LABEL = {profitable: "profitable", loss_making: "loss-making",
  sub_scale: "commercial with revenue under $100m", clinical: "clinical-stage"};

export function companyType(c) {
  if (!c) return null;
  if (c.stage === "clinical") return "clinical";
  const rev = numAt(c, "periods.FY0.revenue_usd_m");
  if (rev === null || rev < MIN_REVENUE_USD_M) return "sub_scale";
  const op = numAt(c, "periods.FY0.operating_income_usd_m");
  if (op !== null) return op <= 0 ? "loss_making" : "profitable";
  const ni = numAt(c, "periods.FY0.net_income_usd_m");
  if (ni !== null && ni <= 0) return "loss_making";
  return "profitable";
}

export function isPreRevenue(c) {
  const rev = get(c, "periods.FY0.revenue_usd_m");
  return rev === null || rev === undefined || rev === 0;
}

export function typeGroup(type) {
  if (type === "profitable") return "profitable";
  if (type === "loss_making") return "loss-making";
  if (type === "sub_scale" || type === "clinical") return "pre-scale";
  return null;
}

export function engineAffinity(a, b) {
  if (!a || !b) return 0;
  if (a === b) return 1.0;
  const pair = [a, b].sort().join("|");
  if (pair === "biotech|cellgene") return 0.5;
  if (pair === "biotech|pharma") return 0.3;
  if (pair === "cellgene|pharma") return 0.1;
  return 0;
}

const PHASE_RANK = {"Preclinical": 0, "Phase 1": 1, "Phase 1/2": 1.5, "Phase 2": 2, "Phase 2/3": 2.5,
  "Phase 3": 3, "Filed": 3.5, "Marketed": 4};
export function phaseRank(phase) {
  return Object.prototype.hasOwnProperty.call(PHASE_RANK, phase) ? PHASE_RANK[phase] : null;
}

// ---------------------------------------------------------------------------------------------
// 3.4 Cells and multiples
// ---------------------------------------------------------------------------------------------

class Missing { constructor(path, code) { this.path = path; this.code = code || null; } }
class NotMeaningful { constructor(reason, brief) { this.reason = reason; this.brief = brief || null; } }
class NoBurn {}

/** The null reason code for a path: the entry on the path itself or on the nearest parent. */
export function naCode(rec, path) {
  const na = (rec && rec.na) || {};
  let p = path || "";
  while (p) {
    if (na[p]) return na[p];
    const i = p.lastIndexOf(".");
    if (i < 0) break;
    p = p.slice(0, i);
  }
  return null;
}

/** Display currency code for a record under ctx: the row currency in REPORTED mode. */
export function displayCurrency(rec, ctx) {
  const cur = (ctx && ctx.currency) || "USD";
  if (cur === "REPORTED") return (rec && (rec.row_currency || rec.reporting_currency)) || "USD";
  return cur;
}
function rateFor(cur, ctx) {
  if (cur === "USD") return 1;
  const r = get(ctx, "fx.usd_per_unit." + cur);
  return isNum(r) && r > 0 ? r : null;
}

export function resolveBasis(colId, basis) {
  const c = COLUMN_BY_ID[colId];
  if (!c) return null;
  if (c.bases[0] === "-") return "-";
  return c.bases.includes(basis) ? basis : c.bases[0];
}

export function multipleDirection(colId) {
  if (colId === "fcf_yield") return "richer_down";
  if (["pe", "ev_ebitda", "ev_revenue", "price_to_sales", "price_to_book", "peg", "mcap_to_cash"].includes(colId)) return "richer_up";
  return null;
}

function helper(rec, ctx) {
  const cur = displayCurrency(rec, ctx);
  const rate = rateFor(cur, ctx);
  return {
    rec, ctx, cur,
    v(path) { const x = get(rec, path); return x === undefined ? null : x; },
    num(path) { return numAt(rec, path); },
    need(path) {
      const x = get(rec, path);
      if (x === null || x === undefined || (typeof x === "number" && !Number.isFinite(x))) throw new Missing(path);
      return x;
    },
    money(usd) { if (rate === null) throw new Missing(null, "no_rate"); return usd / rate; },
    mp(usd) { return rate === null ? fmtMoneyProse(usd) : fmtMoneyProse(usd, cur, ctx && ctx.fx); },
  };
}
function fy0Label(h) { return h.v("periods.FY0.label") || "FY0"; }
function balanceDate(h) { const d = h.v("ev.balance_sheet_as_of"); return d ? fmtDate(d) : null; }
const usdProse = (v) => fmtMoneyProse(v);

function revenueOn(h, b) {
  if (b === "LTM") {
    const ltm = h.num("periods.LTM.revenue_usd_m");
    if (ltm !== null) return {usd: ltm, period: h.v("periods.LTM.label") || "LTM", key: "LTM", tag: "A", differs: false};
    const fy = h.need("periods.FY0.revenue_usd_m");
    return {usd: fy, period: fy0Label(h), key: "FY0", tag: "A", differs: true};
  }
  return {usd: h.need("periods.FY0.revenue_usd_m"), period: fy0Label(h), key: "FY0", tag: "A", differs: false};
}
function guidedRevenue(h) {
  const g = h.num("growth.revenue_guided_fy1");
  if (g === null) {
    const code = naCode(h.rec, "growth.revenue_guided_fy1") || naCode(h.rec, "periods.FY1.guidance") || "no_guidance";
    if (code === "guidance_product_scope" || code === "guidance_cer") throw new NotMeaningful(NA_TEXT[code]);
    throw new Missing(null, code);
  }
  const val = h.num("periods.FY1.guidance.value_usd_m");
  const fy0 = h.num("periods.FY0.revenue_usd_m");
  const usd = val !== null ? val : (fy0 !== null ? fy0 * (1 + g) : null);
  if (usd === null) throw new Missing("periods.FY0.revenue_usd_m");
  return {usd, g, period: h.v("periods.FY1.label") || "FY1", key: "FY1", tag: "G", differs: false};
}
function revFloor(usd, period, what = "revenue multiples") {
  if (usd < MIN_REVENUE_USD_M) {
    throw new NotMeaningful(`Revenue of ${usdProse(usd)} in ${period} is under the $100m floor for ${what}.`);
  }
}
function ebitdaFY0(h, flags) {
  const e = h.need("periods.FY0.ebitda_usd_m");
  if (!h.ctx || h.ctx.earnings !== "adjusted") return e;
  if (h.v("periods.FY0.operating_income_basis") === "derived") { flags.push("derived_no_addback"); return e; }
  const iprd = h.num("periods.FY0.acquired_iprd_usd_m"), am = h.num("periods.FY0.amortisation_usd_m");
  if (iprd === null && am === null) { flags.push("no_tagged_addbacks"); return e; }
  return e + (iprd || 0);
}
function opIncFY0(h, flags) {
  const o = h.need("periods.FY0.operating_income_usd_m");
  if (!h.ctx || h.ctx.earnings !== "adjusted") return o;
  if (h.v("periods.FY0.operating_income_basis") === "derived") { flags.push("derived_no_addback"); return o; }
  const iprd = h.num("periods.FY0.acquired_iprd_usd_m"), am = h.num("periods.FY0.amortisation_usd_m");
  if (iprd === null && am === null) { flags.push("no_tagged_addbacks"); return o; }
  return o + (am || 0) + (iprd || 0);
}
function growthVal(h, path) {
  const g = h.num(path);
  if (g === null) {
    if (naCode(h.rec, path) === "non_positive_base") throw new NotMeaningful(NA_TEXT.non_positive_base);
    throw new Missing(path);
  }
  return g;
}
function growthCap(g) {
  if (Math.abs(g) > MAX_ABS_GROWTH) {
    throw new NotMeaningful(`Growth of ${fmtPctProse(g)} is over 500%, so it is not meaningful.`);
  }
}
function revenueBaseFloor(bases) {
  const b = Array.isArray(bases) ? bases : [];
  if (b.some((x) => isNum(x) && x < MIN_GROWTH_BASE_USD_M)) {
    const parts = b.map((x) => (isNum(x) ? usdProse(x) : "not filed"));
    throw new NotMeaningful(`Revenue is under $10m at one end (${parts.join(" and ")}), so growth is not meaningful.`);
  }
}
function epsBaseFloor(base) {
  if (!isNum(base)) return;
  if (base <= 0) throw new NotMeaningful(NA_TEXT.non_positive_base);
  if (Math.abs(base) < MIN_EPS_GROWTH_BASE) {
    throw new NotMeaningful(`Base EPS of ${fmtEps(base)} is under 0.10, so growth is not meaningful.`);
  }
}
function marginFloor(v, what) {
  if (v < MIN_MARGIN) throw new NotMeaningful(`${what} of ${fmtPctProse(v)} is below ${MINUS}100%.`);
}

function peCompute(h, b) {
  const price = h.need("market.price");
  if (b === "NTM") {
    const e1 = h.num("periods.FY1.eps"), e2 = h.num("periods.FY2.eps");
    const n1 = e1 !== null && e1 <= 0, n2 = e2 !== null && e2 <= 0;
    if (n1 || n2) {
      if (e1 !== null && e2 !== null && n1 !== n2) {
        const dir = n1 ? "from a loss to a profit" : "from a profit to a loss";
        throw new NotMeaningful(`Consensus moves ${dir} within the next twelve months (FY1 EPS ${fmtEps(e1)}, FY2 EPS ${fmtEps(e2)}), so P/E NTM is not meaningful.`,
          `consensus moves ${dir} within the next twelve months`);
      }
      if (n1 && n2) {
        throw new NotMeaningful(`Consensus EPS is at or below zero for both FY1 (${fmtEps(e1)}) and FY2 (${fmtEps(e2)}), so P/E NTM is not meaningful.`,
          "consensus EPS is at or below zero for both FY1 and FY2");
      }
      throw new NotMeaningful(`Consensus ${n1 ? "FY1" : "FY2"} EPS is at or below zero, so P/E NTM is not meaningful.`);
    }
    const eps = h.need("periods.NTM.eps");
    if (eps <= 0) throw new NotMeaningful(`NTM EPS of ${fmtEps(eps)} is at or below zero.`);
    return {v: price / eps, tag: "E", period: "NTM", key: "NTM"};
  }
  if (b === "FY1" || b === "FY2") {
    const eps = h.need(`periods.${b}.eps`);
    const label = h.v(`periods.${b}.label`) || b;
    if (eps <= 0) throw new NotMeaningful(`Consensus ${label} EPS of ${fmtEps(eps)} is at or below zero.`);
    return {v: price / eps, tag: "E", period: label, key: b};
  }
  const mcap = h.need("market.market_cap_usd_m");
  let ni, period, key = "FY0", differs = false;
  if (b === "LTM") {
    const l = h.num("periods.LTM.net_income_usd_m");
    if (l !== null) { ni = l; period = h.v("periods.LTM.label") || "LTM"; key = "LTM"; }
    else { ni = h.need("periods.FY0.net_income_usd_m"); period = fy0Label(h); differs = true; }
  } else {
    ni = h.need("periods.FY0.net_income_usd_m"); period = fy0Label(h);
  }
  if (ni <= 0) throw new NotMeaningful(`Net income was ${h.mp(ni)} in ${period}.`);
  return {v: mcap / ni, tag: "A", period, key, tagDiffers: differs};
}

const COMPUTE = {
  country(h) { return {text: String(h.need("country"))}; },
  subsector(h) {
    const e = h.need("engine");
    const labels = (h.ctx && h.ctx.engineLabels) || DEFAULT_ENGINE_LABELS;
    return {text: labels[e] || DEFAULT_ENGINE_LABELS[e] || e, tone: h.v("stage") === "clinical" ? "clinical" : "neutral"};
  },
  currency(h) {
    const c = h.v("row_currency") || h.need("reporting_currency");
    return {text: c + (c !== "USD" ? " ⇄" : "")};
  },
  price(h) { return {v: h.need("market.price")}; },
  change_1d(h) { return {v: h.need("market.change_1d")}; },
  ttm_price_change(h) { return {v: h.need("market.ttm_change")}; },
  spark_90d(h) {
    const arr = h.v("market.spark_90d");
    if (!Array.isArray(arr) || !arr.length) throw new Missing("market.spark_90d");
    return {text: "", series: arr.filter(isNum)};
  },
  market_cap(h) { return {v: h.money(h.need("market.market_cap_usd_m"))}; },
  ev(h) { return {v: h.money(h.need("ev.ev_usd_m")), period: balanceDate(h)}; },
  revenue(h, b) {
    const r = revenueOn(h, b);
    return {v: h.money(r.usd), tag: r.tag, period: r.period, key: r.key, tagDiffers: r.differs};
  },
  ev_revenue(h, b) {
    const ev = h.need("ev.ev_usd_m");
    const r = b === "FY1" ? guidedRevenue(h) : revenueOn(h, b);
    revFloor(r.usd, r.period);
    if (ev <= 0) throw new NotMeaningful(`Enterprise value is zero or negative (${h.mp(ev)}).`);
    const v = ev / r.usd;
    if (v > MAX_REVENUE_MULTIPLE) throw new NotMeaningful(`EV/Revenue of ${fmtNumber(v, 1)}${TIMES} is over the 100${TIMES} cap.`);
    return {v, tag: r.tag, period: r.period, key: r.key, tagDiffers: r.differs};
  },
  price_to_sales(h, b) {
    const mcap = h.need("market.market_cap_usd_m");
    const r = revenueOn(h, b);
    revFloor(r.usd, r.period);
    const v = mcap / r.usd;
    if (v > MAX_REVENUE_MULTIPLE) throw new NotMeaningful(`Market cap / revenue of ${fmtNumber(v, 1)}${TIMES} is over the 100${TIMES} cap.`);
    return {v, tag: r.tag, period: r.period, key: r.key, tagDiffers: r.differs};
  },
  ev_ebitda(h, b, flags) {
    const ev = h.need("ev.ev_usd_m");
    const e = ebitdaFY0(h, flags);
    if (e <= 0) throw new NotMeaningful(`EBITDA was ${h.mp(e)} in ${fy0Label(h)}.`);
    if (ev <= 0) throw new NotMeaningful(`Enterprise value is zero or negative (${h.mp(ev)}).`);
    return {v: ev / e, tag: "A", period: fy0Label(h), key: "FY0"};
  },
  pe(h, b) { return peCompute(h, b); },
  fcf_yield(h) {
    const fcf = h.need("periods.FY0.fcf_usd_m");
    const mcap = h.need("market.market_cap_usd_m");
    if (fcf < 0) throw new NotMeaningful(`Free cash flow was ${h.mp(fcf)} in ${fy0Label(h)}.`);
    return {v: fcf / mcap, tag: "A", period: fy0Label(h), key: "FY0"};
  },
  price_to_book(h) {
    const mcap = h.need("market.market_cap_usd_m");
    const eq = h.need("periods.FY0.equity_usd_m");
    if (eq <= 0) throw new NotMeaningful(`Shareholders' equity is ${h.mp(eq)}, at or below zero.`);
    const d = h.v("periods.FY0.equity_as_of") || h.v("ev.balance_sheet_as_of");
    return {v: mcap / eq, period: d ? fmtDate(d) : null};
  },
  peg(h) {
    const pe = peCompute(h, "NTM");
    const fy1 = h.num("periods.FY1.eps");
    if (fy1 !== null && fy1 < MIN_EPS_GROWTH_BASE) {
      throw new NotMeaningful(`FY1 EPS of ${fmtEps(fy1)} is under 0.10, so the EPS growth rate is not meaningful.`);
    }
    const cagr = growthVal(h, "growth.eps_street_cagr");
    if (cagr <= 0) throw new NotMeaningful(`Street EPS CAGR FY1 to FY3 is ${fmtPctProse(cagr)}, at or below zero.`);
    return {v: pe.v / (cagr * 100), tag: "E", period: "NTM", key: "NTM"};
  },
  mcap_to_cash(h) {
    const mcap = h.need("market.market_cap_usd_m");
    const cash = h.need("ev.cash_usd_m");
    if (cash <= 0) throw new NotMeaningful("Cash and investments are zero, so the ratio is not meaningful.");
    return {v: mcap / cash, period: balanceDate(h)};
  },
  pt_upside(h) {
    const t = h.need("street.price_target.value");
    const p = h.need("market.price");
    return {v: t / p - 1};
  },
  ev_per_late_trial(h) {
    const ev = h.need("ev.ev_usd_m");
    const n = h.need("healthcare.late_trials");
    if (n === 0) throw new NotMeaningful("No late-stage trials on file, so EV per trial is not meaningful.");
    if (ev <= 0) throw new NotMeaningful(`Enterprise value is zero or negative (${h.mp(ev)}).`);
    return {v: h.money(ev) / n};
  },
  pipeline_to_ev(h) {
    const r = h.need("model.pipeline_rnpv_usd_m");
    const ev = h.need("ev.ev_usd_m");
    if (ev <= 0) throw new NotMeaningful(`Enterprise value is zero or negative (${h.mp(ev)}).`);
    return {v: r / ev, tag: "M"};
  },
  revenue_growth(h, b) {
    if (b === "FY1") {
      const r = guidedRevenue(h);
      growthCap(r.g);
      return {v: r.g, tag: "G", period: r.period, key: "FY1"};
    }
    const g = growthVal(h, "growth.revenue_fy");
    revenueBaseFloor(h.v("growth.bases.revenue_fy"));
    growthCap(g);
    return {v: g, tag: "A", period: fy0Label(h), key: "FY0"};
  },
  revenue_cagr3(h) {
    const g = growthVal(h, "growth.revenue_cagr3");
    revenueBaseFloor(h.v("growth.bases.revenue_cagr3"));
    growthCap(g);
    return {v: g, tag: "A", period: fy0Label(h), key: "FY0"};
  },
  ebitda_growth(h, b, flags) {
    let path = "growth.ebitda_fy";
    if (h.ctx && h.ctx.earnings === "adjusted") {
      if (h.v("periods.FY0.operating_income_basis") === "derived") flags.push("derived_no_addback");
      else if (h.num("periods.FY0.acquired_iprd_usd_m") === null && h.num("periods.FY0.amortisation_usd_m") === null) flags.push("no_tagged_addbacks");
      else path = "growth.ebitda_fy_adjusted";
    }
    const g = growthVal(h, path);
    const bases = h.v("growth.bases.ebitda_fy");
    const base = Array.isArray(bases) ? bases[1] : null;
    if (isNum(base)) {
      if (base <= 0) throw new NotMeaningful(NA_TEXT.non_positive_base);
      if (Math.abs(base) < MIN_EBITDA_GROWTH_BASE_USD_M) {
        throw new NotMeaningful(`Prior-year EBITDA of ${usdProse(base)} is under $10m, so growth is not meaningful.`);
      }
    }
    growthCap(g);
    return {v: g, tag: "A", period: fy0Label(h), key: "FY0"};
  },
  eps_growth(h, b) {
    if (b === "FY0") {
      const g = growthVal(h, "growth.eps_fy_gaap");
      const bases = h.v("growth.bases.eps_fy_gaap");
      epsBaseFloor(Array.isArray(bases) ? bases[1] : null);
      growthCap(g);
      return {v: g, tag: "A", period: fy0Label(h), key: "FY0"};
    }
    const g = growthVal(h, "growth.eps_street_fy2");
    const bases = h.v("growth.bases.eps_street_fy2");
    epsBaseFloor(Array.isArray(bases) ? bases[0] : h.num("periods.FY1.eps"));
    growthCap(g);
    return {v: g, tag: "E", period: h.v("periods.FY2.label") || "FY2", key: b};
  },
  eps_cagr(h) {
    const g = growthVal(h, "growth.eps_street_cagr");
    const bases = h.v("growth.bases.eps_street_cagr");
    const fy1 = h.num("periods.FY1.eps") ?? (Array.isArray(bases) && isNum(bases[0]) ? bases[0] : null);
    if (fy1 !== null && fy1 < MIN_EPS_GROWTH_BASE) {
      throw new NotMeaningful(`FY1 EPS of ${fmtEps(fy1)} is under 0.10, so the growth rate is not meaningful.`);
    }
    growthCap(g);
    const a = h.v("periods.FY1.label") || "FY1", z = h.v("periods.FY3.label") || "FY3";
    return {v: g, tag: "E", period: `${a} to ${z}`, key: "NTM"};
  },
  gross_margin(h) {
    const rev = h.need("periods.FY0.revenue_usd_m");
    revFloor(rev, fy0Label(h), "margins and R&D share");
    const gp = h.need("periods.FY0.gross_profit_usd_m");
    const v = gp / rev; marginFloor(v, "Gross margin");
    return {v, tag: "A", period: fy0Label(h), key: "FY0"};
  },
  ebitda_margin(h, b, flags) {
    const rev = h.need("periods.FY0.revenue_usd_m");
    revFloor(rev, fy0Label(h), "margins and R&D share");
    const v = ebitdaFY0(h, flags) / rev; marginFloor(v, "EBITDA margin");
    return {v, tag: "A", period: fy0Label(h), key: "FY0"};
  },
  operating_margin(h, b, flags) {
    const rev = h.need("periods.FY0.revenue_usd_m");
    revFloor(rev, fy0Label(h), "margins and R&D share");
    const v = opIncFY0(h, flags) / rev; marginFloor(v, "Operating margin");
    return {v, tag: "A", period: fy0Label(h), key: "FY0"};
  },
  net_margin(h) {
    const rev = h.num("periods.FY0.revenue_usd_m");
    if (rev === null && h.num("screen_extras.net_margin") !== null && h.num("periods.FY0.net_income_usd_m") === null) {
      return {v: h.num("screen_extras.net_margin"), tag: "A", period: fy0Label(h), key: "FY0"};
    }
    const r = h.need("periods.FY0.revenue_usd_m");
    revFloor(r, fy0Label(h), "margins and R&D share");
    const v = h.need("periods.FY0.net_income_usd_m") / r; marginFloor(v, "Net margin");
    return {v, tag: "A", period: fy0Label(h), key: "FY0"};
  },
  roic(h, b, flags) {
    const rev = h.need("periods.FY0.revenue_usd_m");
    revFloor(rev, fy0Label(h), "margins, ROIC and R&D share");
    const o = opIncFY0(h, flags);
    const tax = h.need("periods.FY0.tax_rate");
    const eq = h.need("periods.FY0.equity_usd_m");
    const debt = h.need("ev.total_debt_usd_m");
    const cash = h.need("ev.cash_usd_m");
    const ic = eq + debt - cash;
    if (ic <= 0) throw new NotMeaningful(`Invested capital (equity plus debt less cash) is ${h.mp(ic)}, at or below zero.`);
    const v = o * (1 - tax) / ic; marginFloor(v, "ROIC");
    return {v, tag: "A", period: fy0Label(h), key: "FY0"};
  },
  rd_pct(h) {
    const rev = h.need("periods.FY0.revenue_usd_m");
    revFloor(rev, fy0Label(h), "margins and R&D share");
    let rd;
    if (h.ctx && h.ctx.earnings === "adjusted" && h.num("periods.FY0.rd_ex_iprd_usd_m") !== null) rd = h.num("periods.FY0.rd_ex_iprd_usd_m");
    else rd = h.need("periods.FY0.rd_usd_m");
    return {v: rd / rev, tag: "A", period: fy0Label(h), key: "FY0"};
  },
  net_debt(h) { return {v: h.money(h.need("ev.net_debt_usd_m")), period: balanceDate(h)}; },
  net_debt_ebitda(h, b, flags) {
    const nd = h.need("ev.net_debt_usd_m");
    const e = ebitdaFY0(h, flags);
    if (e <= 0) throw new NotMeaningful(`EBITDA was ${h.mp(e)} in ${fy0Label(h)}.`);
    return {v: nd / e, tag: "A", period: fy0Label(h), key: "FY0"};
  },
  cash_to_mcap(h) {
    const cash = h.need("ev.cash_usd_m");
    const mcap = h.need("market.market_cap_usd_m");
    return {v: cash / mcap, period: balanceDate(h)};
  },
  runway_months(h, b, flags) {
    const r = h.num("risk.runway_months");
    if (r === null) {
      if (naCode(h.rec, "risk.runway_months") === "not_burning") throw new NoBurn();
      throw new Missing("risk.runway_months");
    }
    if (h.v("risk.burn_flattered") === true && !(h.rec.flags || []).some((f) => f && f.code === "burn_flattered")) flags.push("burn_flattered");
    return {v: r};
  },
  beta(h) { return {v: h.need("market.beta")}; },
  vol_1y(h) { return {v: h.need("market.vol_1y")}; },
  est_dispersion(h) {
    const m = h.num("periods.FY1.eps");
    if (m !== null && Math.abs(m) < MIN_EPS_FOR_DISPERSION) {
      throw new NotMeaningful(`Mean FY1 EPS of ${fmtEps(m)} is under 0.10 in absolute terms, so the range is not meaningful.`);
    }
    return {v: h.need("risk.est_dispersion"), tag: "E", period: h.v("periods.FY1.label") || "FY1", key: "FY1"};
  },
  n_estimates(h) { return {v: h.need("periods.FY1.eps_n"), tag: "E", period: h.v("periods.FY1.label") || "FY1", key: "FY1"}; },
  stage(h) {
    const s = h.need("stage");
    return {text: s === "clinical" ? "Clinical" : "Commercial", tone: s === "clinical" ? "clinical" : "neutral"};
  },
  lead_phase(h) {
    const t = String(h.need("healthcare.lead_phase"));
    return {text: t, tone: t === "Marketed" ? "neutral" : "clinical"};
  },
  major_products(h) { return {v: h.need("healthcare.major_products"), tag: "A", period: fy0Label(h), key: "FY0"}; },
  loe_share_5y(h) { return {v: h.need("healthcare.loe_share_5y")}; },
  loe_unpriced_5y(h) { return {v: h.need("healthcare.loe_unpriced_5y")}; },
  top_product_share(h) { return {v: h.need("healthcare.top_product_share"), tag: "A", period: fy0Label(h), key: "FY0"}; },
  trial_concentration(h) { return {v: h.need("healthcare.trial_concentration")}; },
  late_trials(h) { return {v: h.need("healthcare.late_trials")}; },
  revenue_per_late_trial(h) {
    return {v: h.money(h.need("healthcare.revenue_per_late_trial_usd_m")), tag: "A", period: fy0Label(h), key: "FY0"};
  },
  catalysts_12m(h) { return {v: h.need("healthcare.catalysts_12m")}; },
  pipeline_ps(h) { return {v: h.need("model.pipeline_per_share"), tag: "M"}; },
};

const MCAP_DEPENDANTS = new Set(["market_cap", "ev", "price_to_sales", "fcf_yield", "price_to_book",
  "mcap_to_cash", "cash_to_mcap", "ev_revenue", "ev_ebitda", "ev_per_late_trial", "pipeline_to_ev"]);
const CONVERTED_COLS = new Set(["revenue", "net_debt", "ev", "revenue_per_late_trial", "ev_per_late_trial"]);

function thinPeriod(flag, rec) {
  const m = /(FY[123])\b/.exec(flag.field || "");
  if (m) return m[1];
  const p = flag.params && flag.params.period;
  if (/^FY[123]$/.test(p || "")) return p;
  for (const k of ["FY1", "FY2", "FY3"]) if (p && get(rec, `periods.${k}.label`) === p) return k;
  return null;
}

/** Whether a record flag (2.5) touches a cell (section 8 "Where"). */
export function flagTouches(flag, colId, key, rec = null) {
  const fwd = key === "NTM" || key === "FY1" || key === "FY2";
  switch (flag && flag.code) {
    case "stale_price": return colId === "price";
    case "stale_consensus":
      return (colId === "pe" && fwd) || colId === "peg" || (colId === "eps_growth" && fwd) ||
        colId === "eps_cagr" || colId === "est_dispersion" || colId === "n_estimates";
    case "stale_balance_sheet":
      return ["ev", "net_debt", "price_to_book", "cash_to_mcap", "mcap_to_cash", "roic"].includes(colId);
    case "stale_fiscal_year": return key === "FY0";
    case "fx_converted": return CONVERTED_COLS.has(colId);
    case "currency_mismatch": return CONVERTED_COLS.has(colId);
    case "fiscal_year_end": return key === "FY0" || key === "FY1" || key === "FY2";
    case "includes_minorities": {
      const eq = /equity/.test(flag.field || "") || get(flag, "params.line") === "equity";
      if (eq) return colId === "price_to_book" || colId === "roic";
      return (colId === "pe" && (key === "FY0" || key === "LTM")) || colId === "net_margin";
    }
    case "market_cap_diluted_route":
    case "cover_count_exception": return colId === "market_cap";
    case "stale_shares":
    case "market_cap_disagreement":
      return MCAP_DEPENDANTS.has(colId) || (colId === "pe" && (key === "FY0" || key === "LTM"));
    case "derived_operating_income":
      return ["operating_margin", "ebitda_margin", "ev_ebitda", "net_debt_ebitda", "roic"].includes(colId);
    case "thin_estimates": {
      const per = thinPeriod(flag, rec);
      if (per === "FY3") return colId === "peg" || colId === "eps_cagr";
      if (per === "FY2") return (colId === "eps_growth" && fwd) || (colId === "pe" && key === "FY2");
      if (per === "FY1") return colId === "pe" && key === "FY1";
      return false;
    }
    case "estimate_range_wide": return colId === "est_dispersion" || (colId === "pe" && fwd);
    case "eps_sign_change": return (colId === "pe" && fwd) || colId === "peg";
    case "guidance_fx_unstated": return (colId === "revenue_growth" || colId === "ev_revenue") && key === "FY1";
    case "burn_flattered": return colId === "runway_months";
    default: return false;
  }
}

const DERIVED_MARK_COLS = ["operating_margin", "ebitda_margin", "ev_ebitda", "net_debt_ebitda", "roic"];

/**
 * `flagMarks(flag, colId, key, rec)` (12.7): whether a flag bears on the value printed in a cell.
 * Only this draws a marker (`cell.marks`, `cell.amber`, `cell.red`, `cell.flagLines`).
 * `flagTouches` stays the wider test the logic reads through `cell.flags`. `flag` is
 * `{code, ...}` or a bare code; `key` is the cell's resolved period key.
 */
export function flagMarks(flag, colId, key, rec = null) {
  const f = typeof flag === "string" ? {code: flag, params: {}} : flag;
  switch (f && f.code) {
    // A property of the row, or stated by the cell's own reason: listed in the detail panel.
    case "stale_fiscal_year": case "fiscal_year_end": case "source_failed": case "fx_converted":
    case "ifrs_filer": case "non_sec_filer": case "market_cap_diluted_route": case "cover_count_exception":
    case "no_tagged_addbacks": case "no_consensus": case "eps_sign_change":
      return false;
    case "stale_shares": case "market_cap_disagreement": return colId === "market_cap";
    case "estimate_range_wide": return colId === "est_dispersion";
    case "derived_operating_income": return DERIVED_MARK_COLS.includes(colId);
    // A client flag: the cell's own computation raised it, and EBITDA growth raises it too.
    case "derived_no_addback": return DERIVED_MARK_COLS.includes(colId) || colId === "ebitda_growth";
    case "burn_flattered": return colId === "runway_months";
    case "calc_failed": return true;
    default: return flagTouches(f, colId, key, rec);
  }
}

function sevOf(flag) {
  const code = typeof flag === "string" ? flag : flag && flag.code;
  const s = typeof flag === "object" && flag && flag.severity;
  return s || FLAG_SEVERITY[code] || "info";
}

function guidanceQuote(rec) {
  const g = get(rec, "periods.FY1.guidance");
  if (!g || !g.text) return null;
  // A filed headline often arrives framed by dashes ("\u2014 Raising guidance \u2014"). The frame is
  // decoration, not wording, so it is trimmed; the words between stay verbatim.
  let text = String(g.text).replace(/^[\s\u2013\u2014-]+|[\s\u2013\u2014-]+$/g, "");
  if (!text) return null;
  if (text.length > 240) {
    const cut = text.slice(0, 239);
    const sp = cut.lastIndexOf(" ");
    text = (sp > 0 ? cut.slice(0, sp) : cut) + ELLIPSIS;
  }
  return `${rec.name || rec.ticker} guidance, ${fmtDate(g.as_of)}: “${text}”`;
}

function blankCell(rec) {
  return {v: null, status: "ok", text: "", reason: null, tag: null, period: null, tagDiffers: false,
          unit: null, flags: [], marks: [], ticker: rec ? rec.ticker || null : null, brief: null, flagLines: [],
          amber: false, red: false, periodKey: null};
}

/**
 * `cell(company, colId, ctx) -> Cell`, ctx = {basis, currency, earnings, fx, fy0Label}.
 * An optional `ctx.cache` (a Map) memoises cells per ticker and column for that ctx.
 */
export function cell(company, colId, ctx) {
  const cache = ctx && ctx.cache;
  const key = cache ? `${company && company.ticker}|${colId}` : null;
  if (cache && cache.has(key)) return cache.get(key);
  const out = computeCell(company, colId, ctx || {});
  if (cache) cache.set(key, out);
  return out;
}

function computeCell(rec, colId, ctx) {
  const out = blankCell(rec);
  if (!rec) return {...out, status: "na", text: NULL, reason: NA_TEXT.no_free_data};
  if (colId === "company") return {...out, text: rec.name || rec.ticker || NULL};
  if (colId === "ticker") {
    // `flags` lists every amber or red code of the record for the logic. The marker after a ticker
    // is a row matter (`RowView.tickerFlags`, 12.7), so outside a row only a failed calculation marks.
    const fl = (rec.flags || []).filter((f) => f && (sevOf(f) === "amber" || sevOf(f) === "red"));
    const failed = rec.error ? [flagText({code: "calc_failed", params: {message: rec.error}}).text] : [];
    return {...out, text: rec.ticker, flags: uniq(fl.map((f) => f.code)), marks: rec.error ? ["calc_failed"] : [],
            flagLines: failed, amber: false, red: !!rec.error};
  }
  const c = COLUMN_BY_ID[colId];
  if (!c || !COMPUTE[colId]) return {...out, status: "na", text: NULL, reason: NO_SOURCE_TEXT, brief: lcfirst(stripStop(NO_SOURCE_TEXT))};
  if (rec.error) {
    return {...out, status: "err", text: NULL, reason: CALC_FAILED_CELL, brief: "calculation failed",
            flags: ["calc_failed"], marks: ["calc_failed"],
            flagLines: [flagText({code: "calc_failed", params: {message: rec.error}}).text], red: true};
  }
  const h = helper(rec, ctx);
  const b = resolveBasis(colId, ctx.basis || "NTM");
  const clientFlags = [];
  let r = null;
  try {
    r = COMPUTE[colId](h, b, clientFlags) || {};
    out.status = "ok";
    if (r.v !== undefined) out.v = isNum(r.v) ? r.v : null;
    if (r.text !== undefined) out.text = r.text;
    if (r.tone) out.tone = r.tone;
    if (r.series) out.series = r.series;
    out.tag = r.tag !== undefined ? r.tag : (c.prov === "M" ? "M" : null);
    out.period = r.period || null;
    out.periodKey = r.key || b;
    out.tagDiffers = !!r.tagDiffers;
    if (isNumericCol(c) && out.v === null) {
      out.status = "na"; out.reason = NA_TEXT.no_free_data;
    }
  } catch (e) {
    out.periodKey = b;
    if (e instanceof Missing) {
      const code = e.code || naCode(rec, e.path) || "no_free_data";
      if (code === "non_positive_base") {
        out.status = "nm"; out.reason = NA_TEXT.non_positive_base;
      } else {
        out.status = "na"; out.reason = NA_TEXT[code] || NA_TEXT.no_free_data; out.naCode = code;
      }
    } else if (e instanceof NotMeaningful) {
      out.status = "nm"; out.reason = e.reason; out.brief = e.brief;
    } else if (e instanceof NoBurn) {
      out.status = "nb"; out.reason = NA_TEXT.not_burning; out.naCode = "not_burning";
    } else {
      out.status = "err"; out.reason = CALC_FAILED_CELL; out.error = String(e && e.message || e);
    }
    out.v = null;
    out.tag = null;
  }
  if (!out.brief && out.reason) out.brief = lcfirst(stripStop(out.reason));
  // Flags that touch this cell feed the logic (`flags`). The ones that bear on the printed value
  // draw the marker (`marks`, 12.7): amber, red and the tooltip lines follow them alone.
  const touching = (rec.flags || []).filter((f) => f && flagTouches(f, colId, out.periodKey, rec));
  const codes = touching.map((f) => f.code).concat(clientFlags);
  out.flags = uniq(codes);
  const marking = touching.filter((f) => flagMarks(f, colId, out.periodKey, rec));
  const clientMarks = clientFlags.filter((f) => flagMarks(f, colId, out.periodKey, rec));
  out.marks = uniq(marking.map((f) => f.code).concat(clientMarks));
  const lines = marking.map((f) => flagText(f, rec).text).concat(clientMarks.map((f) => flagText(f, rec).text));
  if (ctx.currency === "REPORTED" && (colId === "market_cap" || colId === "ev") && out.status === "ok") {
    lines.push(`USD market value translated at the ECB rate of ${fmtDate(get(ctx, "fx.as_of"))}.`);
  }
  out.flagLines = uniq(lines);
  out.amber = marking.some((f) => sevOf(f) === "amber") || clientMarks.some((f) => sevOf(f) === "amber");
  out.red = marking.some((f) => sevOf(f) === "red");
  if (out.tag === "G") out.quote = guidanceQuote(rec);
  if (ctx.currency === "REPORTED" && isMoneyCol(c)) out.unit = h.cur;
  if (out.status !== "ok" || isNumericCol(c)) out.text = fmtCell(out, c);
  return out;
}

/** `fmtCell(cell, col)`: the column format of 4.3 applied to `cell.v`. */
export function fmtCell(cellObj, colDef) {
  const c = typeof colDef === "string" ? COLUMN_BY_ID[colDef] : colDef;
  if (!cellObj) return NULL;
  if (cellObj.status === "nm") return "n.m.";
  if (cellObj.status === "nb") return "no burn";
  if (cellObj.status === "na" || cellObj.status === "err") return NULL;
  if (!c || !isNumericCol(c)) return cellObj.text || "";
  const v = cellObj.v;
  if (!isNum(v)) return NULL;
  const s = {signed: !!c.signed};
  switch (c.fmt) {
    case "mult1": return fmtNumber(v, 1, s);
    case "mult2": return fmtNumber(v, 2, s);
    case "pct1": return fmtNumber(v * 100, 1, s);
    case "pct0": return fmtNumber(v * 100, 0, s);
    case "money1": return fmtNumber(v / 1000, 1, s);
    case "money0m": return fmtNumber(v, 0, s);
    case "price2": return fmtNumber(v, 2, s);
    case "num2": return fmtNumber(v, 2, s);
    case "int": return fmtNumber(v, 0, s);
    default: return cellObj.text || "";
  }
}

/** The cell's number in the header's unit (money in bn or m, percents times 100), unrounded. */
export function displayValue(cellObj, colDef) {
  const c = typeof colDef === "string" ? COLUMN_BY_ID[colDef] : colDef;
  if (!cellObj || cellObj.status !== "ok" || !isNum(cellObj.v) || !c) return null;
  switch (c.fmt) {
    case "pct1": case "pct0": return cellObj.v * 100;
    case "money1": return cellObj.v / 1000;
    default: return cellObj.v;
  }
}

/** Prose value of a cell for sentences: "16.2×", "8.6%", "$260.0bn", "77 months". */
export function proseValue(colId, v, ctx = {}, rec = null) {
  const c = COLUMN_BY_ID[colId];
  if (!c || !isNum(v)) return NULL;
  switch (c.fmt) {
    case "mult1": case "mult2": return fmtNumber(v, c.fmt === "mult2" ? 2 : 1) + TIMES;
    case "pct1": return fmtNumber(v * 100, 1) + "%";
    case "pct0": return fmtNumber(v * 100, 0) + "%";
    case "money1": case "money0m": {
      const cur = displayCurrency(rec, ctx);
      const rate = rateFor(cur, ctx);
      return rate === null ? NULL : fmtMoneyProse(v * rate, cur, ctx.fx);
    }
    case "price2": return "$" + fmtNumber(v, 2);
    case "int": return fmtNumber(v, 0);
    default: return fmtNumber(v, 2);
  }
}

// ---------------------------------------------------------------------------------------------
// Rows, labels and periods shared by the analysis functions
// ---------------------------------------------------------------------------------------------

function asRec(x) { return x && x.record ? x.record : x; }
function asRow(x) {
  if (!x) return null;
  if (x.record) return x;
  return {ticker: x.ticker, record: x, isFocal: false, excluded: false};
}
function shortFy(label) {
  const m = /^FY(\d{2})(\d{2})$/.exec(label || "");
  return m ? `FY${m[2]}` : (label || "");
}
/** Short word for a resolved basis: "NTM", "LTM", "FY25", "FY26". */
export function basisWord(basis, ctx = {}) {
  if (basis === "NTM" || basis === "LTM") return basis;
  if (basis === "FY0") return shortFy(ctx.fy0Label) || "FY0";
  if (basis === "FY1") return shortFy(ctx.fy1Label) || "FY1";
  if (basis === "FY2") return shortFy(ctx.fy2Label) || "FY2";
  return basis || "";
}
/** Label of a metric with its basis when the column has more than one: "P/E NTM", "EV/EBITDA". */
export function metricLabel(colId, basis, ctx = {}) {
  const c = COLUMN_BY_ID[colId];
  if (!c) return String(colId);
  const b = resolveBasis(colId, basis);
  return c.bases.length > 1 ? `${c.label} ${basisWord(b, ctx)}` : c.label;
}
/** Basis chip text (4.2): "NTM E", "FY26 E", "FY25 A", "LTM A", "FY26 G"; null for spot columns. */
export function basisChipText(colId, basis, ctx = {}, withEarnings = false) {
  const c = COLUMN_BY_ID[colId];
  if (!c || c.bases[0] === "-") return null;
  const b = resolveBasis(colId, basis);
  let tag = "A";
  if (b === "NTM" || ((b === "FY1" || b === "FY2") && colId !== "revenue_growth" && colId !== "ev_revenue")) tag = "E";
  if (b === "FY1" && (colId === "revenue_growth" || colId === "ev_revenue")) tag = "G";
  if (colId === "est_dispersion" || colId === "n_estimates") tag = "E";
  const word = basisWord(b, ctx);
  if (withEarnings && c.earnings) return `${word} ${tag === "E" ? "street" : "GAAP/IFRS"} ${tag}`;
  return `${word} ${tag}`;
}

// ---------------------------------------------------------------------------------------------
// 3.5 Metric availability and the primary metric
// ---------------------------------------------------------------------------------------------

const PRIMARY_CANDIDATES = {
  profitable: ["pe", "ev_ebitda", "ev_revenue", "price_to_sales"],
  loss_making: ["ev_revenue", "price_to_sales", "mcap_to_cash"],
  sub_scale: ["mcap_to_cash"],
  clinical: ["mcap_to_cash"],
};
export function primaryCandidates(focal) { return (PRIMARY_CANDIDATES[companyType(focal)] || []).slice(); }

export function metricAvailability(focal, peers, colId, ctx) {
  const prem = PREMIUM_METRICS.includes(colId);
  const recs = (peers || []).map(asRec).filter(Boolean);
  const n = recs.filter((r) => cell(r, colId, ctx).status === "ok").length;
  const fc = cell(focal, colId, ctx);
  const T = focal && focal.ticker;
  if (fc.status !== "ok") {
    const why = fc.status === "nm" ? `Not meaningful for ${T}: ${fc.reason}` : `No value for ${T}: ${fc.reason}`;
    return {enabled: false, n, premium: prem, reason: why};
  }
  if (n === 0) return {enabled: false, n, premium: prem, reason: "No peer has a value"};
  if (n === 1) return {enabled: false, n, premium: prem, reason: "Only 1 peer has a value"};
  return {enabled: true, n, premium: prem, reason: null};
}

function lowConfidenceText(k, colId) {
  return `Only ${k} peers have a ${proseLabel(colId)}. A median of fewer than 5 is not a reliable reference, so no premium or discount is stated.`;
}

export function primaryMetric(focal, peers, ctx, override = null) {
  const T = focal.ticker;
  const type = companyType(focal);
  const recs = (peers || []).map(asRec).filter(Boolean);
  const n = recs.length;
  const info = (colId) => {
    const fc = cell(focal, colId, ctx);
    const k = recs.filter((r) => cell(r, colId, ctx).status === "ok").length;
    return {colId, fc, k, focalOk: fc.status === "ok"};
  };
  const lbl = (colId) => metricLabel(colId, ctx.basis, ctx);
  const out = (i, state, reasonText, fallbackFrom = null, extra = {}) => ({
    colId: i ? i.colId : null, basis: i ? resolveBasis(i.colId, ctx.basis) : null, state, reasonText,
    fallbackFrom, k: i ? i.k : 0, n, label: i ? lbl(i.colId) : null, override: false, ...extra});
  const unavailable = (i) => {
    if (!i.focalOk) {
      return i.fc.status === "nm" ? `not meaningful for ${T}: ${i.fc.brief}` : `no value for ${T}: ${i.fc.brief}`;
    }
    if (i.k === 0) return "no peer has a value";
    return `only ${i.k} of ${n} ${plural(i.k, "peer has", "peers have")} a value`;
  };
  if (override && PREMIUM_METRICS.includes(override)) {
    const i = info(override);
    if (i.focalOk && i.k >= 2) {
      const state = i.k >= MIN_PEERS ? "ok" : "low_confidence";
      return out(i, state, `${lbl(override)} is primary: chosen by you. The dot plot's "Use as primary" sets it; "Reset primary" in its menu restores the default.`, null, {override: true});
    }
  }
  const cands = PRIMARY_CANDIDATES[type] || [];
  const infos = cands.map(info);
  const okIdx = infos.findIndex((i) => i.focalOk && i.k >= MIN_PEERS);
  if (okIdx >= 0) {
    const i = infos[okIdx];
    let text;
    if (type === "sub_scale" || type === "clinical") {
      text = `${lbl(i.colId)} is primary: ${T} is ${TYPE_LABEL[type]}, so revenue and earnings multiples are not used, and ${i.k} of ${n} peers have a value.`;
    } else if (okIdx === 0) {
      text = `${lbl(i.colId)} is primary: ${T} is ${TYPE_LABEL[type]} and ${i.k} of ${n} peers have a value.`;
    } else {
      text = `${lbl(i.colId)} is primary: ${lbl(infos[0].colId)} is not available (${unavailable(infos[0])}), and ${i.k} of ${n} peers have a value.`;
    }
    return out(i, "ok", text, okIdx > 0 ? infos[0].colId : null);
  }
  const lcIdx = infos.findIndex((i) => i.focalOk && i.k >= 2);
  if (lcIdx >= 0) {
    const i = infos[lcIdx];
    return out(i, "low_confidence", lowConfidenceText(i.k, i.colId), lcIdx > 0 ? infos[0].colId : null);
  }
  const tfIdx = infos.findIndex((i) => i.focalOk);
  if (tfIdx >= 0) {
    const i = infos[tfIdx];
    const parts = headlineParts(focal, i.colId, ctx, []);
    const text = `${T} trades at ${parts.v} ${parts.metric} (${parts.period}). ${i.k === 1 ? "One peer has" : "No peer has"} a value, so there is no comparison.`;
    return out(i, "too_few", text, tfIdx > 0 ? infos[0].colId : null);
  }
  return {colId: null, basis: null, state: "no_multiple", k: 0, n, label: null, override: false,
          reasonText: `No valuation multiple has both a value for ${T} and 2 or more peer values.`,
          fallbackFrom: null, firstCandidate: cands[0] || null};
}

/** Pieces of a headline for the focal's cell in a column: value, prose metric, period. */
function headlineParts(focal, colId, ctx, peerCells) {
  const fc = cell(focal, colId, ctx);
  const v = proseValue(colId, fc.v, ctx, focal);
  let period = fc.period || basisWord(resolveBasis(colId, ctx.basis), ctx) || "latest";
  if (colId === "price_to_book" || colId === "mcap_to_cash") period = fc.period || "latest balance sheet";
  const mixed = (peerCells || []).some((c) => c && c.status === "ok" && c.tagDiffers) || fc.tagDiffers;
  if (mixed && resolveBasis(colId, ctx.basis) === "LTM") period += ", peers mixed LTM and FY";
  return {v, metric: proseLabel(colId), period, cell: fc};
}

// ---------------------------------------------------------------------------------------------
// 3.6 Peer relevance and the default set
// ---------------------------------------------------------------------------------------------

function cosine(a, b) {
  const keys = uniq(Object.keys(a).concat(Object.keys(b)));
  let dot = 0, na = 0, nb = 0;
  for (const k of keys) {
    const x = isNum(a[k]) ? a[k] : 0, y = isNum(b[k]) ? b[k] : 0;
    dot += x * y; na += x * x; nb += y * y;
  }
  return na > 0 && nb > 0 ? dot / Math.sqrt(na * nb) : 0;
}
function jaccard(a, b) {
  const A = new Set(a), B = new Set(b);
  const inter = [...A].filter((x) => B.has(x)).length;
  const uni = new Set([...A, ...B]).size;
  return uni ? inter / uni : 0;
}
function hasAreas(r) { return r && r.areas && typeof r.areas === "object" && Object.values(r.areas).some((v) => isNum(v) && v > 0); }
function hasThemes(r) { return r && Array.isArray(r.themes) && r.themes.length > 0; }
function opMarginOf(rec) {
  const o = numAt(rec, "periods.FY0.operating_income_usd_m"), r = numAt(rec, "periods.FY0.revenue_usd_m");
  if (o === null || r === null || r <= 0) return null;
  return clamp(o / r, -1, 1);
}
const COMPONENT_LABEL = {subsector: "Subsector", model: "Business model", scale: "Scale",
  profitability: "Profitability or stage", growth: "Growth", geography: "Geography"};
export const RELEVANCE_COMPONENTS = Object.keys(RELEVANCE_WEIGHTS).map((id) => ({id, label: COMPONENT_LABEL[id], weight: RELEVANCE_WEIGHTS[id]}));

export function relevance(focal, peer) {
  const comps = {}, missing = [];
  const aff = engineAffinity(focal && focal.engine, peer && peer.engine);
  const focus = [];
  if (hasAreas(focal) && hasAreas(peer)) focus.push(cosine(focal.areas, peer.areas));
  if (hasThemes(focal) && hasThemes(peer)) focus.push(jaccard(focal.themes, peer.themes));
  comps.subsector = focus.length ? 0.6 * aff + 0.4 * (focus.reduce((s, v) => s + v, 0) / focus.length) : aff;
  const ga = typeGroup(companyType(focal)), gb = typeGroup(companyType(peer));
  comps.model = ga && ga === gb ? 1.0 : (focal.stage && focal.stage === peer.stage ? 0.5 : 0);
  const ma = numAt(focal, "market.market_cap_usd_m"), mb = numAt(peer, "market.market_cap_usd_m");
  if (ma !== null && mb !== null && ma > 0 && mb > 0) {
    comps.scale = 1 - Math.min(1, Math.abs(Math.log10(ma) - Math.log10(mb)) / 1.5);
  } else missing.push({id: "scale", reason: "no market cap on file"});
  if (focal.stage === "commercial" && peer.stage === "commercial") {
    const a = opMarginOf(focal), b = opMarginOf(peer);
    if (a !== null && b !== null) comps.profitability = 1 - Math.min(1, Math.abs(a - b) / 0.40);
    else missing.push({id: "profitability", reason: "no operating margin on file"});
  } else if (focal.stage === "clinical" && peer.stage === "clinical") {
    const a = phaseRank(get(focal, "healthcare.lead_phase")), b = phaseRank(get(peer, "healthcare.lead_phase"));
    if (a !== null && b !== null) comps.profitability = 1 - Math.abs(a - b) / 4;
    else missing.push({id: "profitability", reason: "no lead phase on file"});
  } else {
    comps.profitability = 0;
  }
  const g1 = numAt(focal, "growth.revenue_fy"), g2 = numAt(peer, "growth.revenue_fy");
  if (g1 !== null && g2 !== null) {
    comps.growth = 1 - Math.min(1, Math.abs(clamp(g1, -0.5, 1.0) - clamp(g2, -0.5, 1.0)) / 0.30);
  } else missing.push({id: "growth", reason: "no revenue growth on file"});
  if (focal.region == null || peer.region == null) {
    missing.push({id: "geography", reason: "region not known"});
  } else {
    comps.geography = focal.country && focal.country === peer.country ? 1.0 : (focal.region === peer.region ? 0.7 : 0.4);
  }
  let sw = 0, s = 0;
  for (const [k, w] of Object.entries(RELEVANCE_WEIGHTS)) {
    if (isNum(comps[k])) { sw += w; s += w * comps[k]; }
  }
  const score = sw > 0 ? Math.round(100 * s / sw) : 0;
  const level = score >= 70 ? "high" : score >= 50 ? "medium" : "low";
  return {score, level, components: comps, missing};
}

export function defaultPeers(focal, universe) {
  const cands = (universe || []).filter((r) => r && r.ticker && r.ticker !== focal.ticker && !r.error);
  const scores = {};
  for (const r of cands) scores[r.ticker] = relevance(focal, r).score;
  const mc = (r) => numAt(r, "market.market_cap_usd_m") || 0;
  const rank = (a, b) => (scores[b.ticker] - scores[a.ticker]) || (mc(b) - mc(a)) || a.ticker.localeCompare(b.ticker);
  const tickers = [], reasons = {}, pools = {};
  // 12.8: a cohort of WHOLE_COHORT_MAX other companies or fewer is the set, whole: no relevance
  // floor and no cap. A larger cohort keeps the MAX_DEFAULT_PEERS most relevant at or above the floor.
  const cohort = cands.filter((r) => r.engine === focal.engine && r.stage === focal.stage).sort(rank);
  const whole = cohort.length <= WHOLE_COHORT_MAX;
  const poolA = whole ? cohort
    : cohort.filter((r) => scores[r.ticker] >= MIN_DEFAULT_RELEVANCE).slice(0, MAX_DEFAULT_PEERS);
  for (const r of poolA) {
    tickers.push(r.ticker); pools[r.ticker] = "A";
    reasons[r.ticker] = `Same subsector and stage, relevance ${scores[r.ticker]}` +
      (scores[r.ticker] < MIN_DEFAULT_RELEVANCE ? `, under the usual floor of ${MIN_DEFAULT_RELEVANCE}` : "");
  }
  let padded = false;
  if (tickers.length < 5) {
    const poolB = cands.filter((r) => r.engine === focal.engine && r.stage !== focal.stage).sort(rank);
    for (const r of poolB) {
      if (tickers.length >= 5) break;
      tickers.push(r.ticker); pools[r.ticker] = "B";
      reasons[r.ticker] = `Added to reach five peers: same subsector, ${r.stage || "other"} stage, relevance ${scores[r.ticker]}`;
      if (scores[r.ticker] < MIN_DEFAULT_RELEVANCE) padded = true;
    }
  }
  if (tickers.length < 5) {
    const poolC = cands.filter((r) => r.engine !== focal.engine && engineAffinity(focal.engine, r.engine) >= 0.5 &&
      r.stage === focal.stage).sort(rank);
    for (const r of poolC) {
      if (tickers.length >= 5) break;
      tickers.push(r.ticker); pools[r.ticker] = "C";
      reasons[r.ticker] = `Added to reach five peers: adjacent subsector, relevance ${scores[r.ticker]}`;
      if (scores[r.ticker] < MIN_DEFAULT_RELEVANCE) padded = true;
    }
  }
  const warning = tickers.length < 5 ? "too_few" : (padded ? "padded" : null);
  return {tickers, reasons, pools, warning, scores, whole, cohortSize: cohort.length};
}

/** Pool C candidates for a focal (adjacent engine, same stage), best first. */
export function adjacentCandidates(focal, universe) {
  return (universe || []).filter((r) => r && r.ticker !== focal.ticker && !r.error && r.engine !== focal.engine &&
    engineAffinity(focal.engine, r.engine) >= 0.5 && r.stage === focal.stage)
    .map((r) => ({ticker: r.ticker, score: relevance(focal, r).score, mc: numAt(r, "market.market_cap_usd_m") || 0}))
    .sort((a, b) => (b.score - a.score) || (b.mc - a.mc) || a.ticker.localeCompare(b.ticker));
}

/**
 * `setLabel(state, info) -> {full, short, noun, scopeChip}`. `info` carries what the label needs:
 * {kind: "system" | "saved" | "edited", engineLabel, stage, n, poolsUsed: {B, C}, savedName, subgroup}.
 */
export function setLabel(state, info = {}) {
  const n = info.n ?? 0;
  const el = info.engineLabel || "Peers";
  let full, short, noun;
  if (info.kind === "edited") {
    full = `Custom, ${n}`; short = full; noun = "selected peers";
  } else if (info.kind === "saved") {
    const name = info.savedName || "";
    full = `'${name}', ${n}`;
    short = `'${name.length > 16 ? name.slice(0, 16) + ELLIPSIS : name}', ${n}`;
    noun = `peers in '${name}'`;
  } else if (info.poolsUsed && (info.poolsUsed.B || info.poolsUsed.C)) {
    full = info.poolsUsed.C ? `${el} and adjacent, ${n}` : `${el}, mixed stages, ${n}`;
    short = `${el}+, ${n}`;
    noun = `${el.toLowerCase()} and adjacent peers`;
  } else {
    full = `${el}, ${info.stage || "commercial"}, ${n}`;
    short = `${el}, ${n}`;
    noun = `${info.stage === "clinical" ? "clinical " : ""}${el.toLowerCase()} peers`;
  }
  let scopeChip = null;
  if (info.subgroup) { noun = `${info.subgroup} peers`; scopeChip = `Statistics over: ${info.subgroup}`; }
  return {full, short, noun, scopeChip};
}

export function mixedModels(focal, included) {
  const recs = (included || []).map(asRec).filter(Boolean);
  if (!recs.length) return null;
  const fg = typeGroup(companyType(focal));
  const groups = recs.map((r) => typeGroup(companyType(r)));
  const all = [fg].concat(groups);
  const both = all.includes("profitable") && all.includes("pre-scale");
  const same = groups.filter((g) => g === fg).length;
  if (!both && same >= recs.length / 2) return null;
  const counts = {};
  for (const g of groups) if (g !== fg) counts[g] = (counts[g] || 0) + 1;
  const other = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  if (!other) return null;
  return {focalType: fg, otherType: other[0], k: other[1], n: recs.length};
}

// ---------------------------------------------------------------------------------------------
// 3.7 Peer statistics
// ---------------------------------------------------------------------------------------------

const EMPTY_SUMMARY = {n: 0, mean: null, median: null, p25: null, p75: null, iqr: null, min: null, max: null};

/**
 * `peerStats(rows, colId, ctx, {outliers, group, focalCurrency})`: over included peers only
 * (never the focal, excluded rows or rows outside `group`); with outliers "exclude", mild and
 * extreme values are removed for this column. Filters never change it.
 */
export function peerStats(rows, colId, ctx, opts = {}) {
  const o = {...((ctx && ctx.stats) || {}), ...(opts || {})};
  const mode = o.outliers || "include";
  const group = o.group ? new Set(o.group) : null;
  const c = COLUMN_BY_ID[colId];
  let nm = 0, na = 0;
  const items = [];
  const currencies = new Set();
  for (const raw of rows || []) {
    const r = asRow(raw);
    if (!r || r.isFocal || r.excluded || r.inSet === false) continue;
    if (group && !group.has(r.ticker)) continue;
    const cc = cell(r.record, colId, ctx);
    if (cc.status === "ok" && isNum(cc.v)) {
      items.push({ticker: r.ticker, v: cc.v});
      currencies.add(displayCurrency(r.record, ctx));
    } else if (cc.status === "nm" || cc.status === "nb") nm++;
    else na++;
  }
  let mixedCurrency = false;
  if (ctx && ctx.currency === "REPORTED" && isMoneyCol(c)) {
    const fcur = o.focalCurrency || null;
    if (currencies.size > 1 || (fcur && currencies.size === 1 && !currencies.has(fcur))) mixedCurrency = true;
  }
  const all = items.map((i) => i.v);
  const f1 = fences(all, TUKEY_K), f3 = fences(all, TUKEY_EXTREME_K);
  const mild = [], extreme = [];
  if (f1 && f3) {
    for (const i of items) {
      if (i.v < f3.lo || i.v > f3.hi) extreme.push(i.ticker);
      else if (i.v < f1.lo || i.v > f1.hi) mild.push(i.ticker);
    }
  }
  let kept = items;
  if (mode === "exclude") kept = items.filter((i) => !mild.includes(i.ticker) && !extreme.includes(i.ticker));
  if (mixedCurrency) kept = [];
  const values = kept.map((i) => i.v);
  const s = summarize(values) || EMPTY_SUMMARY;
  return {...s, nm, na, outliers: {mild, extreme}, values, tickers: kept.map((i) => i.ticker),
          fences: f1 ? {mild: f1, extreme: f3} : null, mixedCurrency, all};
}

// ---------------------------------------------------------------------------------------------
// Dot plot (5.1) geometry model
// ---------------------------------------------------------------------------------------------

function padDomain(lo, hi, log) {
  if (!isNum(lo) || !isNum(hi)) return null;
  if (log) {
    const a = Math.log10(lo), b = Math.log10(hi);
    const span = b - a || 1;
    return [10 ** (a - 0.08 * span), 10 ** (b + 0.08 * span)];
  }
  let span = hi - lo;
  if (span === 0) span = Math.abs(hi) || 1;
  return [lo - 0.08 * span, hi + 0.08 * span];
}

/**
 * `dotplotModel(focal, rows, colId, ctx, opts)`: lanes of peer points with the focal, the domain
 * rule of 5.1 (min to max of plotted values, focal included, padded 8 %; with 5 or more peer
 * values, Tukey-extreme values are left out of the domain and clamped to its edge with a label).
 * opts: {lanes: [{id, label, rows}], isPrimary, target, subtitle}.
 */
export function dotplotModel(focal, rows, colId, ctx, opts = {}) {
  const T = focal.ticker;
  const c = COLUMN_BY_ID[colId];
  const base = {colId: colId || null, label: colId ? metricLabel(colId, ctx.basis, ctx) : "", unit: c ? unitText(c, ctx) : "",
    isPrimary: !!opts.isPrimary, premiumEligible: PREMIUM_METRICS.includes(colId), scale: "linear",
    domain: null, extent: null, lanes: [], notPlotted: {nm: 0, na: 0}, target: opts.target || null,
    description: "", disabledReason: null, subtitle: opts.subtitle || ""};
  if (!c) return {...base, disabledReason: "No metric has a value for this company and its peers."};
  const laneDefs = opts.lanes && opts.lanes.length ? opts.lanes : [{id: "set", label: "Peer set", rows}];
  const fc = cell(focal, colId, ctx);
  const lanes = [];
  const allPlotted = [];
  let peerAll = [];
  laneDefs.forEach((ld, li) => {
    const lrows = (ld.rows || []).map(asRow).filter((r) => r && !r.isFocal && r.inSet !== false);
    const st = peerStats(lrows, colId, ctx);
    if (li === 0) peerAll = st.all;
    const points = [];
    for (const r of lrows) {
      const cc = cell(r.record, colId, ctx);
      if (cc.status !== "ok" || !isNum(cc.v)) {
        if (li === 0) { if (cc.status === "na" || cc.status === "err") base.notPlotted.na++; else base.notPlotted.nm++; }
        continue;
      }
      const pp = percentileRank(cc.v, st.values);
      const pv = proseValue(colId, cc.v, ctx, r.record);
      points.push({ticker: r.ticker, v: cc.v, x: cc.v, text: cc.text, isFocal: false, excluded: !!r.excluded,
        outlier: st.outliers.extreme.includes(r.ticker) ? "extreme" : (st.outliers.mild.includes(r.ticker) ? "mild" : null),
        clamped: null, label: null, pct: pp,
        hover: `${r.ticker} ${pv} ${metricLabel(colId, ctx.basis, ctx)}${pp !== null ? `, ${ordinal(Math.round(pp))} percentile` : ""}${r.excluded ? ", excluded" : ""}`,
        announce: `${r.ticker}: ${pv}${pp !== null ? `, ${ordinal(Math.round(pp))} percentile` : ""}`});
      allPlotted.push(cc.v);
    }
    if (fc.status === "ok" && isNum(fc.v)) {
      const fp = percentileRank(fc.v, st.values);
      const fv = proseValue(colId, fc.v, ctx, focal);
      points.push({ticker: T, v: fc.v, x: fc.v, text: fc.text, isFocal: true, excluded: false, outlier: null,
        clamped: null, label: T, pct: fp,
        hover: `${T} ${fv} ${metricLabel(colId, ctx.basis, ctx)}${fp !== null ? `, ${ordinal(Math.round(fp))} percentile` : ""}`,
        announce: `${T}: ${fv}${fp !== null ? `, ${ordinal(Math.round(fp))} percentile` : ""}`});
    }
    lanes.push({id: ld.id, label: ld.label, n: st.n, median: st.median, p25: st.p25, p75: st.p75, points, stats: st});
  });
  if (fc.status === "ok" && isNum(fc.v)) allPlotted.push(fc.v);
  if (!allPlotted.length) {
    return {...base, lanes, disabledReason: `No company in the set has a ${proseLabel(colId)} value.`,
      description: `${metricLabel(colId, ctx.basis, ctx)}: no plotted values.`};
  }
  const f3 = peerAll.length >= 5 ? fences(peerAll, TUKEY_EXTREME_K) : null;
  const inside = f3 ? allPlotted.filter((v) => v >= f3.lo && v <= f3.hi) : allPlotted;
  const ext = inside.length ? [Math.min(...inside), Math.max(...inside)] : [Math.min(...allPlotted), Math.max(...allPlotted)];
  let log = (colId === "market_cap" || colId === "ev") && ext[0] > 0;
  const domain = padDomain(ext[0], ext[1], log);
  for (const lane of lanes) {
    for (const p of lane.points) {
      if (p.v < ext[0]) { p.x = ext[0]; p.clamped = "lo"; p.label = `${p.ticker} ${p.text}`; }
      else if (p.v > ext[1]) { p.x = ext[1]; p.clamped = "hi"; p.label = `${p.ticker} ${p.text}`; }
      else if (p.outlier && !p.isFocal) p.label = p.ticker;
    }
  }
  const l0 = lanes[0];
  const st0 = l0 ? l0.stats : null;
  const fmt = (v) => proseValue(colId, v, ctx, focal);
  const pct = fc.status === "ok" && st0 ? percentileRank(fc.v, st0.values) : null;
  let desc = `${metricLabel(colId, ctx.basis, ctx)} for ${st0 ? st0.n : 0} peers.`;
  if (st0 && st0.n) desc += ` Median ${fmt(st0.median)}, interquartile range ${fmt(st0.p25)} to ${fmt(st0.p75)}.`;
  desc += fc.status === "ok" ? ` ${T} at ${fmt(fc.v)}${pct !== null ? `, ${ordinal(Math.round(pct))} percentile` : ""}.` : ` ${T} has no value: ${fc.brief}.`;
  if (opts.isPrimary) desc = "Primary metric. " + desc;
  for (const lane of lanes) delete lane.stats;
  return {...base, scale: log ? "log" : "linear", domain, extent: ext, lanes, description: desc};
}

/** KPI 5 position strip: the peer IQR, the median and the focal on the dot plot's domain rule. */
export function positionStrip(focal, rows, colId, ctx) {
  const dp = dotplotModel(focal, rows, colId, ctx, {});
  const lane = dp.lanes[0];
  const fp = lane ? lane.points.find((p) => p.isFocal) : null;
  if (!dp.domain || !lane) return null;
  const pct = fp ? fp.pct : null;
  const inside = fp && isNum(lane.p25) && isNum(lane.p75)
    ? (fp.v < lane.p25 ? "below" : fp.v > lane.p75 ? "above" : "inside") : null;
  const fmt = (v) => proseValue(colId, v, ctx, focal);
  const description = fp && inside
    ? `${focal.ticker} at the ${ordinal(Math.round(pct))} percentile, ${inside} the interquartile range of ${fmt(lane.p25)} to ${fmt(lane.p75)}.`
    : `${focal.ticker} has no position on this metric.`;
  return {domain: dp.domain, scale: dp.scale, p25: lane.p25, median: lane.median, p75: lane.p75,
    focal: fp ? fp.x : null, clamped: fp ? fp.clamped : null, description};
}

// ---------------------------------------------------------------------------------------------
// 3.8 Scatter regression and regions
// ---------------------------------------------------------------------------------------------

export const SCATTER_X_OPTIONS = ["revenue_growth", "eps_growth", "ebitda_growth", "revenue_cagr3",
  "operating_margin", "ebitda_margin", "roic", "loe_share_5y", "late_trials"];
export const SCATTER_Y_OPTIONS = ["pe", "ev_ebitda", "ev_revenue", "price_to_sales", "price_to_book",
  "fcf_yield", "peg", "mcap_to_cash", "pt_upside", "ev_per_late_trial", "pipeline_to_ev"];
export const LOG_Y_COLS = ["ev_revenue", "price_to_sales", "mcap_to_cash", "pe", "price_to_book"];
export function defaultScatterX(yCol) {
  if (yCol === "pe") return "eps_growth";
  if (yCol === "ev_revenue" || yCol === "price_to_sales") return "revenue_growth";
  if (yCol === "ev_ebitda") return "ebitda_growth";
  return "revenue_growth";
}
const SHAPES = {pharma: "circle", biotech: "square", cellgene: "triangle"};

export function scatterModel(focal, rows, xCol, yCol, ctx, opts = {}) {
  const o = {...((ctx && ctx.stats) || {}), ...opts};
  const T = focal.ticker;
  const xl = proseLabel(xCol), yl = proseLabel(yCol);
  const group = o.group ? new Set(o.group) : null;
  const out = {points: [], trend: null, reference: null, rel: null, region: null, interpretation: "",
    description: "", domain: null, disabledReason: null, regions: [], medianX: null, medianY: null, n: 0,
    xLabel: xl, yLabel: yl};
  const fx = cell(focal, xCol, ctx), fy = cell(focal, yCol, ctx);
  const R = (rows || []).map(asRow).filter((r) => r && !r.isFocal && r.inSet !== false);
  const pts = [];
  for (const r of R) {
    const cx = cell(r.record, xCol, ctx), cy = cell(r.record, yCol, ctx);
    if (cx.status === "ok" && cy.status === "ok" && isNum(cx.v) && isNum(cy.v)) {
      pts.push({ticker: r.ticker, record: r.record, x: cx.v, y: cy.v, xText: cx.text, yText: cy.text,
        excluded: !!r.excluded, inStats: !r.excluded && (!group || group.has(r.ticker))});
    }
  }
  let fit = pts.filter((p) => p.inStats);
  if ((o.outliers || "include") === "exclude" && fit.length >= 5) {
    const fxs = fences(fit.map((p) => p.x)), fys = fences(fit.map((p) => p.y));
    fit = fit.filter((p) => (!fxs || (p.x >= fxs.lo && p.x <= fxs.hi)) && (!fys || (p.y >= fys.lo && p.y <= fys.hi)));
  }
  out.n = fit.length;
  if (fx.status !== "ok" || fy.status !== "ok") {
    const bad = fx.status !== "ok" ? fx : fy;
    out.disabledReason = `${T} has no ${fx.status !== "ok" ? xl : yl} value (${bad.brief}).`;
    return out;
  }
  if (fit.length < MIN_SCATTER_PEERS) {
    out.disabledReason = fit.length === 0 ? `No peer has both ${xl} and ${yl}; at least 3 are needed.`
      : `Only ${fit.length} ${plural(fit.length, "peer has", "peers have")} both ${xl} and ${yl}; at least 3 are needed.`;
    return out;
  }
  const medX = median(fit.map((p) => p.x)), medY = median(fit.map((p) => p.y));
  out.medianX = medX; out.medianY = medY;
  const trend = ols(fit.map((p) => ({x: p.x, y: p.y})));
  out.trend = trend;
  const xf = fx.v, yf = fy.v;
  let reference, rel = null, medianReason = null;
  if (trend) {
    const yhat = trend.intercept + trend.slope * xf;
    if (yhat <= 0 || (isNum(medY) && yhat < 0.1 * medY)) {
      reference = "median"; medianReason = `the peer trend gives no usable value at ${T}'s ${xl}`;
    } else { reference = "trend"; rel = (yf - yhat) / yhat; }
  } else {
    reference = "median"; medianReason = "too few peers with both values to fit a trend";
  }
  if (reference === "median") rel = isNum(medY) && medY > 0 ? yf / medY - 1 : null;
  out.reference = reference; out.rel = rel;
  const dir = (COLUMN_BY_ID[xCol] || {}).dir || "n";
  const neutral = dir === "n";
  const better = dir === "-" ? xf < medX : xf > medX;
  const refWord = reference === "trend" ? "trend" : "peer median";
  const sideWord = neutral ? (better ? "above median" : "at or below median") : (better ? "better than median" : "at or worse than median");
  if (rel !== null) {
    if (Math.abs(rel) < NEAR_TREND_BAND) out.region = {id: "near", label: reference === "trend" ? "Near the peer trend" : "Near the peer median"};
    else if (rel >= NEAR_TREND_BAND) out.region = {id: better ? "above_better" : "above_worse", label: `Above ${refWord}, ${xl} ${sideWord}`};
    else out.region = {id: better ? "below_better" : "below_worse", label: `Below ${refWord}, ${xl} ${sideWord}`};
  }
  const classify = (xv0, yv0) => {
    let ref = "median", r = null;
    if (trend) {
      const yh = trend.intercept + trend.slope * xv0;
      if (!(yh <= 0 || (isNum(medY) && yh < 0.1 * medY))) { ref = "trend"; r = (yv0 - yh) / yh; }
    }
    if (ref === "median") r = isNum(medY) && medY > 0 ? yv0 / medY - 1 : null;
    const b = dir === "-" ? xv0 < medX : xv0 > medX;
    const rw = ref === "trend" ? "trend" : "peer median";
    const sw = neutral ? (b ? "above median" : "at or below median") : (b ? "better than median" : "at or worse than median");
    if (r === null) return null;
    if (Math.abs(r) < NEAR_TREND_BAND) return {id: "near", label: ref === "trend" ? "Near the peer trend" : "Near the peer median"};
    return {id: `${r > 0 ? "above" : "below"}_${b ? "better" : "worse"}`, label: `${r > 0 ? "Above" : "Below"} ${rw}, ${xl} ${sw}`};
  };
  const xv = proseValue(xCol, xf, ctx, focal);
  const pctTxt = rel === null ? NULL : wholePct(rel);
  const r2t = trend ? fmtNumber(trend.r2, 2) : null;
  if (reference === "median") {
    out.interpretation = rel === null ? `${T} cannot be placed against the peer median of ${yl}; ${medianReason}.`
      : `${T} sits ${pctTxt}% ${rel >= 0 ? "above" : "below"} the peer median of ${yl}; ${medianReason}.`;
  } else if (out.region && out.region.id === "near") {
    out.interpretation = `${T} sits close to the peer trend for its ${xl} of ${xv}.`;
  } else {
    const cmp = neutral ? (better ? "above the peer median" : "at or below the peer median") : (better ? "better than the peer median" : "worse than the peer median");
    out.interpretation = `${T} sits ${pctTxt}% ${rel > 0 ? "above" : "below"} the peer trend for its ${xl} of ${xv}, with ${xl} ${cmp}.`;
  }
  if (trend && trend.r2 < 0.10) out.interpretation += ` The peer trend is weak (R² ${r2t}), so distance from it says little.`;
  out.description = trend
    ? `${ucfirst(yl)} against ${xl} for ${fit.length} peers. Trend R² ${r2t}. ${T}: ${out.region ? out.region.label : "not placed"}.`
    : `${ucfirst(yl)} against ${xl} for ${fit.length} peers. Too few for a trend. ${T}: ${pctTxt}% ${rel !== null && rel >= 0 ? "above" : "below"} the peer median.`;
  // Points, domain, sizes and labels.
  const sizeCol = o.size === "ev" ? "ev.ev_usd_m" : (o.size === "none" ? null : "market.market_cap_usd_m");
  const all = pts.map((p) => ({...p, isFocal: false})).concat([{ticker: T, record: focal, x: xf, y: yf, xText: fx.text,
    yText: fy.text, excluded: false, inStats: false, isFocal: true}]);
  const peerX = pts.map((p) => p.x), peerY = pts.map((p) => p.y);
  const f3x = peerX.length >= 5 ? fences(peerX, TUKEY_EXTREME_K) : null;
  const f3y = peerY.length >= 5 ? fences(peerY, TUKEY_EXTREME_K) : null;
  const inX = all.map((p) => p.x).filter((v) => !f3x || (v >= f3x.lo && v <= f3x.hi));
  const inY = all.map((p) => p.y).filter((v) => !f3y || (v >= f3y.lo && v <= f3y.hi));
  const ex = inX.length ? [Math.min(...inX), Math.max(...inX)] : [Math.min(...all.map((p) => p.x)), Math.max(...all.map((p) => p.x))];
  const ey = inY.length ? [Math.min(...inY), Math.max(...inY)] : [Math.min(...all.map((p) => p.y)), Math.max(...all.map((p) => p.y))];
  const logY = !!o.logY && LOG_Y_COLS.includes(yCol) && ey[0] > 0;
  out.logY = logY;
  out.domain = {x: padDomain(ex[0], ex[1], false), y: padDomain(ey[0], ey[1], logY)};
  out.extent = {x: ex, y: ey};
  const sizes = all.map((p) => (sizeCol ? numAt(p.record, sizeCol) : null));
  const maxSize = Math.max(0, ...sizes.filter((s) => isNum(s) && s > 0));
  const largest = all.map((p, i) => ({t: p.ticker, s: sizes[i] || 0})).sort((a, b) => b.s - a.s).slice(0, 5).map((a) => a.t);
  out.points = all.map((p, i) => {
    const s = sizes[i];
    const cxr = p.x < ex[0] ? "lo" : p.x > ex[1] ? "hi" : null;
    const cyr = p.y < ey[0] ? "lo" : p.y > ey[1] ? "hi" : null;
    const extreme = !!(cxr || cyr);
    return {ticker: p.ticker, x: p.x, y: p.y, px: clamp(p.x, ex[0], ex[1]), py: clamp(p.y, ey[0], ey[1]),
      size: isNum(s) ? s : null, r: isNum(s) && s > 0 && maxSize > 0 ? 4 + 14 * Math.sqrt(s / maxSize) : 4,
      isFocal: p.isFocal, excluded: p.excluded, inStats: p.inStats, engine: p.record && p.record.engine,
      stage: p.record && p.record.stage, shape: SHAPES[p.record && p.record.engine] || "circle",
      hollow: p.record && p.record.stage === "clinical", clampedX: cxr, clampedY: cyr,
      showLabel: p.isFocal || extreme || (sizeCol ? largest.includes(p.ticker) : false),
      xText: p.xText, yText: p.yText,
      announce: (() => {
        const reg = p.isFocal ? out.region : classify(p.x, p.y);
        return `${p.ticker}: ${xl} ${proseValue(xCol, p.x, ctx, p.record)}, ${yl} ${proseValue(yCol, p.y, ctx, p.record)}${reg ? `, ${lcfirst(reg.label)}` : ""}`;
      })()};
  });
  if (trend && reference === "trend" && out.domain.x && out.domain.y) {
    const [x0, x1] = out.domain.x, [y0, y1] = out.domain.y;
    const halves = [{id: "left", x: (x0 + medX) / 2}, {id: "right", x: (medX + x1) / 2}];
    for (const hf of halves) {
      const yh = trend.intercept + trend.slope * hf.x;
      if (!(yh > 0)) continue;
      out.regions.push({id: `above_${hf.id}`, label: "Above trend", x: hf.x, y: (yh * (1 + NEAR_TREND_BAND) + y1) / 2});
      out.regions.push({id: `below_${hf.id}`, label: "Below trend", x: hf.x, y: (yh * (1 - NEAR_TREND_BAND) + y0) / 2});
    }
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// 3.9 Valuation bridge
// ---------------------------------------------------------------------------------------------

const STAT_LABEL = {median: "Median", mean: "Mean", p25: "25th percentile", p75: "75th percentile", pct: "Percentile"};
function statWord(stat, pct) {
  if (stat === "pct") return `${ordinal(pct)} percentile`;
  return {median: "median", mean: "mean", p25: "25th percentile", p75: "75th percentile"}[stat] || "median";
}

/** The focal's operating metric for a bridgeable column (USD m, or USD per share for forward EPS). */
function operatingMetric(focal, colId, ctx) {
  const h = helper(focal, ctx);
  const b = resolveBasis(colId, ctx.basis);
  const T = focal.ticker;
  const cur = h.cur;
  const fy0 = get(focal, "periods.FY0.label") || "FY0";
  const res = {usd: null, perShare: false, label: "", short: "", sourceText: "", period: null};
  try {
    if (colId === "pe" && (b === "NTM" || b === "FY1" || b === "FY2")) {
      res.perShare = true;
      if (b === "NTM") {
        res.short = "NTM EPS"; res.label = "NTM EPS, street, USD per share";
        const e1 = numAt(focal, "periods.FY1.eps"), e2 = numAt(focal, "periods.FY2.eps");
        res.usd = h.need("periods.NTM.eps");
        if ((e1 !== null && e1 <= 0) || (e2 !== null && e2 <= 0)) res.usd = Math.min(res.usd, 0);
      } else {
        const lbl = get(focal, `periods.${b}.label`) || b;
        res.short = `${lbl} EPS`; res.label = `${lbl} EPS, street, USD per share`;
        res.usd = h.need(`periods.${b}.eps`);
      }
      const asOf = get(focal, "periods.FY1.as_of") || get(focal, "street.consensus_checked_at");
      res.sourceText = `Sourced: Nasdaq consensus, ${fmtDate(asOf)}`;
      res.period = b;
    } else if (colId === "pe") {
      let ni = null, per = fy0;
      if (b === "LTM" && numAt(focal, "periods.LTM.net_income_usd_m") !== null) {
        ni = numAt(focal, "periods.LTM.net_income_usd_m"); per = get(focal, "periods.LTM.label") || "LTM";
      } else ni = h.need("periods.FY0.net_income_usd_m");
      res.usd = ni; res.short = `${per} net income`; res.label = `${per} net income, ${cur} m`;
      res.sourceText = `Sourced: filed ${per}`; res.period = per;
    } else if (colId === "ev_revenue" || colId === "price_to_sales") {
      const r = b === "FY1" ? guidedRevenue(h) : revenueOn(h, b);
      res.usd = r.usd; res.short = `${r.period} revenue`; res.label = `${r.period} revenue, ${cur} m`;
      res.sourceText = r.tag === "G" ? `Sourced: company guidance, ${fmtDate(get(focal, "periods.FY1.guidance.as_of"))}` : `Sourced: filed ${r.period}`;
      res.period = r.period;
    } else if (colId === "ev_ebitda") {
      res.usd = ebitdaFY0(h, []); res.short = `${fy0} EBITDA`; res.label = `${fy0} EBITDA, ${cur} m`;
      res.sourceText = `Sourced: filed ${fy0}`; res.period = fy0;
    } else if (colId === "price_to_book") {
      res.usd = h.need("periods.FY0.equity_usd_m");
      const d = get(focal, "periods.FY0.equity_as_of") || get(focal, "ev.balance_sheet_as_of");
      res.short = "equity"; res.label = `Equity at ${fmtDate(d)}, ${cur} m`; res.sourceText = `Sourced: balance sheet ${fmtDate(d)}`;
    } else if (colId === "mcap_to_cash") {
      res.usd = h.need("ev.cash_usd_m");
      const d = get(focal, "ev.balance_sheet_as_of");
      res.short = "cash"; res.label = `Cash and investments at ${fmtDate(d)}, ${cur} m`; res.sourceText = `Sourced: balance sheet ${fmtDate(d)}`;
    } else if (colId === "fcf_yield") {
      res.usd = h.need("periods.FY0.fcf_usd_m"); res.short = `${fy0} free cash flow`;
      res.label = `${fy0} free cash flow, ${cur} m`; res.sourceText = `Sourced: filed ${fy0}`; res.period = fy0;
    }
  } catch (e) {
    res.usd = null;
    if (e instanceof NotMeaningful) res.nmReason = e.reason;
    if (!res.short) res.short = proseLabel(colId);
  }
  if (!res.short) res.short = proseLabel(colId);
  res.missingText = `${T} has no ${res.short} on this basis.`;
  return res;
}

export const BRIDGE_DEFAULTS = {colId: null, basis: null, stat: "median", pct: 50, multipleOverride: null,
  metricOverride: null, netDebtOverride: null, sharesSource: "market_cap", sharesOverride: null,
  otherClaimsOn: false, otherClaimsOverride: null};

export function bridge(focal, rows, inputs = {}, ctx = {}) {
  const inp = {...BRIDGE_DEFAULTS, ...(inputs || {})};
  const T = focal.ticker;
  const colId = inp.colId;
  const basis = inp.basis || ctx.basis || "NTM";
  const bctx = basis === ctx.basis ? ctx : {...ctx, basis, cache: new Map()};
  const cur = displayCurrency(focal, ctx);
  const rate = rateFor(cur, ctx);
  const price = numAt(focal, "market.price");
  const toDisp = (usd) => (isNum(usd) && rate !== null ? usd / rate : null);
  const fromDisp = (d) => (isNum(d) && rate !== null ? d * rate : null);
  const pt = get(focal, "street.price_target");
  const ratings = (pt && pt.ratings) || {};
  const nAnalysts = ["buy", "hold", "sell"].reduce((s, k) => s + (isNum(ratings[k]) ? ratings[k] : 0), 0);
  const streetTarget = pt && isNum(pt.value) ? {value: pt.value, low: pt.low ?? null, high: pt.high ?? null,
    upside: isNum(price) ? pt.value / price - 1 : null, analysts: nAnalysts || null, as_of: pt.as_of || null} : null;
  const model = focal.model || {};
  const modelFairValue = model.state === "modelled" && isNum(model.fair_value_per_share)
    ? {value: model.fair_value_per_share, rating: model.rating || null,
       upside: isNum(price) ? model.fair_value_per_share / price - 1 : null} : null;
  const ocTotal = numAt(focal, "ev.other_claims_usd_m");
  const otherClaims = {available: ocTotal !== null, on: !!inp.otherClaimsOn && ocTotal !== null,
    total: toDisp(ocTotal), lines: (get(focal, "ev.other_claims_lines") || []).map((l) => ({...l, value: toDisp(l.value_usd_m)})),
    reason: ocTotal === null ? NA_TEXT.none_on_file : null,
    text: ocTotal === null ? NA_TEXT.none_on_file
      : `Off: peer enterprise values exclude these claims. Turn on to apply ${T}'s filed claims (${fmtMoneyProse(ocTotal, cur, ctx.fx)}).`};
  const sharesOptions = [
    {id: "market_cap", label: `Shares behind the market cap: ${get(focal, "market.market_cap_basis_text") || "market cap basis"}`, value: numAt(focal, "market.market_cap_shares_m")},
    {id: "diluted", label: "FY diluted weighted average", value: numAt(focal, "market.shares_diluted_m")},
    {id: "analyst", label: "Enter a count", value: isNum(inp.sharesOverride) ? inp.sharesOverride : null},
  ];
  const out = {enabled: false, reason: null, reasonId: null, colId, basis: colId ? resolveBasis(colId, basis) : null,
    metricLabel: colId ? metricLabel(colId, basis, bctx) : "", stat: inp.stat, pct: inp.pct, currency: cur,
    M: null, X: null, EVi: null, ND: null, OC: null, Eq: null, S: null, V: null, price, upside: null,
    range: null, rangeUpside: null, peerN: 0, isEV: colId === "ev_revenue" || colId === "ev_ebitda",
    perShareX: false, steps: [], description: "", streetTarget, modelFairValue, otherClaims, sharesOptions,
    target: null, inputs: inp, negativeEquity: false, analyst: {
      multiple: isNum(inp.multipleOverride), metric: isNum(inp.metricOverride), netDebt: isNum(inp.netDebtOverride),
      shares: inp.sharesSource === "analyst", otherClaims: isNum(inp.otherClaimsOverride), stat: inp.stat === "pct"}};
  const fail = (id, params) => {
    const m = stateMsg(id, params);
    out.enabled = false; out.reasonId = id; out.reason = m ? m.detail : null;
    out.description = out.reason || "";
    return out;
  };
  if (!colId || !BRIDGEABLE.includes(colId)) return fail("bridge_not_bridgeable", {metric: colId ? metricLabel(colId, basis, bctx) : "this metric"});
  const st = peerStats(rows, colId, bctx);
  out.peerN = st.n;
  const statVal = (s, p) => (s === "median" ? st.median : s === "mean" ? st.mean : s === "p25" ? st.p25
    : s === "p75" ? st.p75 : s === "pct" ? quantile(st.values, clamp(isNum(p) ? p : 50, 0, 100) / 100) : st.median);
  const M = isNum(inp.multipleOverride) ? inp.multipleOverride : statVal(inp.stat, inp.pct);
  out.M = M;
  const om = operatingMetric(focal, colId, bctx);
  out.perShareX = om.perShare;
  out.operatingShort = om.short;
  let Xusd = om.perShare ? (isNum(inp.metricOverride) ? inp.metricOverride : om.usd)
                         : (isNum(inp.metricOverride) ? fromDisp(inp.metricOverride) : om.usd);
  out.X = om.perShare ? Xusd : toDisp(Xusd);
  if (!isNum(Xusd)) {
    if (om.nmReason) { out.reasonId = "bridge_nonpositive"; out.reason = om.nmReason; out.description = om.nmReason; return out; }
    out.reasonId = "bridge_missing"; out.reason = om.missingText; out.description = om.missingText; return out;
  }
  if (Xusd <= 0) return fail("bridge_nonpositive", {metric: ucfirst(om.short), T});
  let NDusd = null, OCusd = 0;
  if (out.isEV) {
    NDusd = isNum(inp.netDebtOverride) ? fromDisp(inp.netDebtOverride) : numAt(focal, "ev.net_debt_usd_m");
    if (!isNum(NDusd)) return fail("bridge_no_net_debt", {T});
    if (otherClaims.on) OCusd = isNum(inp.otherClaimsOverride) ? fromDisp(inp.otherClaimsOverride) : ocTotal;
  }
  const S = inp.sharesSource === "analyst" ? (isNum(inp.sharesOverride) ? inp.sharesOverride : null)
    : inp.sharesSource === "diluted" ? numAt(focal, "market.shares_diluted_m") : numAt(focal, "market.market_cap_shares_m");
  if (!isNum(S) || S <= 0) return fail("bridge_no_shares", {T});
  if (!isNum(M)) {
    out.reasonId = "bridge_no_multiple";
    out.reason = `No peer has a ${proseLabel(colId)} value, so there is no multiple to apply.`;
    out.description = out.reason;
    return out;
  }
  const valueAt = (m) => {
    if (!isNum(m)) return {V: null, Eq: null, EVi: null};
    let EVi = null, Eq, V;
    if (out.isEV) { EVi = m * Xusd; Eq = EVi - NDusd + OCusd; }
    else if (om.perShare) { V = m * Xusd; Eq = V * S; return {V: Eq > 0 ? V : null, Eq, EVi}; }
    else if (colId === "fcf_yield") { if (m <= 0) return {V: null, Eq: null, EVi}; Eq = Xusd / m; }
    else Eq = m * Xusd;
    V = Eq > 0 ? Eq / S : null;
    return {V, Eq, EVi};
  };
  const main = valueAt(M);
  out.enabled = true;
  out.EVi = toDisp(main.EVi); out.ND = out.isEV ? toDisp(NDusd) : null; out.OC = out.isEV && otherClaims.on ? toDisp(OCusd) : null;
  out.Eq = toDisp(main.Eq); out.S = S; out.V = main.V;
  out.upside = isNum(main.V) && isNum(price) ? main.V / price - 1 : null;
  if (isNum(main.Eq) && main.Eq <= 0) {
    out.negativeEquity = true;
    out.reason = STATE_COPY.negative_equity.detail; out.reasonId = "negative_equity";
  }
  const lo = valueAt(st.p25).V, hi = valueAt(st.p75).V;
  if (isNum(lo) && isNum(hi)) {
    out.range = [Math.min(lo, hi), Math.max(lo, hi)];
    out.rangeUpside = isNum(price) ? [out.range[0] / price - 1, out.range[1] / price - 1] : null;
  }
  if (isNum(inp.multipleOverride) || inp.stat === "pct") out.target = {lo: M, hi: M};
  // Steps (5.3).
  const multUnit = colId === "fcf_yield" ? "%" : TIMES;
  const multText = colId === "fcf_yield" ? fmtNumber(M * 100, 1) + "%" : fmtNumber(M, colId === "peg" ? 2 : 1) + TIMES;
  const money = (d) => (isNum(d) ? fmtNumber(d, 0) : NULL);
  const bsDate = fmtDate(get(focal, "ev.balance_sheet_as_of"));
  const steps = [];
  steps.push({id: "metric", label: "Valuation metric", value: out.metricLabel, text: out.metricLabel, unit: null,
    source: "calculated", sourceText: "Calculated", editable: true});
  steps.push({id: "stat", label: "Peer statistic", value: inp.stat, text: inp.stat === "pct" ? `${ordinal(inp.pct)} percentile` : STAT_LABEL[inp.stat] || "Median",
    unit: null, source: inp.stat === "pct" ? "analyst" : "calculated", sourceText: `of ${st.n} peers`, editable: true});
  steps.push({id: "multiple", label: "Applied multiple", value: M, text: multText, unit: multUnit,
    source: isNum(inp.multipleOverride) ? "analyst" : "calculated", sourceText: isNum(inp.multipleOverride) ? "Analyst" : "Calculated", editable: true});
  steps.push({id: "operating", label: om.label, value: out.X, text: om.perShare ? fmtNumber(out.X, 2) : money(out.X),
    unit: om.perShare ? "USD" : `${cur} m`, source: isNum(inp.metricOverride) ? "analyst" : "sourced",
    sourceText: isNum(inp.metricOverride) ? "Analyst" : om.sourceText, editable: true});
  if (out.isEV) {
    steps.push({id: "ev", label: "Implied enterprise value", value: out.EVi, text: money(out.EVi), unit: `${cur} m`,
      source: "calculated", sourceText: "Calculated", editable: false});
    steps.push({id: "net_debt", label: "Less net debt", value: out.ND, text: money(out.ND), unit: `${cur} m`,
      source: isNum(inp.netDebtOverride) ? "analyst" : "sourced",
      sourceText: isNum(inp.netDebtOverride) ? "Analyst" : `Sourced: balance sheet ${bsDate}`, editable: true});
    steps.push({id: "other_claims", label: "Other claims", value: out.OC, text: otherClaims.on ? money(out.OC) : "Off", unit: `${cur} m`,
      source: isNum(inp.otherClaimsOverride) ? "analyst" : "sourced",
      sourceText: !otherClaims.available ? NA_TEXT.none_on_file : isNum(inp.otherClaimsOverride) ? "Analyst"
        : `Sourced: ${fmtDate(get(focal, "ev.other_claims_lines.0.as_of") || get(focal, "ev.balance_sheet_as_of"))}`,
      editable: otherClaims.available, on: otherClaims.on, disabled: !otherClaims.available, note: otherClaims.text});
  }
  steps.push({id: "equity", label: "Implied equity value", value: out.Eq, text: money(out.Eq), unit: `${cur} m`,
    source: "calculated", sourceText: "Calculated", editable: false});
  steps.push({id: "shares", label: "Shares", value: S, text: fmtNumber(S, 1), unit: "m",
    source: inp.sharesSource === "analyst" ? "analyst" : "sourced",
    sourceText: inp.sharesSource === "analyst" ? "Analyst" : inp.sharesSource === "diluted"
      ? `Sourced: ${get(focal, "market.shares_basis") || "FY weighted diluted"}` : `Sourced: ${get(focal, "market.market_cap_basis_text") || "market cap shares"}`,
    editable: true});
  steps.push({id: "per_share", label: "Implied value per share", value: out.V, text: isNum(out.V) ? fmtNumber(out.V, 2) : NULL,
    unit: "USD", source: "calculated", sourceText: out.negativeEquity ? STATE_COPY.negative_equity.detail : "Calculated", editable: false});
  steps.push({id: "price", label: "Current price", value: price, text: fmtNumber(price, 2), unit: "USD", source: "sourced",
    sourceText: `Sourced: close ${fmtDate(get(focal, "market.price_as_of"))}`, editable: false});
  steps.push({id: "upside", label: "Upside or downside", value: out.upside,
    text: isNum(out.upside) ? `${out.upside >= 0 ? UP_GLYPH : DOWN_GLYPH} ${fmtNumber(out.upside * 100, 1, {signed: true})}%` : NULL,
    unit: "%", source: "calculated", sourceText: "Calculated", editable: false});
  out.steps = steps;
  // Description (5.3).
  const ml = lcfirst(out.metricLabel);
  const statPhrase = isNum(inp.multipleOverride) ? `an analyst ${ml} of ${multText}` : `the peer ${statWord(inp.stat, inp.pct)} ${ml} of ${multText}`;
  let d;
  if (isNum(out.V)) {
    d = `Implied value of ${fmtNumber(out.V, 2)} USD per share at ${statPhrase}, against a price of ${fmtNumber(price, 2)}: ${fmtNumber(Math.abs(out.upside) * 100, 1)}% ${out.upside >= 0 ? "upside" : "downside"}.`;
  } else {
    d = `No implied value per share at ${statPhrase}: ${lcfirst(STATE_COPY.negative_equity.detail)}`;
  }
  if (out.range) d += ` Interquartile range ${fmtNumber(out.range[0], 2)} to ${fmtNumber(out.range[1], 2)}.`;
  if (out.isEV) {
    const mp = (usd) => fmtMoneyProse(usd, cur, ctx.fx);
    d += ` Implied enterprise value ${mp(main.EVi)}, less net debt ${mp(NDusd)}${otherClaims.on ? `, plus claims ${mp(OCusd)}` : ""}, gives equity of ${mp(main.Eq)}.`;
  }
  out.description = d;
  return out;
}

// ---------------------------------------------------------------------------------------------
// 3.10 Drivers and risks
// ---------------------------------------------------------------------------------------------

const OBS_SKIP_FLAGS = ["derived_operating_income", "derived_no_addback", "includes_minorities", "thin_estimates", "estimate_range_wide"];
const withMedian = (m, a, b) => (m && m !== NULL ? a : b);

const OBS_RULES = [
  {id: "growth_top", side: "premium", col: "revenue_growth", q: "top", tag: "revenue growth top quartile",
   long: (v, m) => `Revenue growth of ${v} is in the top quartile of peers (median ${m}).`,
   short: (v, m) => `revenue growth in the top quartile of peers (${v} against a median of ${m})`},
  {id: "eps_growth_top", side: "premium", col: "eps_growth", q: "top", forward: true, tag: "EPS growth top quartile",
   long: (v, m) => `Street EPS growth of ${v} is in the top quartile of peers (median ${m}).`,
   short: (v, m) => `street EPS growth in the top quartile of peers (${v} against a median of ${m})`},
  {id: "margin_top", side: "premium", col: "operating_margin", q: "top", tag: "operating margin top quartile",
   long: (v, m) => `Operating margin of ${v} is in the top quartile of peers (median ${m}).`,
   short: (v, m) => `an operating margin in the top quartile of peers (${v} against a median of ${m})`},
  {id: "roic_top", side: "premium", col: "roic", q: "top", tag: "ROIC top quartile",
   long: (v, m) => `Return on invested capital of ${v} is in the top quartile of peers (median ${m}).`,
   short: (v, m) => `a return on invested capital in the top quartile of peers (${v} against a median of ${m})`},
  {id: "pipeline_depth", side: "premium", col: "late_trials", q: "top", tag: "late-stage trials top quartile",
   long: (v, m) => `${v} late-stage ${v === "1" ? "trial" : "trials"} against a peer median of ${m}.`,
   short: (v, m) => `${v} late-stage ${v === "1" ? "trial" : "trials"} against a peer median of ${m}`},
  {id: "pipeline_value", side: "premium", col: "pipeline_to_ev", q: "top", prov: "M", tag: "pipeline value top quartile (model)",
   long: (v, m) => `Modelled pipeline value is ${v} of enterprise value against a peer median of ${m}. Model output.`,
   short: (v, m) => `modelled pipeline value of ${v} of enterprise value against a peer median of ${m}`},
  {id: "leverage_low", side: "premium", col: "net_debt_ebitda", q: "bottom", netCash: true, tag: "leverage bottom quartile",
   long: (v, m) => `Net debt of ${v} EBITDA against a peer median of ${m}.`,
   short: (v, m) => `net debt of ${v} EBITDA against a peer median of ${m}`},
  {id: "loe_low", side: "premium", col: "loe_share_5y", q: "bottom", tag: "patent exposure bottom quartile",
   long: (v, m) => `${v} of product revenue loses US exclusivity within five years, against a peer median of ${m}.`,
   short: (v, m) => `${v} of product revenue losing US exclusivity within five years against a peer median of ${m}`},
  {id: "visibility", side: "premium", col: "est_dispersion", q: "bottom", minEstimates: 5, own: ["estimate_range_wide"], tag: "narrow estimate range",
   long: (v, m) => `Analyst EPS estimates span ${v} of the mean, narrower than most peers (median ${m}).`,
   short: (v, m) => `a narrower analyst EPS estimate range than most peers (${v} of the mean against a median of ${m})`},
  {id: "runway_long", side: "premium", col: "runway_months", q: "top", preScale: true, minValue: 36, tag: "runway top quartile",
   long: (v, m) => `Cash runway of ${v} months against a peer median of ${m}.`,
   short: (v, m) => `a cash runway of ${v} months against a peer median of ${m}`},
  {id: "loss_making", side: "discount", col: "operating_margin", abs: true, tag: "operating loss",
   long: (v, m, x) => `Operating loss in ${x.period}: operating margin of ${v}.`,
   short: (v, m, x) => `an operating loss in ${x.period} (operating margin ${v})`},
  {id: "runway_short", side: "discount", col: "runway_months", abs: true, tag: "runway under 24 months",
   long: (v) => `Cash runway of ${v} months on trailing burn.`,
   short: (v) => `a cash runway of ${v} months on trailing burn`},
  {id: "product_concentration", side: "discount", col: "top_product_share", abs: true, tag: "one product over half of sales",
   long: (v) => `${v} of product revenue comes from one product.`,
   short: (v) => `${v} of product revenue from one product`},
  {id: "trial_concentration", side: "discount", col: "trial_concentration", abs: true, tag: "trials concentrated on one asset",
   long: (v) => `${v} of active trials study one asset.`,
   short: (v) => `${v} of active trials studying one asset`},
  {id: "binary_catalysts", side: "discount", col: "catalysts_12m", abs: true, tag: "binary catalysts in 12 months",
   long: (v) => `${v} clinical ${v === "1" ? "catalyst" : "catalysts"} due within 12 months, with little or no product revenue beside them. Dates are mostly estimated.`,
   short: (v) => `${v} clinical ${v === "1" ? "catalyst" : "catalysts"} due within 12 months`},
  {id: "patent_cliff", side: "discount", col: "loe_share_5y", abs: true, q: "top", tag: "patent exposure top quartile",
   long: (v, m) => withMedian(m, `${v} of product revenue loses US exclusivity within five years (peer median ${m}).`, `${v} of product revenue loses US exclusivity within five years.`),
   short: (v, m) => withMedian(m, `${v} of product revenue losing US exclusivity within five years (peer median ${m})`, `${v} of product revenue losing US exclusivity within five years`)},
  {id: "leverage_high", side: "discount", col: "net_debt_ebitda", abs: true, q: "top", tag: "leverage top quartile",
   long: (v, m) => withMedian(m, `Net debt of ${v} EBITDA against a peer median of ${m}.`, `Net debt of ${v} EBITDA.`),
   short: (v, m) => withMedian(m, `net debt of ${v} EBITDA against a peer median of ${m}`, `net debt of ${v} EBITDA`)},
  {id: "estimates_wide", side: "discount", col: "est_dispersion", q: "top", own: ["estimate_range_wide"], tag: "wide estimate range",
   long: (v, m) => `Analyst EPS estimates span ${v} of the mean, wider than most peers (median ${m}).`,
   short: (v, m) => `a wider analyst EPS estimate range than most peers (${v} of the mean against a median of ${m})`},
  {id: "estimates_thin", side: "discount", col: "n_estimates", abs: true, own: ["thin_estimates"], tag: "thin analyst coverage",
   long: (v) => `Only ${v} ${v === "1" ? "analyst covers" : "analysts cover"} FY1 EPS.`,
   short: (v) => `only ${v} ${v === "1" ? "analyst" : "analysts"} covering FY1 EPS`},
  {id: "growth_bottom", side: "discount", col: "revenue_growth", q: "bottom", tag: "revenue growth bottom quartile",
   long: (v, m) => `Revenue growth of ${v} is in the bottom quartile of peers (median ${m}).`,
   short: (v, m) => `revenue growth in the bottom quartile of peers (${v} against a median of ${m})`},
  {id: "margin_bottom", side: "discount", col: "operating_margin", q: "bottom", tag: "operating margin bottom quartile",
   long: (v, m) => `Operating margin of ${v} is in the bottom quartile of peers (median ${m}).`,
   short: (v, m) => `an operating margin in the bottom quartile of peers (${v} against a median of ${m})`},
];
export const OBSERVATION_RULES = OBS_RULES.map((r) => ({id: r.id, side: r.side, colId: r.col, tag: r.tag}));

function obsValueText(colId, v, ctx, rec) {
  if (colId === "runway_months" || colId === "late_trials" || colId === "catalysts_12m" || colId === "n_estimates") {
    return fmtNumber(v, 0);
  }
  return proseValue(colId, v, ctx, rec);
}

export function observations(focal, rows, ctx, opts = {}) {
  const o = {...((ctx && ctx.stats) || {}), ...opts};
  const type = companyType(focal);
  const preScale = type === "clinical" || type === "sub_scale";
  const statsCache = {};
  const st = (colId) => (statsCache[colId] = statsCache[colId] || peerStats(rows, colId, ctx, o));
  const premiumList = [], discountList = [], suppressed = [];
  const fired = new Set();
  const forwardEps = ["NTM", "FY1", "FY2"].includes(resolveBasis("eps_growth", ctx.basis));
  for (const rule of OBS_RULES) {
    const fc = cell(focal, rule.col, ctx);
    if (rule.id === "loss_making") {
      if (type !== "loss_making") continue;
    } else if (fc.status !== "ok" || !isNum(fc.v)) continue;
    if (rule.forward && !forwardEps) continue;
    const skip = (fc.flags || []).filter((f) => OBS_SKIP_FLAGS.includes(f) && !(rule.own || []).includes(f));
    if (skip.length) {
      suppressed.push({id: rule.id, colId: rule.col, flags: skip,
        text: `${COLUMN_BY_ID[rule.col].label} not assessed: ${flagText(skip[0], focal).text}`});
      continue;
    }
    const s = st(rule.col);
    const vals = s.values;
    // A focal value equal to the peer median sits in no quartile worth stating (all peers at 0 trials).
    const side = isNum(s.median) && fc.v === s.median ? null : quartileSide(fc.v, vals);
    const pct = percentileRank(fc.v, vals);
    const qStrength = isNum(pct) ? Math.abs(pct - 50) : 0;
    let fire = false, strength = 0, severity = rule.side === "discount" ? "amber" : "info";
    const v = fc.v;
    switch (rule.id) {
      case "leverage_low":
        if (side === "bottom") { fire = true; strength = qStrength; }
        else if (v < 0 && isNum(s.median) && s.median > 0) { fire = true; strength = 50; }
        break;
      case "visibility":
        fire = side === "bottom" && (numAt(focal, "periods.FY1.eps_n") ?? 0) >= 5; strength = qStrength; break;
      case "runway_long":
        fire = preScale && v >= 36 && side === "top"; strength = qStrength; break;
      case "loss_making":
        fire = true; strength = 50; break;
      case "runway_short":
        fire = v < 24; strength = 50; if (v < 12) severity = "red"; break;
      case "product_concentration":
        fire = v >= 0.50; strength = 50; break;
      case "trial_concentration":
        fire = v >= 0.50 && (numAt(focal, "healthcare.active_mapped_trials") ?? 0) >= 3; strength = 50; break;
      case "binary_catalysts":
        fire = preScale && v >= 1; strength = 50; break;
      case "patent_cliff":
        if (v >= 0.30) { fire = true; strength = 50; }
        if (side === "top") { fire = true; strength = Math.max(strength, qStrength); }
        break;
      case "leverage_high":
        if (v > 0 && v >= 3.0) { fire = true; strength = 50; }
        if (v > 0 && side === "top") { fire = true; strength = Math.max(strength, qStrength); }
        break;
      case "estimates_thin":
        fire = v < 3; strength = 50; break;
      case "margin_bottom":
        fire = side === "bottom" && focal.stage === "commercial" && !fired.has("loss_making"); strength = qStrength; break;
      default:
        fire = rule.q ? side === rule.q : false; strength = qStrength;
    }
    if (!fire) continue;
    fired.add(rule.id);
    const vt = rule.id === "loss_making" && fc.status !== "ok"
      ? fmtMoneyProse(numAt(focal, "periods.FY0.operating_income_usd_m"), displayCurrency(focal, ctx), ctx.fx)
      : obsValueText(rule.col, v, ctx, focal);
    const mt = isNum(s.median) ? obsValueText(rule.col, s.median, ctx, focal) : null;
    const x = {period: get(focal, "periods.FY0.label") || "the last fiscal year"};
    let long = rule.long(vt, mt, x), short = rule.short(vt, mt, x);
    if (rule.id === "loss_making" && fc.status !== "ok") {
      long = `Operating loss in ${x.period}: operating income of ${vt}.`;
      short = `an operating loss in ${x.period} (operating income ${vt})`;
    }
    const obs = {id: rule.id, side: rule.side, colId: rule.col, value: isNum(v) ? v : null, median: s.median,
      pct, strength, severity, provenance: rule.prov || "C", short, tag: rule.tag, long};
    (rule.side === "premium" ? premiumList : discountList).push(obs);
  }
  const bySt = (a, b) => b.strength - a.strength;
  premiumList.sort(bySt); discountList.sort(bySt);
  return {premium: premiumList, discount: discountList, notAssessed: NOT_ASSESSED.slice(), suppressed};
}

// ---------------------------------------------------------------------------------------------
// 3.11 Conclusion banner and confidence
// ---------------------------------------------------------------------------------------------

function conclusionState(A) {
  if (A.focal.error) return "error";
  if (!A.included.length) return "no_peers";
  return A.primary.state;
}

/** Amber (or red) flags on the focal's primary cell that cost a confidence point. */
function costingFlags(A) {
  const P = A.primary;
  if (!P || !P.colId) return [];
  const fc = cell(A.focal, P.colId, A.ctx);
  const recFlags = (A.focal.flags || []).filter((f) => f && fc.flags.includes(f.code));
  const client = fc.flags.filter((c) => !recFlags.some((f) => f.code === c)).map((c) => ({code: c, params: {}}));
  return recFlags.concat(client).filter((f) => {
    const s = sevOf(f);
    if (s !== "amber" && s !== "red") return false;
    if (f.code === "estimate_range_wide") {
      const n = numAt(A.focal, "periods.FY1.eps_n");
      const d = numAt(A.focal, "risk.est_dispersion");
      return (n !== null && n < WIDE_RANGE_MIN_ESTIMATES) || (d !== null && d > WIDE_RANGE_MAX);
    }
    return true;
  });
}

export function confidence(view) {
  const A = view && view.analysis;
  if (!A) return {level: null, score: null, reasons: [], points: []};
  const state = conclusionState(A);
  if (["too_few", "no_multiple", "no_peers", "error"].includes(state)) return {level: null, score: null, reasons: [], points: []};
  const P = A.primary;
  const st = A.pStats;
  const pts = [];
  const k = st.n;
  pts.push({text: `${k} ${plural(k, "peer has", "peers have")} a value`, points: k >= 8 ? 2 : k >= MIN_PEERS ? 1 : 0});
  if (A.appropriate < 5) {
    pts.push({text: `Only ${A.appropriate} of ${A.included.length} peers score 40 or more on relevance`, points: -1});
  }
  if (isNum(A.medianRelevance) && A.medianRelevance < MIN_MEDIAN_RELEVANCE) {
    pts.push({text: `The median peer relevance is ${Math.round(A.medianRelevance)} of 100`, points: -1});
  }
  if (A.mixed) pts.push({text: `Peers mix ${A.mixed.focalType} and ${A.mixed.otherType} companies`, points: -1});
  if (usesFiledFigures(P.colId, P.basis) && A.standards.ifrs > 0 && A.standards.gaap > 0) {
    pts.push({text: `Peers mix IFRS and US GAAP filers, and ${proseLabel(P.colId)} uses filed figures`, points: -1});
  }
  const peerCells = st.tickers.map((t) => cell(A.byTicker[t], P.colId, A.ctx));
  const fyInLtm = peerCells.filter((c) => c.tagDiffers).length;
  if (fyInLtm > 0) pts.push({text: `${fyInLtm} peer values are fiscal-year figures in an LTM column`, points: -1});
  const derived = peerCells.filter((c) => c.flags.includes("derived_operating_income")).length;
  if (k > 0 && derived / k > MAX_DERIVED_SHARE) {
    pts.push({text: `${derived} of ${k} peer EBITDA figures are derived and may be overstated`, points: -1});
  }
  const costing = costingFlags(A);
  if (costing.length) pts.push({text: stripStop(flagText(costing[0], A.focal).text), points: -1});
  if (isNum(st.iqr) && isNum(st.median) && st.median > 0 && st.iqr / st.median > MAX_DISPERSION_RATIO) {
    pts.push({text: `Peer values are widely spread (interquartile range ${Math.round(st.iqr / st.median * 100)}% of the median)`, points: -1});
  }
  const extreme = (A.state.outliers || "include") === "include" ? st.outliers.extreme.length : 0;
  if (extreme) pts.push({text: `${extreme} extreme ${plural(extreme, "outlier", "outliers")} in the statistics`, points: -1});
  const score = pts.reduce((s, p) => s + p.points, 0);
  let level = score >= 2 ? "high" : score === 1 ? "medium" : "low";
  if (state === "low_confidence") level = "low";
  return {level, score, reasons: pts.map((p) => p.text), points: pts};
}

function testedAssociation(A, dir, first) {
  const sc = A.scatter;
  if (!first || !sc || !sc.trend || sc.trend.r2 < 0.10 || sc.disabledReason) return null;
  if (sc.x !== first.colId || sc.y !== A.primary.colId) return null;
  const xv = cell(A.focal, sc.x, A.ctx).v;
  if (!isNum(xv) || !isNum(sc.medianX) || xv === sc.medianX) return null;
  let premiumSide = (sc.trend.slope > 0) === (xv > sc.medianX);
  if (multipleDirection(A.primary.colId) === "richer_down") premiumSide = !premiumSide;
  if ((dir === "premium") !== premiumSide) return null;
  const r2 = fmtNumber(sc.trend.r2, 2);
  return {
    sentence: `The ${dir} is associated with ${first.short}: across these peers, ${proseLabel(sc.x)} and ${proseLabel(A.primary.colId)} ${sc.trend.slope > 0 ? "rise" : "fall"} together (R² ${r2}).`,
    short: `Associated with ${first.tag} (R² ${r2})`,
  };
}

function lookNextFor(A, state) {
  const T = A.T, P = A.primary;
  if (P.colId && ["ok", "low_confidence", "too_few"].includes(state)) {
    const fc = cell(A.focal, P.colId, A.ctx);
    const costing = costingFlags(A);
    if (fc.red || costing.length) {
      const chip = lcfirst(fc.red ? "Calculation failed" : flagText(costing[0], A.focal).chip);
      let t = `Check ${T}'s ${proseLabel(P.colId)} data: ${chip}`;
      if (t.length > MAX_LOOK_NEXT_CHARS) t = `Check ${T}'s ${proseLabel(P.colId)} data`;
      return {text: cutAt(t, MAX_LOOK_NEXT_CHARS), target: {kind: "cell", colId: P.colId, ticker: T}};
    }
  }
  const obs = A.obs.premium.concat(A.obs.discount).filter((o) => o.provenance !== "M").sort((a, b) => b.strength - a.strength);
  if (obs.length) return {text: cutAt(obs[0].tag, MAX_LOOK_NEXT_CHARS), target: {kind: "cell", colId: obs[0].colId, ticker: T}};
  if (P.colId && (A.state.outliers || "include") === "include" && A.pStats && A.pStats.outliers.extreme.length) {
    const t = A.pStats.outliers.extreme[0];
    return {text: cutAt(`${t}, an extreme ${proseLabel(P.colId)} value`, MAX_LOOK_NEXT_CHARS), target: {kind: "dotplot", colId: P.colId, ticker: t}};
  }
  if (A.scatter && A.scatter.trend && A.scatter.trend.r2 < 0.10 && !A.scatter.disabledReason) {
    return {text: "Valuation against growth: weak trend", target: {kind: "scatter", colId: A.scatter.y || null, ticker: null}};
  }
  return {text: `The peer set: ${A.setRows.length} peers`, target: {kind: "peers", colId: null, ticker: null}};
}

function weakTooltip(A) {
  if (A.defaultWarning === "too_few") {
    return stateMsg("default_short", {n: A.def.tickers.length, T: A.T}).detail;
  }
  if (A.defaultWarning === "padded") {
    const low = A.def.tickers.filter((t) => A.def.pools[t] !== "A" && A.def.scores[t] < MIN_DEFAULT_RELEVANCE).length;
    const m = stateMsg("padded", {k: low, n: A.def.tickers.length});
    return `${m.title}. ${m.detail}`;
  }
  return `Only ${A.appropriate} of ${A.included.length} peers score 40 or more on relevance. The median rests on less comparable companies.`;
}

export function conclusion(view) {
  const A = view.analysis;
  const T = A.T, P = A.primary, ctx = A.ctx, focal = A.focal;
  const state = conclusionState(A);
  const conf = confidence(view);
  const noun = A.label.noun;
  const cur = displayCurrency(focal, ctx);
  const mp = (usd) => fmtMoneyProse(usd, cur, ctx.fx);
  const out = {state, headline: "", support: "", supportShort: "", token: {text: NULL, caption: "no premium stated", dir: null},
    label: SYSTEM_LABEL, labelShort: SYSTEM_LABEL_SHORT, confidence: conf, bar: "active", chips: [], lookNext: null,
    why: {groups: []}, metric: P.colId ? proseLabel(P.colId) : null, value: null, median: null, premium: null,
    pct: null, n: A.pStats ? A.pStats.n : 0, notes: [], action: null};
  const nonM = (l) => l.filter((o) => o.provenance !== "M");
  const prem = nonM(A.obs.premium), disc = nonM(A.obs.discount);
  const bySt = (a, b) => b.strength - a.strength;
  const peerCells = A.pStats ? A.pStats.tickers.map((t) => cell(A.byTicker[t], P.colId, ctx)) : [];
  const fmt = (v) => proseValue(P.colId, v, ctx, focal);

  if (state === "error") {
    out.headline = "The summary could not be computed.";
    out.support = `${stripStop(String(focal.error))}. The table below is unaffected.`;
    out.supportShort = "The summary could not be computed";
  } else if (state === "no_peers") {
    out.headline = "No peers are selected, so there is no comparison.";
    out.support = "Add a peer with A or from the peer panel, or restore the system set.";
    out.supportShort = "No peers selected";
    out.action = {label: "Restore system peers", command: "peers.restore"};
  } else if (state === "no_multiple") {
    out.headline = `No valuation multiple has both a value for ${T} and 2 or more peer values.`;
    const first = P.firstCandidate;
    const fc = first ? cell(focal, first, ctx) : null;
    const mcUsd = numAt(focal, "market.market_cap_usd_m");
    const mcPeers = A.statsRows.map((r) => numAt(r.record, "market.market_cap_usd_m"));
    const pct = percentileRank(mcUsd, mcPeers);
    const cash = numAt(focal, "ev.cash_usd_m");
    const run = numAt(focal, "risk.runway_months");
    let s = first ? `${metricLabel(first, ctx.basis, ctx)}: ${fc.reason} ` : "";
    s += `Market cap is ${mp(mcUsd)}${pct !== null ? `, the ${ordinal(Math.round(pct))} percentile of peers` : ""}`;
    if (isNum(cash) && isNum(mcUsd) && mcUsd > 0) s += `; cash covers ${fmtPctProse(cash / mcUsd, 0)} of it`;
    if (isNum(run)) s += `; cash runway is ${Math.round(run)} months on trailing burn`;
    out.support = s + ".";
    out.supportShort = `Market cap ${mp(mcUsd)}${pct !== null ? `, ${ordinal(Math.round(pct))} percentile` : ""}`;
  } else if (state === "too_few") {
    out.headline = P.reasonText;
    out.support = "Widen the set to adjacent subsectors, or add peers with A.";
    out.supportShort = "Too few peer values for a comparison";
    out.action = {label: "Add adjacent-subsector peers", command: "peers.addAdjacent"};
    out.value = cell(focal, P.colId, ctx).v;
  } else {
    const parts = headlineParts(focal, P.colId, ctx, peerCells);
    const st = A.pStats;
    const k = st.n;
    out.value = parts.cell.v; out.median = st.median; out.pct = A.pct; out.n = k;
    if (state === "low_confidence") {
      out.headline = `${T} trades at ${parts.v} ${parts.metric} (${parts.period}). Only ${k} peers have a value, so no premium or discount is stated.`;
      out.support = `The ${k} peer values run from ${fmt(st.min)} to ${fmt(st.max)}. A median of fewer than 5 is not a reliable reference.`;
      out.supportShort = `Only ${k} peer values`;
    } else if (!isNum(A.premium)) {
      // A zero or negative focal value (a nil free cash flow) gives no ratio against the median.
      out.headline = `${T} trades at ${parts.v} ${parts.metric} (${parts.period}); the median of ${k} ${noun} is ${fmt(st.median)}.`;
      out.support = `No premium or discount is stated: ${lcfirst(proseLabel(P.colId))} at or below zero has no ratio to the median.`;
      out.supportShort = "No premium or discount stated";
    } else {
      const p = A.premium;
      out.premium = p;
      const inLine = isInLine(p);
      const dir = isNum(p) && p >= 0 ? "premium" : "discount";
      const m = fmt(st.median);
      const build = (nn) => {
        if (P.colId === "fcf_yield") {
          return inLine
            ? `${T}'s FCF yield of ${parts.v} (${parts.period}) sits against a median of ${m} for ${k} ${nn}: in line on this measure (${signedWholePct(p)}).`
            : `${T}'s FCF yield of ${parts.v} (${parts.period}) sits against a median of ${m} for ${k} ${nn}: ${article(wholePct(p))} ${wholePct(p)}% ${dir} on this measure.`;
        }
        return inLine
          ? `${T} trades at ${parts.v} ${parts.metric} (${parts.period}), in line with the median of ${k} ${nn}, ${m} (${signedWholePct(p)}).`
          : `${T} trades at ${parts.v} ${parts.metric} (${parts.period}), ${article(wholePct(p))} ${wholePct(p)}% ${dir} to the median of ${k} ${nn}, ${m}.`;
      };
      out.headline = build(noun);
      if (out.headline.length > MAX_HEADLINE_CHARS) out.headline = build("peers");
      out.token = inLine ? {text: signedWholePct(p), caption: "in line with median", dir: null}
        : {text: signedWholePct(p), caption: `${dir} to median`, dir: dir === "premium" ? "up" : "down"};
      const same = dir === "premium" ? prem : disc;
      const other = dir === "premium" ? disc : prem;
      if (A.type === "clinical" || A.type === "sub_scale") {
        const ev = numAt(focal, "ev.ev_usd_m");
        const run = numAt(focal, "risk.runway_months");
        const r = isNum(run) ? Math.round(run) : null;
        let s1;
        if (ev !== null) s1 = `Enterprise value is ${mp(ev)}${r !== null ? `, and cash runway is ${r} months on trailing burn` : ""}.`;
        else {
          const code = naCode(focal, "ev.ev_usd_m");
          const why = code === "no_debt_line" ? "no debt line on file" : lcfirst(stripStop(NA_TEXT[code] || NA_TEXT.no_free_data));
          s1 = `Enterprise value is not computed (${why})${r !== null ? `; cash runway is ${r} months on trailing burn` : ""}.`;
        }
        const sentences = [s1];
        if (!inLine && same.length) sentences.push(`Alongside the ${dir}, ${T} has ${same[0].short}.`);
        else if (inLine) {
          const all = prem.concat(disc).sort(bySt);
          if (all.length) sentences.push(`Measures furthest from peers: ${all[0].short}.`);
        }
        out.support = sentences.join(" ");
        out.supportShort = ev !== null ? `EV ${mp(ev)}${r !== null ? `; runway ${r} months` : ""}` : `EV not computed${r !== null ? `; runway ${r} months` : ""}`;
      } else if (inLine) {
        const all = prem.concat(disc).sort(bySt);
        out.support = all.length ? `Measures furthest from peers: ${all[0].short}${all[1] ? `; ${all[1].short}` : ""}.`
          : "Its measures sit mostly within the peer interquartile range.";
        out.supportShort = all.length ? `Furthest from peers: ${all[0].tag}` : "Measures mostly within the peer range";
      } else if (same.length) {
        const assoc = testedAssociation(A, dir, same[0]);
        const s1 = assoc ? assoc.sentence : `Alongside the ${dir}, ${T} has ${same[0].short}${same[1] ? ` and ${same[1].short}` : ""}.`;
        const sentences = [s1];
        if (other.length) sentences.push(`On the other side, it has ${other[0].short}.`);
        out.support = sentences.join(" ");
        if (assoc) out.supportShort = assoc.short;
        else {
          out.supportShort = `Alongside: ${same[0].tag}`;
          if (same[1] && (`${out.supportShort}; ${same[1].tag}`).length <= MAX_SUPPORT_SHORT_CHARS) out.supportShort += `; ${same[1].tag}`;
        }
      } else {
        out.support = `No measure in this table sits in the direction of the ${dir}. It may reflect factors outside the free data, such as deal expectations, litigation or pricing.`;
        out.supportShort = "No measure here sits in its direction";
      }
    }
  }
  out.headline = cutAt(out.headline, MAX_HEADLINE_CHARS);
  out.supportShort = cutAt(out.supportShort, MAX_SUPPORT_SHORT_CHARS);
  if ((focal.flags || []).some((f) => f && f.code === "no_consensus")) {
    out.notes.push(`No consensus estimates for ${T}, so the comparison uses reported ${get(focal, "periods.FY0.label") || "FY0"} figures.`);
  }
  // Chips and bar.
  if (A.weakChip) out.chips.push({id: "weak", text: "Weak peer set", tone: "flag", tooltip: weakTooltip(A)});
  if (A.mixed) {
    const m = stateMsg("mixed_models", {k: A.mixed.k, n: A.mixed.n, other: A.mixed.otherType, T, focalType: A.mixed.focalType});
    out.chips.push({id: "mixed", text: "Mixed business models", tone: "flag", tooltip: m.detail});
  }
  if (state === "low_confidence") {
    out.chips.push({id: "low", text: "Low confidence", tone: "flag", tooltip: lowConfidenceText(A.pStats.n, P.colId)});
  }
  if (state === "error") out.bar = "down";
  else if (conf.level === "low" || state === "low_confidence" || state === "too_few" || A.weakChip) out.bar = "flag";
  else out.bar = "active";
  out.lookNext = lookNextFor(A, state);
  out.why = whyGroups(A, conf, state);
  return out;
}

function whyGroups(A, conf, state) {
  const P = A.primary, ctx = A.ctx, focal = A.focal;
  const groups = [];
  groups.push({title: "Primary metric", items: [{text: P.reasonText, colId: P.colId, provenance: "C"}]});
  const confItems = conf.points.map((p) => ({text: p.text + ".", colId: null, provenance: "C", points: p.points}));
  if (conf.level === null && state !== "error") confItems.push({text: P.reasonText, colId: P.colId, provenance: "C"});
  if (A.weakChip) confItems.push({text: weakTooltip(A), colId: null, provenance: "C"});
  groups.push({title: "Confidence", items: confItems});
  const obs = A.obs.premium.concat(A.obs.discount);
  const obsItems = obs.map((o) => ({text: o.long, colId: o.colId, provenance: o.provenance, label: o.provenance === "M" ? "Model output" : null, side: o.side}));
  for (const s of A.obs.suppressed || []) obsItems.push({text: s.text, colId: s.colId, provenance: "C", suppressed: true});
  if (obsItems.length) groups.push({title: "Observations", items: obsItems});
  const outl = [];
  if (P.colId && A.pStats && (state === "ok" || state === "low_confidence")) {
    if (A.pStats.outliers.extreme.length) {
      outl.push({text: `${A.pStats.outliers.extreme.join(", ")}: ${STATE_COPY.extreme_outliers.detail}`, colId: P.colId, provenance: "C"});
    }
    if ((A.state.outliers || "include") === "include" && (A.pStats.outliers.mild.length || A.pStats.outliers.extreme.length)) {
      const ex = peerStats(A.statsRows, P.colId, ctx, {outliers: "exclude", group: A.group});
      const fv = cell(focal, P.colId, ctx).v;
      if (isNum(ex.median) && isNum(A.pStats.median) && A.pStats.median !== 0 && Math.abs(ex.median / A.pStats.median - 1) > 0.05) {
        const p2 = premium(fv, ex.median, multipleDirection(P.colId));
        if (isNum(p2)) {
          outl.push({text: `Without outliers the median is ${proseValue(P.colId, ex.median, ctx, focal)} and the ${p2 >= 0 ? "premium" : "discount"} is ${wholePct(p2)}%.`, colId: P.colId, provenance: "C"});
        }
      }
    }
  }
  if (outl.length) groups.push({title: "Outliers", items: outl});
  const bases = [];
  if (A.standards.ifrs > 0 && A.standards.gaap > 0) {
    bases.push({text: stateMsg("mixed_standards", {i: A.standards.ifrs, g: A.standards.gaap}).detail, colId: null, provenance: "C"});
  }
  if (["NTM", "FY1", "FY2"].includes(ctx.basis)) bases.push({text: STATE_COPY.street_vs_reported.detail, colId: null, provenance: "C"});
  if (bases.length) groups.push({title: "Bases", items: bases});
  return {groups, link: "Open drivers and risks"};
}

// ---------------------------------------------------------------------------------------------
// House style lint (3.11)
// ---------------------------------------------------------------------------------------------

export const LINT_ALLOW = ["US", "GAAP", "IFRS", "EPS", "EV", "EBITDA", "FCF", "NTM", "LTM", "R&D", "IPR&D", "ECB",
  "USD", "EUR", "GBP", "CHF", "DKK", "IRA", "LOE", "OTC", "ADR", "CSV", "TSV", "P/E", "P/B", "PEG", "ROIC", "SG&A",
  "XLV", "S&P", "CAGR", "rNPV", "R²", "Phase", "Part", "Blume", "Nasdaq", "NYSE", "London", "FDA", "Forecast",
  "Financials", "Comps", "Pipelines", "Indications", "Valuation", "AZN", "PoS", "PDUFA", "EMA", "Catalysts",
  // Metric names that join two allowed terms with a slash (3.11 accepts "EV/Revenue").
  "EV/Revenue"];
const LINT_PART = /^(FY\d{0,4}|Q[1-4]|\d+-[A-Z]|[A-Z])$/;

/**
 * `lintCopy(text, kind, extraAllowed)`: "em dash" anywhere except the bare null glyph, "banned: {w}"
 * per banned word, and for kind "label" "not sentence case" when a later word starts with a
 * capital that is not allowed. `extraAllowed` takes the payload's tickers and company names.
 * Month abbreviations in dates ("28 Sep") are data and pass.
 */
export function lintCopy(text, kind = "sentence", extraAllowed = []) {
  const issues = [];
  const s = String(text == null ? "" : text);
  if (s !== NULL && s.includes("—")) issues.push("em dash");
  for (const w of BANNED_WORDS) {
    if (new RegExp(`(^|[^A-Za-z])${w}([^A-Za-z]|$)`, "i").test(s)) issues.push(`banned: ${w}`);
  }
  if (kind === "label") {
    const allow = new Set(LINT_ALLOW);
    for (const e of extraAllowed || []) {
      if (!e) continue;
      allow.add(e);
      for (const w of String(e).split(/\s+/)) allow.add(w.replace(/[,.]+$/, ""));
    }
    const words = s.split(/\s+/).filter(Boolean);
    for (let i = 1; i < words.length; i++) {
      const w = words[i].replace(/^[("'“‘[{]+/, "").replace(/[)"'”’\]},.:;!?…]+$/, "").replace(/['’]s$/, "");
      if (!w || !/^[A-Z]/.test(w)) continue;
      if (allow.has(w) || MONTHS.includes(w)) continue;
      const parts = w.split(/[/-]/).filter(Boolean);
      if (parts.length && parts.every((p) => allow.has(p) || MONTHS.includes(p) || LINT_PART.test(p) || !/^[A-Z]/.test(p))) continue;
      issues.push("not sentence case");
      break;
    }
  }
  return issues;
}

// ---------------------------------------------------------------------------------------------
// 3.14 Commands and keys
// ---------------------------------------------------------------------------------------------

function cmd(id, label, keys, group, when = "global") {
  const ks = keys || [];
  const single = ks.length ? isSingleKeyBinding(ks[0]) && when !== "grid" : false;
  return {id, label, key: ks[0] || null, keys: ks, group, when, singleKey: single};
}
function isSingleKeyBinding(k) {
  return !!k && !/^(mod|alt)\+/.test(k) && k !== "esc";
}

/**
 * The single list behind the help overlay, the palette and the key handler (7.2). `when` is
 * "global" or "grid" (active only while the table grid has focus). `singleKey` marks a binding
 * with no modifier outside a focused grid or chart; `keys` lists every binding of the command.
 */
export const COMMANDS = [
  cmd("palette.open", "Open the command palette", ["mod+k", "/"], "General"),
  cmd("help.open", "Show keyboard shortcuts", ["?"], "General"),
  cmd("company.open", "Change the focal company", ["c"], "General"),
  cmd("preset.1", "Core valuation columns", ["1"], "Table"),
  cmd("preset.2", "Growth and profitability columns", ["2"], "Table"),
  cmd("preset.3", "Balance sheet and risk columns", ["3"], "Table"),
  cmd("preset.4", "Pharma columns", ["4"], "Table"),
  cmd("preset.5", "Biotechnology columns", ["5"], "Table"),
  cmd("preset.6", "Cell and gene therapy columns", ["6"], "Table"),
  cmd("preset.7", "Custom columns", ["7"], "Table"),
  cmd("basis.next", "Next period basis", ["p"], "Basis"),
  cmd("basis.prev", "Previous period basis", ["shift+p"], "Basis"),
  cmd("currency.next", "Next display currency", ["y"], "Basis"),
  cmd("earnings.toggle", "Switch between GAAP/IFRS and ex amort. and IPR&D", ["g"], "Basis"),
  cmd("metric.open", "Focus the dot plot metric switcher", ["m"], "Charts"),
  cmd("columns.find", "Search metrics and columns", ["f"], "Table"),
  cmd("peer.add", "Add a peer", ["a"], "Peers"),
  cmd("peer.exclude", "Exclude or include the focused row in statistics", ["x"], "Peers", "grid"),
  cmd("peer.remove", "Remove the focused row from the peer set", ["shift+x", "delete"], "Peers", "grid"),
  cmd("detail.open", "Open the focused row's side panel", ["enter", "o"], "Table", "grid"),
  cmd("row.expand", "Expand or collapse the focused row", ["shift+enter"], "Table", "grid"),
  cmd("export.csv", "Export CSV of the current view", ["e"], "Export"),
  cmd("export.tsv", "Copy the current view as TSV", ["shift+e"], "Export"),
  cmd("filters.reset", "Clear all filters", ["r"], "Table"),
  cmd("layout.reset", "Reset columns, widths and sort for this preset", ["shift+r"], "Table"),
  cmd("outliers.toggle", "Statistics with or without outliers", ["u"], "Peers"),
  cmd("cf.next", "Next conditional format mode", ["v"], "Table"),
  cmd("sort.focused", "Sort by the focused column", ["s"], "Table", "grid"),
  cmd("why.toggle", "Why this summary: open or close", ["w"], "General"),
  cmd("density.next", "Next row density", ["d"], "Table"),
  cmd("text.bigger", "Larger text", ["+"], "Table"),
  cmd("text.smaller", "Smaller text", ["-"], "Table"),
  cmd("undo", "Undo the last destructive action", ["mod+z"], "General"),
  cmd("grid.up", "Move up a row", ["up", "k"], "Grid", "grid"),
  cmd("grid.down", "Move down a row", ["down", "j"], "Grid", "grid"),
  cmd("grid.left", "Move left a cell", ["left"], "Grid", "grid"),
  cmd("grid.right", "Move right a cell", ["right"], "Grid", "grid"),
  cmd("grid.rowStart", "First column", ["home"], "Grid", "grid"),
  cmd("grid.rowEnd", "Last column", ["end"], "Grid", "grid"),
  cmd("grid.pageUp", "Up ten rows", ["pageup"], "Grid", "grid"),
  cmd("grid.pageDown", "Down ten rows", ["pagedown"], "Grid", "grid"),
  cmd("overlay.close", "Close the top-most panel", ["esc"], "General"),
  // Palette only.
  cmd("peers.save", "Save peer set", [], "Peers"),
  cmd("peers.restore", "Restore system peers", [], "Peers"),
  cmd("peers.addAdjacent", "Add adjacent-subsector peers", [], "Peers"),
  cmd("layout.save", "Save layout", [], "Table"),
  cmd("summary.copy", "Copy summary", [], "Export"),
  cmd("primary.reset", "Reset primary", [], "Charts"),
  cmd("method.open", "Show methodology", [], "General"),
  // Revision 3 (12.10). `peer.add` (a) now opens the peer drawer at its search box.
  cmd("peers.edit", "Edit peers", [], "Peers"),
  cmd("sources.open", "Sources and method", [], "General"),
  cmd("forecast.open", "Open the peer-multiple value on the Forecast tab", [], "General"),
  cmd("catalysts.open", "Open the Catalysts tab", [], "General"),
  cmd("singlekeys.toggle", "Turn single-key shortcuts on or off", [], "General"),
  cmd("reload", "Reload the comps", [], "General"),
];
export const COMMAND_BY_ID = Object.fromEntries(COMMANDS.map((c) => [c.id, c]));

/** Normalised key string -> command id. Built from COMMANDS; no key is bound twice. */
export const KEYMAP = (() => {
  const m = {};
  for (const c of COMMANDS) for (const k of c.keys) {
    if (Object.prototype.hasOwnProperty.call(m, k)) throw new Error(`Key ${k} bound twice`);
    m[k] = c.id;
  }
  return m;
})();
/** Keys a focused grid or chart consumes; they stay active whatever the single-key setting. */
export const GRID_KEYS = ["up", "down", "left", "right", "home", "end", "pageup", "pagedown", "enter",
  "shift+enter", "j", "k", "o", "s", "x", "shift+x", "delete"];

const NAMED_KEYS = {Escape: "esc", Esc: "esc", Enter: "enter", Delete: "delete", Backspace: "backspace",
  ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", Home: "home", End: "end",
  PageUp: "pageup", PageDown: "pagedown", Tab: "tab", " ": "space", Spacebar: "space"};

export function normKey(event, isMac = false) {
  const e = event || {};
  const mod = isMac ? !!e.metaKey : !!e.ctrlKey;
  let prefix = (mod ? "mod+" : "") + (e.altKey ? "alt+" : "");
  const k = e.key == null ? "" : String(e.key);
  if (NAMED_KEYS[k]) return prefix + (e.shiftKey ? "shift+" : "") + NAMED_KEYS[k];
  if (k.length === 1) {
    if (/[a-z]/i.test(k)) return prefix + (e.shiftKey ? "shift+" : "") + k.toLowerCase();
    return prefix + k;
  }
  return prefix + (e.shiftKey ? "shift+" : "") + k.toLowerCase();
}

/**
 * `handleKey(state, keyString, focusZone)` -> command id | null. focusZone is "grid", "chart",
 * "input" or anything else. Grid commands need the grid; single-key commands obey
 * state.singleKeys; mod+k, esc and mod+z always work.
 */
export function handleKey(state, keyString, focusZone) {
  const id = KEYMAP[keyString];
  if (!id) return null;
  const c = COMMAND_BY_ID[id];
  if (!c) return null;
  if (c.when === "grid") return focusZone === "grid" ? id : null;
  if (isSingleKeyBinding(keyString) && state && state.singleKeys === false) return null;
  return id;
}

/** Shortcut hint for a command, hidden for single keys while they are off. */
export function commandHint(state, c, isMac = false) {
  if (!c || !c.key) return "";
  if (c.singleKey && state && state.singleKeys === false) return "";
  return keyLabel(c.key, isMac);
}

const KEY_WORDS = {esc: "Esc", enter: "Enter", delete: "Delete", up: "↑", down: "↓", left: "←",
  right: "→", home: "Home", end: "End", pageup: "Page up", pagedown: "Page down", tab: "Tab", space: "Space"};
/** Display form of a normalised key: "mod+k" -> "⌘K" on macOS, "Ctrl K" elsewhere; "shift+x" -> "Shift X". */
export function keyLabel(key, isMac = false) {
  if (!key) return "";
  const parts = String(key).split("+");
  const base = parts.pop() || "+";
  const words = parts.filter(Boolean).map((m) => (m === "mod" ? (isMac ? "⌘" : "Ctrl") : m === "alt" ? (isMac ? "⌥" : "Alt") : m === "shift" ? "Shift" : m));
  const k = KEY_WORDS[base] || (base.length === 1 ? base.toUpperCase() : base);
  if (isMac && words.length && words.every((w) => w === "⌘" || w === "⌥")) return words.join("") + k;
  return words.concat([k]).join(" ");
}

/**
 * `matchCommands(query, commands, extra)`: fuzzy subsequence match over labels. Score 3 for a
 * prefix, 2 for a word start, 1 for any other subsequence; ties keep list order.
 */
function wordPrefixes(q, label) {
  const qs = q.split(/\s+/).filter(Boolean);
  const ws = label.split(/[\s,:()]+/).filter(Boolean);
  let j = 0;
  for (const t of qs) {
    while (j < ws.length && !ws[j].startsWith(t)) j++;
    if (j >= ws.length) return false;
    j++;
  }
  return qs.length > 0;
}
export function matchCommands(query, commands = COMMANDS, extra = []) {
  const list = (commands || []).concat(extra || []);
  const q = String(query || "").trim().toLowerCase();
  if (!q) return list.slice();
  const scored = [];
  list.forEach((item, i) => {
    const label = String(item.label || "").toLowerCase();
    let score = 0;
    if (label.startsWith(q)) score = 3;
    else if (label.includes(" " + q) || wordPrefixes(q, label)) score = 2;
    else {
      let pos = 0, ok = true;
      for (const ch of q) {
        if (ch === " ") continue;
        const j = label.indexOf(ch, pos);
        if (j < 0) { ok = false; break; }
        pos = j + 1;
      }
      if (ok) score = 1;
    }
    if (score) scored.push({item, score, i});
  });
  scored.sort((a, b) => (b.score - a.score) || (a.i - b.i));
  return scored.map((s) => ({...s.item, score: s.score}));
}

// ---------------------------------------------------------------------------------------------
// 3.15 State, reducer and persistence
// ---------------------------------------------------------------------------------------------

const TABLE_KEYS = ["preset", "customColumns", "hidden", "pinned", "widths", "sort", "filters", "cfMode",
  "density", "textSize", "summaryRows", "summaryExpanded", "chartStrip"];
const LAYOUT_KEYS = ["preset", "customColumns", "hidden", "pinned", "widths", "cfMode", "density", "textSize", "summaryRows"];
const UNDO_KEYS = ["peerEdits", "activeSet", "savedSets", "subgroups", "filters", "layouts", "customColumns",
  "hidden", "pinned", "widths", "sort", "preset", "excluded", "statsGroup"];
export const CF_MODES = ["off", "premium", "percentile", "trend", "quality", "outliers"];
export const CF_MODE_LABEL = {off: "Off", premium: "Premium or discount to median", percentile: "Percentile rank",
  trend: "Operating trend", quality: "Data quality", outliers: "Outliers"};
export const DENSITIES = ["compact", "default", "comfortable"];
export const TEXT_SIZES = [13, 14, 15];
export const SYSTEM_SUBGROUPS = ["US", "Europe", "IFRS filers", "US GAAP filers", "Commercial", "Clinical"];
const FILTER_OPS = [">=", "<=", "has", "text"];
const DEFAULT_SCATTER = {x: null, y: null, size: "market_cap", trend: true, colorBy: "none", logY: false};
const MAX_PINS = {ultrawide: 2, wide: 2, laptop: 1, narrow: 0};

function pick(obj, keys) { const o = {}; for (const k of keys) if (obj && obj[k] !== undefined) o[k] = obj[k]; return o; }
function isoOf(now) {
  if (isNum(now)) { try { return new Date(now).toISOString(); } catch (e) { return String(now); } }
  return now == null ? "" : String(now);
}

function defaultTableSettings(engine) {
  return {preset: PRESET_BY_ID[engine] ? engine : "core", customColumns: [], hidden: [], pinned: [], widths: {},
    sort: null, filters: [], cfMode: "off", density: "default", textSize: 13, summaryRows: true,
    summaryExpanded: {}, chartStrip: {}};
}
function defaultPersisted() {
  return {version: 1, byEngine: {}, basis: "NTM", currency: "USD", earnings: "reported", peerEdits: {},
    activeSet: "system", savedSets: {}, subgroups: {}, statsGroup: "all", outliers: "include",
    primaryOverride: {}, scatter: {...DEFAULT_SCATTER}, layouts: {}, singleKeys: true, bridge: {}, notes: {}, cohorts: []};
}

function cleanCols(arr) { return Array.isArray(arr) ? uniq(arr.filter((c) => typeof c === "string" && COLUMN_BY_ID[c])) : []; }
function cleanTable(s, engine) {
  const o = defaultTableSettings(engine);
  if (!s || typeof s !== "object") return {...o, dotMetric: null};
  if (PRESET_IDS.includes(s.preset)) o.preset = s.preset;
  o.customColumns = cleanCols(s.customColumns);
  o.hidden = cleanCols(s.hidden);
  o.pinned = cleanCols(s.pinned).slice(0, 2);
  o.widths = {};
  if (s.widths && typeof s.widths === "object") {
    for (const [k, v] of Object.entries(s.widths)) if ((COLUMN_BY_ID[k] || FROZEN_IDS.has(k)) && isNum(v)) o.widths[k] = clamp(Math.round(v), 56, 320);
  }
  o.sort = s.sort && COLUMN_BY_ID[s.sort.colId] && (s.sort.dir === "asc" || s.sort.dir === "desc") ? {colId: s.sort.colId, dir: s.sort.dir} : null;
  o.filters = Array.isArray(s.filters) ? s.filters.filter((f) => f && COLUMN_BY_ID[f.colId] && FILTER_OPS.includes(f.op))
    .map((f) => ({colId: f.colId, op: f.op, value: f.value})) : [];
  if (CF_MODES.includes(s.cfMode)) o.cfMode = s.cfMode;
  if (DENSITIES.includes(s.density)) o.density = s.density;
  if (TEXT_SIZES.includes(s.textSize)) o.textSize = s.textSize;
  if (typeof s.summaryRows === "boolean") o.summaryRows = s.summaryRows;
  if (s.summaryExpanded && typeof s.summaryExpanded === "object") {
    for (const [k, v] of Object.entries(s.summaryExpanded)) if (typeof v === "boolean") o.summaryExpanded[k] = v;
  }
  if (s.chartStrip && typeof s.chartStrip === "object") {
    for (const [k, v] of Object.entries(s.chartStrip)) if (v === "open" || v === "collapsed") o.chartStrip[k] = v;
  }
  return {...o, dotMetric: METRIC_CANDIDATES.includes(s.dotMetric) ? s.dotMetric : null};
}
function cleanBridge(b) {
  if (!b || typeof b !== "object") return null;
  const o = {};
  if (BRIDGEABLE.includes(b.colId)) o.colId = b.colId;
  if (BASES.includes(b.basis)) o.basis = b.basis;
  if (["median", "mean", "p25", "p75", "pct"].includes(b.stat)) o.stat = b.stat;
  if (isNum(b.pct)) o.pct = clamp(b.pct, 0, 100);
  for (const k of ["multipleOverride", "metricOverride", "netDebtOverride", "sharesOverride", "otherClaimsOverride"]) {
    if (isNum(b[k])) o[k] = b[k];
  }
  if (["market_cap", "diluted", "analyst"].includes(b.sharesSource)) o.sharesSource = b.sharesSource;
  if (typeof b.otherClaimsOn === "boolean") o.otherClaimsOn = b.otherClaimsOn;
  return o;
}

/**
 * `migrateState(raw, tickers?)` -> PersistedState. An unknown version gives the defaults; unknown
 * column ids are dropped, and so are unknown tickers when the universe's `tickers` are given;
 * a primary override outside PREMIUM_METRICS is cleared.
 */
export function migrateState(raw, tickers = null) {
  const d = defaultPersisted();
  if (!raw || typeof raw !== "object" || raw.version !== 1) return d;
  const T = tickers ? new Set(tickers) : null;
  const okT = (t) => typeof t === "string" && t.length > 0 && (!T || T.has(t));
  const tl = (arr) => (Array.isArray(arr) ? uniq(arr.filter(okT)) : []);
  if (raw.byEngine && typeof raw.byEngine === "object") {
    for (const [e, s] of Object.entries(raw.byEngine)) d.byEngine[e] = cleanTable(s, e);
  }
  if (BASES.includes(raw.basis)) d.basis = raw.basis;
  if (CURRENCIES.includes(raw.currency)) d.currency = raw.currency;
  if (raw.earnings === "reported" || raw.earnings === "adjusted") d.earnings = raw.earnings;
  if (raw.peerEdits && typeof raw.peerEdits === "object") {
    for (const [f, ed] of Object.entries(raw.peerEdits)) {
      if (!okT(f) || !ed || typeof ed !== "object") continue;
      const notes = {};
      if (ed.notes && typeof ed.notes === "object") for (const [t, s] of Object.entries(ed.notes)) if (okT(t) && typeof s === "string") notes[t] = s;
      d.peerEdits[f] = {added: tl(ed.added), removed: tl(ed.removed), notes};
    }
  }
  if (raw.savedSets && typeof raw.savedSets === "object") {
    for (const [name, s] of Object.entries(raw.savedSets)) {
      if (!name || !s || typeof s !== "object") continue;
      const notes = {};
      if (s.notes && typeof s.notes === "object") for (const [t, v] of Object.entries(s.notes)) if (okT(t) && typeof v === "string") notes[t] = v;
      d.savedSets[name] = {tickers: tl(s.tickers), notes, created: typeof s.created === "string" ? s.created : "",
        engine: typeof s.engine === "string" ? s.engine : ""};
    }
  }
  if (typeof raw.activeSet === "string" && (raw.activeSet === "system" ||
      (raw.activeSet.startsWith("saved:") && d.savedSets[raw.activeSet.slice(6)]))) d.activeSet = raw.activeSet;
  if (raw.subgroups && typeof raw.subgroups === "object") {
    for (const [f, groups] of Object.entries(raw.subgroups)) {
      if (!okT(f) || !groups || typeof groups !== "object") continue;
      d.subgroups[f] = {};
      for (const [name, ts] of Object.entries(groups)) if (name) d.subgroups[f][name] = tl(ts);
    }
  }
  if (typeof raw.statsGroup === "string" && raw.statsGroup) d.statsGroup = raw.statsGroup;
  if (raw.outliers === "include" || raw.outliers === "exclude") d.outliers = raw.outliers;
  if (raw.primaryOverride && typeof raw.primaryOverride === "object") {
    for (const [e, v] of Object.entries(raw.primaryOverride)) d.primaryOverride[e] = PREMIUM_METRICS.includes(v) ? v : null;
  }
  if (raw.scatter && typeof raw.scatter === "object") {
    const s = raw.scatter;
    d.scatter = {
      x: SCATTER_X_OPTIONS.includes(s.x) ? s.x : null,
      y: SCATTER_Y_OPTIONS.includes(s.y) ? s.y : null,
      size: ["market_cap", "ev", "none"].includes(s.size) ? s.size : "market_cap",
      trend: typeof s.trend === "boolean" ? s.trend : true,
      colorBy: s.colorBy === "stage" ? "stage" : "none",
      logY: typeof s.logY === "boolean" ? s.logY : false,
    };
  }
  if (raw.layouts && typeof raw.layouts === "object") {
    for (const [name, l] of Object.entries(raw.layouts)) {
      if (!name || !l || typeof l !== "object") continue;
      const t = cleanTable(l, "core");
      d.layouts[name] = {...pick(t, LAYOUT_KEYS), created: typeof l.created === "string" ? l.created : ""};
    }
  }
  if (typeof raw.singleKeys === "boolean") d.singleKeys = raw.singleKeys;
  if (raw.bridge && typeof raw.bridge === "object") {
    for (const [f, b] of Object.entries(raw.bridge)) { if (!okT(f)) continue; const c = cleanBridge(b); if (c) d.bridge[f] = c; }
  }
  if (raw.notes && typeof raw.notes === "object") {
    for (const [t, n] of Object.entries(raw.notes)) {
      if (okT(t) && n && typeof n.text === "string") d.notes[t] = {text: n.text, updated: typeof n.updated === "string" ? n.updated : ""};
    }
  }
  if (Array.isArray(raw.cohorts)) d.cohorts = raw.cohorts.filter((c) => typeof c === "string").slice(0, 3);
  return d;
}

export function defaultState(payload, args = {}, persisted = null, session = null) {
  const companies = (payload && Array.isArray(payload.companies)) ? payload.companies : [];
  const tickers = companies.map((c) => c.ticker);
  const P = migrateState(persisted, tickers.length ? tickers : null);
  const focal = (args && args.focal) || (companies[0] && companies[0].ticker) || "";
  const rec = companies.find((c) => c.ticker === focal);
  const engine = (args && args.engine) || (rec && rec.engine) || "pharma";
  const table = P.byEngine[engine] ? pick(P.byEngine[engine], TABLE_KEYS) : defaultTableSettings(engine);
  const dotMetric = {};
  for (const [e, s] of Object.entries(P.byEngine)) dotMetric[e] = s.dotMetric ?? null;
  const sess = session && typeof session === "object" ? session : {};
  const known = (t) => typeof t === "string" && (!tickers.length || tickers.includes(t));
  const excludedByFocal = {};
  if (sess.excluded && typeof sess.excluded === "object") {
    for (const [f, ts] of Object.entries(sess.excluded)) if (known(f) && Array.isArray(ts)) excludedByFocal[f] = uniq(ts.filter(known));
  }
  const byEngine = {};
  for (const [e, s] of Object.entries(P.byEngine)) byEngine[e] = pick(s, TABLE_KEYS);
  return {
    version: 1, focal, engine, live: !(args && args.live === false),
    basis: P.basis, currency: P.currency, earnings: P.earnings,
    ...defaultTableSettings(engine), ...table,
    peerEdits: P.peerEdits, activeSet: P.activeSet, savedSets: P.savedSets, subgroups: P.subgroups,
    statsGroup: P.statsGroup, excluded: excludedByFocal[focal] || [], excludedByFocal,
    outliers: P.outliers, primaryOverride: P.primaryOverride, dotMetric,
    scatter: P.scatter, layouts: P.layouts, singleKeys: P.singleKeys, bridge: P.bridge, notes: P.notes,
    cohorts: P.cohorts, byEngine,
    ui: {detail: known(sess.detail) ? sess.detail : null, why: false, method: null, focus: null,
         expanded: Array.isArray(sess.expanded) ? sess.expanded.filter(known) : [],
         peers: false, peersSearch: false, insightTab: "catalysts",
         narrowTab: "position", laptopTab: "position", overlay: null, undo: null},
  };
}

export function persistable(state) {
  const byEngine = {};
  for (const [e, s] of Object.entries(state.byEngine || {})) byEngine[e] = {...defaultTableSettings(e), ...pick(s, TABLE_KEYS), dotMetric: null};
  byEngine[state.engine] = {...pick(state, TABLE_KEYS), dotMetric: null};
  for (const [e, v] of Object.entries(state.dotMetric || {})) {
    if (!byEngine[e]) byEngine[e] = {...defaultTableSettings(e), dotMetric: null};
    byEngine[e].dotMetric = v ?? null;
  }
  const local = {version: 1, byEngine, basis: state.basis, currency: state.currency, earnings: state.earnings,
    peerEdits: state.peerEdits, activeSet: state.activeSet, savedSets: state.savedSets, subgroups: state.subgroups,
    statsGroup: state.statsGroup, outliers: state.outliers, primaryOverride: state.primaryOverride,
    scatter: state.scatter, layouts: state.layouts, singleKeys: state.singleKeys, bridge: state.bridge,
    notes: state.notes, cohorts: state.cohorts};
  const excluded = {...(state.excludedByFocal || {}), [state.focal]: state.excluded || []};
  return {local, session: {excluded, detail: state.ui ? state.ui.detail : null, expanded: state.ui ? state.ui.expanded : []}};
}

/** Columns of the current preset (the analyst's list for Custom). */
export function presetColumns(state) {
  if (state.preset === "custom") return (state.customColumns || []).slice();
  return ((PRESET_BY_ID[state.preset] || PRESET_BY_ID.core).columns).slice();
}

/** Current peer set for the state's focal: the system or saved base with the analyst's edits. */
export function peerSetTickers(payload, state) {
  const companies = (payload && payload.companies) || [];
  const byT = Object.fromEntries(companies.map((c) => [c.ticker, c]));
  const focalRec = byT[state.focal];
  if (!focalRec) return {tickers: [], base: [], added: [], removed: [], source: "system", savedName: null, def: null, edited: false};
  const def = defaultPeers(focalRec, companies);
  const savedName = typeof state.activeSet === "string" && state.activeSet.startsWith("saved:") ? state.activeSet.slice(6) : null;
  const saved = savedName && state.savedSets ? state.savedSets[savedName] : null;
  const base = saved ? saved.tickers.filter((t) => t !== state.focal && byT[t]) : def.tickers.slice();
  const ed = (state.peerEdits || {})[state.focal] || {};
  const removed = new Set(ed.removed || []);
  const added = (ed.added || []).filter((t) => t !== state.focal && byT[t] && !base.includes(t));
  const tickers = base.filter((t) => !removed.has(t)).concat(added.filter((t) => !removed.has(t)));
  const edited = added.length > 0 || base.some((t) => removed.has(t));
  return {tickers, base, added, removed: [...removed], source: saved ? "saved" : "system", savedName: saved ? savedName : null, def, edited};
}

/** Whether a column can be pinned: at most 2 pins wide, 1 laptop, 0 narrow, within the 40 % budget. */
export function canPin(state, colId, opts = {}) {
  const reason = "Pinned columns would cover more than 40% of the table. Unpin one first.";
  if (!COLUMN_BY_ID[colId]) return {ok: false, reason: "Unknown column."};
  if ((state.pinned || []).includes(colId)) return {ok: false, reason: "Already pinned."};
  const layout = opts.layout || "wide";
  const max = MAX_PINS[layout] ?? 2;
  if ((state.pinned || []).length >= max) return {ok: false, reason};
  if (isNum(opts.boxWidth)) {
    const w = (id) => (state.widths && state.widths[id]) || (COLUMN_BY_ID[id] && COLUMN_BY_ID[id].width) || 84;
    const baseW = FROZEN_BASE_WIDTH[layout] || 332;
    const total = baseW + (state.pinned || []).reduce((s, id) => s + w(id), 0) + w(colId);
    if (total > FROZEN_MAX_SHARE * opts.boxWidth) return {ok: false, reason};
  }
  return {ok: true, reason: null};
}

function patch(state, p) {
  for (const k of Object.keys(p)) if (state[k] !== p[k]) return {...state, ...p};
  return state;
}
function patchUi(state, p) {
  const ui = state.ui || {};
  for (const k of Object.keys(p)) if (ui[k] !== p[k]) return {...state, ui: {...ui, ...p}};
  return state;
}
function withUndo(prev, next, label, now) {
  if (next === prev) return prev;
  return {...next, ui: {...next.ui, undo: {label, before: pick(prev, UNDO_KEYS), at: isNum(now) ? now : null}}};
}
function nextIn(list, v, dir = 1) {
  const i = list.indexOf(v);
  return list[((i < 0 ? 0 : i) + (dir < 0 ? -1 : 1) + list.length) % list.length];
}
function editsFor(state) {
  const ed = (state.peerEdits || {})[state.focal] || {};
  return {added: (ed.added || []).slice(), removed: (ed.removed || []).slice(), notes: {...(ed.notes || {})}};
}
function withEdits(state, ed) { return {...state, peerEdits: {...state.peerEdits, [state.focal]: ed}}; }
function switchEngine(state, engine) {
  const byEngine = {...(state.byEngine || {}), [state.engine]: pick(state, TABLE_KEYS)};
  const settings = {...defaultTableSettings(engine), ...(byEngine[engine] ? pick(byEngine[engine], TABLE_KEYS) : {})};
  return {...state, ...settings, engine, byEngine};
}

/**
 * ADOPT_PERSISTED {local, session} (12.5): what another frame of this origin stored replaces every
 * persisted slice; `focal`, `engine`, `live` and `ui` stay. A null `local` or `session` leaves its
 * slices as they are. Returns the same state when nothing differs.
 */
function adoptPersisted(state, a, payload) {
  const companies = (payload && payload.companies) || [];
  const tickers = companies.map((c) => c.ticker);
  const known = (t) => typeof t === "string" && (!tickers.length || tickers.includes(t));
  let next = state;
  // A blob of another version is not adopted: migrateState would answer with the defaults.
  if (a.local && typeof a.local === "object" && a.local.version === 1) {
    const P = migrateState(a.local, tickers.length ? tickers : null);
    const byEngine = {};
    for (const [e, s] of Object.entries(P.byEngine)) byEngine[e] = pick(s, TABLE_KEYS);
    const dotMetric = {};
    for (const [e, s] of Object.entries(P.byEngine)) dotMetric[e] = s.dotMetric ?? null;
    const table = {...defaultTableSettings(state.engine), ...(byEngine[state.engine] || {})};
    next = {...next, ...table, basis: P.basis, currency: P.currency, earnings: P.earnings, peerEdits: P.peerEdits,
      activeSet: P.activeSet, savedSets: P.savedSets, subgroups: P.subgroups, statsGroup: P.statsGroup,
      outliers: P.outliers, primaryOverride: P.primaryOverride, dotMetric, scatter: P.scatter, layouts: P.layouts,
      singleKeys: P.singleKeys, bridge: P.bridge, notes: P.notes, cohorts: P.cohorts, byEngine};
  }
  if (a.session && typeof a.session === "object") {
    const excludedByFocal = {};
    if (a.session.excluded && typeof a.session.excluded === "object") {
      for (const [f, ts] of Object.entries(a.session.excluded)) if (known(f) && Array.isArray(ts)) excludedByFocal[f] = uniq(ts.filter(known));
    }
    next = {...next, excludedByFocal, excluded: excludedByFocal[state.focal] || []};
  }
  if (next === state) return state;
  const sig = (st) => { const p = persistable(st); return JSON.stringify([p.local, p.session.excluded]); };
  return sig(next) === sig(state) ? state : next;
}

/**
 * `mergeBridge(storedLocal, focal, inputs)` (12.5): the stored local blob (an object, its JSON
 * text, or nothing) with `bridge[focal]` replaced by `inputs`, and nothing else changed. Empty or
 * null `inputs` removes the entry. The bridge frame writes this back, never its whole state.
 */
export function mergeBridge(storedLocal, focal, inputs) {
  let blob = storedLocal;
  if (typeof blob === "string") { try { blob = JSON.parse(blob); } catch (e) { blob = null; } }
  if (!blob || typeof blob !== "object" || Array.isArray(blob) || blob.version !== 1) blob = {version: 1};
  const bridgeMap = {...(blob.bridge && typeof blob.bridge === "object" ? blob.bridge : {})};
  const clean = cleanBridge(inputs);
  if (focal) {
    if (clean && Object.keys(clean).length) bridgeMap[focal] = clean; else delete bridgeMap[focal];
  }
  return {...blob, bridge: bridgeMap};
}

export function reduce(state, action, payload = null) {
  if (!state || !action || !action.type) return state;
  const a = action;
  const companies = (payload && payload.companies) || [];
  const has = (t) => !payload || companies.some((c) => c.ticker === t);
  switch (a.type) {
    case "SET_FOCAL": {
      const t = a.ticker;
      if (!t || t === state.focal || !has(t)) return state;
      const rec = companies.find((c) => c.ticker === t);
      const excludedByFocal = {...(state.excludedByFocal || {}), [state.focal]: state.excluded || []};
      const subgroupsNew = (state.subgroups || {})[t] || {};
      const statsGroup = state.statsGroup === "all" || SYSTEM_SUBGROUPS.includes(state.statsGroup) || subgroupsNew[state.statsGroup] ? state.statsGroup : "all";
      let next = {...state, focal: t, excludedByFocal, excluded: excludedByFocal[t] || [], statsGroup,
        ui: {...state.ui, detail: state.ui.detail === t ? null : state.ui.detail, why: false, focus: null, expanded: [], overlay: null, undo: null}};
      const eng = rec && rec.engine;
      if (eng && eng !== state.engine) next = switchEngine(next, eng);
      return next;
    }
    case "SET_BASIS": return BASES.includes(a.basis) ? patch(state, {basis: a.basis}) : state;
    case "CYCLE_BASIS": return patch(state, {basis: nextIn(BASES, state.basis, a.dir)});
    case "SET_CURRENCY": return CURRENCIES.includes(a.currency) ? patch(state, {currency: a.currency}) : state;
    case "CYCLE_CURRENCY": return patch(state, {currency: nextIn(CURRENCIES, state.currency, a.dir)});
    case "SET_EARNINGS": return a.earnings === "reported" || a.earnings === "adjusted" ? patch(state, {earnings: a.earnings}) : state;
    case "TOGGLE_EARNINGS": return patch(state, {earnings: state.earnings === "adjusted" ? "reported" : "adjusted"});
    case "SET_PRESET": {
      if (!PRESET_IDS.includes(a.preset)) return state;
      if (a.preset === state.preset) return state;
      if (a.preset === "custom" && !(state.customColumns || []).length) {
        return {...state, preset: "custom", customColumns: presetColumns(state)};
      }
      return patch(state, {preset: a.preset});
    }
    case "SET_CUSTOM_COLUMNS": {
      const ids = cleanCols(a.ids);
      if (state.preset === "custom" && shallowEqualArr(ids, state.customColumns)) return state;
      return {...state, preset: "custom", customColumns: ids};
    }
    case "HIDE_COLUMN": {
      const cols = presetColumns(state);
      if (!cols.includes(a.colId)) return state;
      return {...state, preset: "custom", customColumns: cols.filter((c) => c !== a.colId),
        hidden: uniq((state.hidden || []).concat([a.colId])), pinned: (state.pinned || []).filter((c) => c !== a.colId)};
    }
    case "SHOW_COLUMN": {
      if (!COLUMN_BY_ID[a.colId]) return state;
      const cols = presetColumns(state);
      const hidden = (state.hidden || []).filter((c) => c !== a.colId);
      if (cols.includes(a.colId)) return hidden.length === (state.hidden || []).length ? state : {...state, hidden};
      return {...state, preset: "custom", customColumns: cols.concat([a.colId]), hidden};
    }
    case "PIN_COLUMN": {
      const chk = canPin(state, a.colId, {layout: a.layout, boxWidth: a.boxWidth});
      if (!chk.ok) return state;
      return {...state, pinned: (state.pinned || []).concat([a.colId])};
    }
    case "UNPIN_COLUMN": {
      if (!(state.pinned || []).includes(a.colId)) return state;
      return {...state, pinned: state.pinned.filter((c) => c !== a.colId)};
    }
    case "MOVE_COLUMN": {
      const cols = presetColumns(state);
      const i = cols.indexOf(a.colId);
      const d = a.dir === "left" || a.dir === -1 ? -1 : 1;
      const j = i + d;
      if (i < 0 || j < 0 || j >= cols.length) return state;
      const next = cols.slice();
      [next[i], next[j]] = [next[j], next[i]];
      return {...state, preset: "custom", customColumns: next};
    }
    case "RESIZE_COLUMN": {
      if (!COLUMN_BY_ID[a.colId] && !FROZEN_IDS.has(a.colId)) return state;
      const w = clamp(Math.round(Number(a.width) || 0), 56, 320);
      if ((state.widths || {})[a.colId] === w) return state;
      return {...state, widths: {...(state.widths || {}), [a.colId]: w}};
    }
    case "RESET_LAYOUT": {
      const next = patch(state, {hidden: [], pinned: [], widths: {}, sort: null});
      const unchanged = !(state.hidden || []).length && !(state.pinned || []).length && !Object.keys(state.widths || {}).length && !state.sort;
      return unchanged ? state : withUndo(state, next, "Reset the column layout", a.now);
    }
    case "SORT": {
      if (!COLUMN_BY_ID[a.colId] && a.colId !== "company" && a.colId !== "ticker" && a.colId !== "rel") return state;
      const s = state.sort;
      let sort;
      if (!s || s.colId !== a.colId) sort = {colId: a.colId, dir: "desc"};
      else if (s.dir === "desc") sort = {colId: a.colId, dir: "asc"};
      else sort = null;
      return {...state, sort};
    }
    case "SET_FILTER": {
      const f = a.filter;
      if (!f || !COLUMN_BY_ID[f.colId] || !FILTER_OPS.includes(f.op)) return state;
      const rest = (state.filters || []).filter((x) => x.colId !== f.colId);
      const old = (state.filters || []).find((x) => x.colId === f.colId);
      if (old && old.op === f.op && old.value === f.value) return state;
      return {...state, filters: rest.concat([{colId: f.colId, op: f.op, value: f.value}])};
    }
    case "REMOVE_FILTER": {
      if (!(state.filters || []).some((x) => x.colId === a.colId)) return state;
      return {...state, filters: state.filters.filter((x) => x.colId !== a.colId)};
    }
    case "CLEAR_FILTERS": {
      const n = (state.filters || []).length;
      if (!n) return state;
      return withUndo(state, {...state, filters: []}, `Cleared ${n} ${plural(n, "filter", "filters")}`, a.now);
    }
    case "ADD_PEER": {
      const t = a.ticker;
      if (!t || t === state.focal || !has(t)) return state;
      const info = payload ? peerSetTickers(payload, state) : null;
      if (info && info.tickers.includes(t)) return state;
      const ed = editsFor(state);
      if (ed.removed.includes(t)) ed.removed = ed.removed.filter((x) => x !== t);
      if (!info || !info.base.includes(t)) ed.added = uniq(ed.added.concat([t]));
      return withEdits(state, ed);
    }
    case "ADD_POOL_C": {
      if (!payload) return state;
      const focalRec = companies.find((c) => c.ticker === state.focal);
      if (!focalRec) return state;
      const info = peerSetTickers(payload, state);
      const cands = adjacentCandidates(focalRec, companies).filter((c) => !info.tickers.includes(c.ticker));
      if (!cands.length) return state;
      const room = Math.max(0, MAX_DEFAULT_PEERS - info.tickers.length);
      let take = cands.filter((c) => c.score >= MIN_DEFAULT_RELEVANCE).slice(0, room);
      if (info.tickers.length + take.length < 5) take = cands.slice(0, Math.max(5 - info.tickers.length, take.length));
      if (!take.length) return state;
      const ed = editsFor(state);
      const ts = take.map((c) => c.ticker);
      ed.removed = ed.removed.filter((x) => !ts.includes(x));
      ed.added = uniq(ed.added.concat(ts.filter((t) => !info.base.includes(t))));
      return withEdits(state, ed);
    }
    case "REMOVE_PEER": {
      const t = a.ticker;
      const info = payload ? peerSetTickers(payload, state) : null;
      if (info && !info.tickers.includes(t)) return state;
      const ed = editsFor(state);
      if (ed.added.includes(t)) ed.added = ed.added.filter((x) => x !== t);
      if (!info || info.base.includes(t)) ed.removed = uniq(ed.removed.concat([t]));
      return withUndo(state, withEdits(state, ed), `Removed ${t} from peers`, a.now);
    }
    case "TOGGLE_EXCLUDE": {
      const t = a.ticker;
      if (!t || t === state.focal) return state;
      const ex = state.excluded || [];
      return {...state, excluded: ex.includes(t) ? ex.filter((x) => x !== t) : ex.concat([t])};
    }
    case "SET_OUTLIERS": return a.mode === "include" || a.mode === "exclude" ? patch(state, {outliers: a.mode}) : state;
    case "TOGGLE_OUTLIERS": return patch(state, {outliers: state.outliers === "exclude" ? "include" : "exclude"});
    case "SET_PRIMARY": {
      const v = a.colId == null ? null : a.colId;
      if (v !== null && !PREMIUM_METRICS.includes(v)) return state;
      if ((state.primaryOverride || {})[state.engine] === v || ((state.primaryOverride || {})[state.engine] == null && v === null)) return state;
      return {...state, primaryOverride: {...(state.primaryOverride || {}), [state.engine]: v}};
    }
    case "SET_DOT_METRIC": {
      const v = a.colId == null ? null : a.colId;
      if (v !== null && !METRIC_CANDIDATES.includes(v)) return state;
      if (((state.dotMetric || {})[state.engine] ?? null) === v) return state;
      return {...state, dotMetric: {...(state.dotMetric || {}), [state.engine]: v}};
    }
    case "SET_SCATTER": {
      const s = {...state.scatter};
      if (a.x !== undefined && (a.x === null || SCATTER_X_OPTIONS.includes(a.x))) s.x = a.x;
      if (a.y !== undefined && (a.y === null || SCATTER_Y_OPTIONS.includes(a.y))) s.y = a.y;
      if (["market_cap", "ev", "none"].includes(a.size)) s.size = a.size;
      if (typeof a.trend === "boolean") s.trend = a.trend;
      if (a.colorBy === "none" || a.colorBy === "stage") s.colorBy = a.colorBy;
      if (typeof a.logY === "boolean") s.logY = a.logY;
      for (const k of Object.keys(s)) if (s[k] !== state.scatter[k]) return {...state, scatter: s};
      return state;
    }
    case "SET_CF_MODE": return CF_MODES.includes(a.mode) ? patch(state, {cfMode: a.mode}) : state;
    case "CYCLE_CF_MODE": return patch(state, {cfMode: nextIn(CF_MODES, state.cfMode, a.dir)});
    case "CYCLE_DENSITY": return patch(state, {density: nextIn(DENSITIES, state.density, 1)});
    case "SET_DENSITY": return DENSITIES.includes(a.density) ? patch(state, {density: a.density}) : state;
    case "SET_TEXT_SIZE": {
      const target = isNum(a.size) ? a.size : (state.textSize || 13) + (a.delta || 0);
      return patch(state, {textSize: clamp(Math.round(target), 13, 15)});
    }
    case "TOGGLE_SUMMARY_ROWS": return {...state, summaryRows: !state.summaryRows};
    case "TOGGLE_SUMMARY_EXPANDED": {
      const l = a.layout || "laptop";
      return {...state, summaryExpanded: {...(state.summaryExpanded || {}), [l]: !(state.summaryExpanded || {})[l]}};
    }
    case "SET_CHART_STRIP": {
      if (a.value !== "open" && a.value !== "collapsed") return state;
      if ((state.chartStrip || {})[a.layout] === a.value) return state;
      return {...state, chartStrip: {...(state.chartStrip || {}), [a.layout]: a.value}};
    }
    case "SAVE_LAYOUT": {
      const name = String(a.name || "").trim();
      if (!name) return state;
      return {...state, layouts: {...(state.layouts || {}), [name]: {...pick(state, LAYOUT_KEYS), created: isoOf(a.now)}}};
    }
    case "LOAD_LAYOUT": {
      const l = (state.layouts || {})[a.name];
      if (!l) return state;
      return patch(state, pick(l, LAYOUT_KEYS));
    }
    case "DELETE_LAYOUT": {
      if (!(state.layouts || {})[a.name]) return state;
      const layouts = {...state.layouts}; delete layouts[a.name];
      return withUndo(state, {...state, layouts}, `Deleted layout '${a.name}'`, a.now);
    }
    case "SAVE_SET": {
      const name = String(a.name || "").trim();
      if (!name || !payload) return state;
      const info = peerSetTickers(payload, state);
      const ed = editsFor(state);
      const savedSets = {...(state.savedSets || {}), [name]: {tickers: info.tickers.slice(), notes: {...ed.notes},
        created: isoOf(a.now), engine: state.engine}};
      return {...state, savedSets, activeSet: `saved:${name}`,
        peerEdits: {...state.peerEdits, [state.focal]: {added: [], removed: [], notes: ed.notes}}};
    }
    case "LOAD_SET": {
      if (!(state.savedSets || {})[a.name]) return state;
      const ed = editsFor(state);
      if (state.activeSet === `saved:${a.name}` && !ed.added.length && !ed.removed.length) return state;
      return {...state, activeSet: `saved:${a.name}`, peerEdits: {...state.peerEdits, [state.focal]: {added: [], removed: [], notes: ed.notes}}};
    }
    case "DELETE_SET": {
      if (!(state.savedSets || {})[a.name]) return state;
      const savedSets = {...state.savedSets}; delete savedSets[a.name];
      const activeSet = state.activeSet === `saved:${a.name}` ? "system" : state.activeSet;
      return withUndo(state, {...state, savedSets, activeSet}, `Deleted peer set '${a.name}'`, a.now);
    }
    case "RESTORE_SYSTEM": {
      const ed = editsFor(state);
      if (state.activeSet === "system" && !ed.added.length && !ed.removed.length) return state;
      const next = {...state, activeSet: "system", peerEdits: {...state.peerEdits, [state.focal]: {added: [], removed: [], notes: ed.notes}}};
      return withUndo(state, next, "Restored system peers", a.now);
    }
    case "SET_SUBGROUP": {
      const name = String(a.name || "").trim();
      if (!name || SYSTEM_SUBGROUPS.includes(name)) return state;
      const mine = {...((state.subgroups || {})[state.focal] || {}), [name]: uniq((a.tickers || []).filter((t) => typeof t === "string"))};
      return {...state, subgroups: {...(state.subgroups || {}), [state.focal]: mine}};
    }
    case "DELETE_SUBGROUP": {
      const mine = {...((state.subgroups || {})[state.focal] || {})};
      if (!mine[a.name]) return state;
      delete mine[a.name];
      const next = {...state, subgroups: {...state.subgroups, [state.focal]: mine}, statsGroup: state.statsGroup === a.name ? "all" : state.statsGroup};
      return withUndo(state, next, `Deleted subgroup '${a.name}'`, a.now);
    }
    case "SET_STATS_GROUP": return typeof a.group === "string" && a.group ? patch(state, {statsGroup: a.group}) : state;
    case "SET_COHORTS": {
      const ids = Array.isArray(a.ids) ? uniq(a.ids.filter((x) => typeof x === "string")).slice(0, 3) : [];
      return shallowEqualArr(ids, state.cohorts) ? state : {...state, cohorts: ids};
    }
    case "SET_PEER_NOTE": {
      const ed = editsFor(state);
      const text = String(a.text || "");
      if ((ed.notes[a.ticker] || "") === text) return state;
      if (text) ed.notes[a.ticker] = text; else delete ed.notes[a.ticker];
      return withEdits(state, ed);
    }
    case "SET_NOTE": {
      const text = String(a.text || "");
      const cur = (state.notes || {})[a.ticker];
      if ((cur ? cur.text : "") === text) return state;
      const notes = {...(state.notes || {})};
      if (text) notes[a.ticker] = {text, updated: isoOf(a.now)}; else delete notes[a.ticker];
      return {...state, notes};
    }
    case "SET_BRIDGE": {
      const cur = (state.bridge || {})[state.focal] || {};
      const p = a.patch || {};
      if (Object.keys(p).every((k) => cur[k] === p[k])) return state;
      return {...state, bridge: {...(state.bridge || {}), [state.focal]: {...cur, ...p}}};
    }
    case "RESET_BRIDGE": {
      if (!(state.bridge || {})[state.focal]) return state;
      const bridgeMap = {...state.bridge}; delete bridgeMap[state.focal];
      return {...state, bridge: bridgeMap};
    }
    case "SET_SINGLE_KEYS": return patch(state, {singleKeys: !!a.on});
    // One right-side surface at a time (12.6): the side panel, the peer drawer or the methodology drawer.
    case "OPEN_DETAIL": return a.ticker && has(a.ticker) ? patchUi(state, {detail: a.ticker, peers: false, peersSearch: false, method: null}) : state;
    case "CLOSE_DETAIL": return patchUi(state, {detail: null});
    case "FOCUS_CELL": {
      const f = state.ui.focus;
      if (f && f.row === a.row && f.col === a.col) return state;
      return patchUi(state, {focus: a.row ? {row: a.row, col: a.col} : null});
    }
    case "TOGGLE_ROW_EXPANDED": {
      const ex = state.ui.expanded || [];
      return patchUi(state, {expanded: ex.includes(a.ticker) ? ex.filter((t) => t !== a.ticker) : ex.concat([a.ticker])});
    }
    case "TOGGLE_WHY": return patchUi(state, {why: !state.ui.why});
    case "OPEN_METHOD": return patchUi(state, {method: a.anchor || "stats", detail: null, peers: false, peersSearch: false});
    case "OPEN_PEERS": return patchUi(state, {peers: true, peersSearch: !!a.search, detail: null, method: null});
    case "CLOSE_PEERS": return patchUi(state, {peers: false, peersSearch: false});
    case "SET_INSIGHT_TAB": return a.tab === "catalysts" || a.tab === "competition" ? patchUi(state, {insightTab: a.tab}) : state;
    case "ADOPT_PERSISTED": return adoptPersisted(state, a, payload);
    case "CLOSE_METHOD": return patchUi(state, {method: null});
    case "SET_NARROW_TAB": return a.tab === "position" || a.tab === "scatter" ? patchUi(state, {narrowTab: a.tab}) : state;
    case "SET_LAPTOP_TAB": return a.tab === "position" || a.tab === "scatter" ? patchUi(state, {laptopTab: a.tab}) : state;
    case "OPEN_OVERLAY": return patchUi(state, {overlay: a.overlay || null});
    case "CLOSE_OVERLAY": return patchUi(state, {overlay: null});
    case "UNDO": {
      const u = state.ui && state.ui.undo;
      if (!u) return state;
      return {...state, ...u.before, ui: {...state.ui, undo: null}};
    }
    case "EXPIRE_UNDO": {
      const u = state.ui && state.ui.undo;
      if (!u || !isNum(a.now)) return state;
      if (u.at == null) return patchUi(state, {undo: {...u, at: a.now}});
      return a.now - u.at >= UNDO_MS ? patchUi(state, {undo: null}) : state;
    }
    default: return state;
  }
}

// ---------------------------------------------------------------------------------------------
// 3.15 deriveView and its sections
// ---------------------------------------------------------------------------------------------

const PROVENANCE_WORD = {S: "sourced", C: "calc.", M: "model"};
const TREND_COLS = ["revenue_growth", "revenue_cagr3", "ebitda_growth", "eps_growth", "eps_cagr", "change_1d", "ttm_price_change"];
const BASIS_NAMES = {NTM: "NTM", FY1: "FY1", FY2: "FY2", FY0: "FY0", LTM: "LTM"};
const SUMMARY_IDS = ["mean", "median", "p25", "p75", "n"];
const SUMMARY_LABEL = {mean: "Mean", median: "Median", p25: "25th percentile", p75: "75th percentile", n: "Peers with a value"};
const MIXED_CURRENCY_TEXT = "Mixed currencies. Statistics need one currency: pick USD, EUR, GBP, CHF or DKK.";
const KPI5_TOOLTIP = "The primary multiple over the peer median, less one. For FCF yield, the peer median over the yield, less one. A premium or discount is not a verdict; see drivers and risks.";

/** Header unit text of a column: "×", "%", "USD bn", "bn, filing currency", "count". */
function unitText(c, ctx = {}) {
  if (!c || !c.unit) return "";
  if (c.unit.includes("{cur}")) {
    if (ctx.currency === "REPORTED") return c.unit.replace("{cur} ", "") + ", filing currency";
    return c.unit.replace("{cur}", ctx.currency || "USD");
  }
  return c.unit;
}
export {unitText};

function fyLabelPlus(label, k) {
  const m = /^FY(\d{4})$/.exec(label || "");
  return m ? `FY${Number(m[1]) + k}` : null;
}

function subgroupMembers(name, setRows, state) {
  const leftOut = [];
  let pickFn = null;
  switch (name) {
    case "US": case "Europe":
      pickFn = (r) => { const reg = r.record.region; if (reg == null) { leftOut.push(r.ticker); return false; } return reg === name; };
      break;
    case "IFRS filers": case "US GAAP filers": {
      const want = name === "IFRS filers" ? "IFRS" : "US GAAP";
      pickFn = (r) => { const s = get(r.record, "filer.standard"); if (s == null) { leftOut.push(r.ticker); return false; } return s === want; };
      break;
    }
    case "Commercial": pickFn = (r) => r.record.stage === "commercial"; break;
    case "Clinical": pickFn = (r) => r.record.stage === "clinical"; break;
    default: {
      const ts = (((state.subgroups || {})[state.focal]) || {})[name];
      if (!ts) return {tickers: null, leftOut};
      pickFn = (r) => ts.includes(r.ticker);
    }
  }
  return {tickers: setRows.filter(pickFn).map((r) => r.ticker), leftOut};
}

function analyse(payload, state, byTicker, focal, opts = {}) {
  const companies = payload.companies || [];
  const engineLabels = {...DEFAULT_ENGINE_LABELS, ...(get(payload, "universe.engine_labels") || {})};
  const fy0Label = get(focal, "periods.FY0.label") || null;
  const ctx = {basis: state.basis, currency: state.currency, earnings: state.earnings, fx: payload.fx || {usd_per_unit: {USD: 1}},
    fy0Label, fy1Label: get(focal, "periods.FY1.label") || fyLabelPlus(fy0Label, 1),
    fy2Label: get(focal, "periods.FY2.label") || fyLabelPlus(fy0Label, 2), engineLabels, cache: new Map(),
    stats: {outliers: state.outliers || "include", group: null}};
  const info = peerSetTickers(payload, state);
  const def = info.def;
  const edits = (state.peerEdits || {})[state.focal] || {};
  const relCache = {};
  const relOf = (t) => relCache[t] || (relCache[t] = relevance(focal, byTicker[t]));
  const setRows = info.tickers.filter((t) => byTicker[t]).map((t) => {
    const rec = byTicker[t];
    const rel = relOf(t);
    const analyst = info.added.includes(t);
    const source = analyst ? "analyst" : (info.source === "saved" ? "saved" : "system");
    const reason = source === "system" ? (def.reasons[t] || `Relevance ${rel.score}`)
      : source === "saved" ? `In saved set '${info.savedName}', relevance ${rel.score}` : `Added by you, relevance ${rel.score}`;
    return {ticker: t, record: rec, isFocal: false, excluded: (state.excluded || []).includes(t), inSet: true, source,
      pool: source === "system" ? (def.pools[t] || null) : null, reason, relevance: rel, note: (edits.notes || {})[t] || ""};
  });
  const focalRow = {ticker: focal.ticker, record: focal, isFocal: true, excluded: false, inSet: true, source: null,
    pool: null, reason: null, relevance: null, note: ""};
  const included = setRows.filter((r) => !r.excluded);
  const groupName = state.statsGroup && state.statsGroup !== "all" ? state.statsGroup : null;
  const gm = groupName ? subgroupMembers(groupName, setRows, state) : null;
  const group = gm && gm.tickers ? gm.tickers : null;
  ctx.stats.group = group;
  const statsRows = group ? included.filter((r) => group.includes(r.ticker)) : included;
  const scores = included.map((r) => r.relevance.score);
  const appropriate = scores.filter((s) => s >= MIN_DEFAULT_RELEVANCE).length;
  const medianRelevance = median(scores);
  const weak = included.length > 0 && appropriate < 5;
  const defaultWarning = info.source === "system" && !info.edited ? def.warning : null;
  const mixed = mixedModels(focal, included);
  const stds = [focal].concat(included.map((r) => r.record)).map((r) => get(r, "filer.standard"));
  const standards = {ifrs: stds.filter((s) => s === "IFRS").length, gaap: stds.filter((s) => s === "US GAAP").length};
  const override = (state.primaryOverride || {})[state.engine] || null;
  let primary = primaryMetric(focal, statsRows, ctx, override);
  let pStats = primary.colId ? peerStats(setRows, primary.colId, ctx, {focalCurrency: displayCurrency(focal, ctx)}) : null;
  if (primary.colId && pStats && (primary.state === "ok" || primary.state === "low_confidence")) {
    if (pStats.n < 2) {
      const parts = headlineParts(focal, primary.colId, ctx, []);
      primary = {...primary, state: "too_few", k: pStats.n,
        reasonText: `${focal.ticker} trades at ${parts.v} ${parts.metric} (${parts.period}). ${pStats.n === 1 ? "One peer has" : "No peer has"} a value, so there is no comparison.`};
    } else if (pStats.n < MIN_PEERS && primary.state === "ok") {
      primary = {...primary, state: "low_confidence", k: pStats.n, reasonText: lowConfidenceText(pStats.n, primary.colId)};
    }
  }
  const focalCell = primary.colId ? cell(focal, primary.colId, ctx) : null;
  const ok = focalCell && focalCell.status === "ok" && pStats;
  const prem = ok ? premium(focalCell.v, pStats.median, multipleDirection(primary.colId)) : null;
  const pct = ok ? percentileRank(focalCell.v, pStats.values) : null;
  // The bridge-only frame (12.5) draws no observations and no scatter, so they are not computed.
  const lean = !!(opts && opts.lean);
  const obs = lean ? {premium: [], discount: [], notAssessed: [], suppressed: []} : observations(focal, setRows, ctx);
  let dotCol = (state.dotMetric || {})[state.engine] || null;
  if (!dotCol || !METRIC_CANDIDATES.includes(dotCol)) {
    dotCol = primary.colId;
    if (!dotCol) dotCol = ["cash_to_mcap", "runway_months", "market_cap"].find((c) => cell(focal, c, ctx).status === "ok") || "market_cap";
  }
  const sy = (state.scatter && state.scatter.y) || (primary.colId && SCATTER_Y_OPTIONS.includes(primary.colId) ? primary.colId
    : (SCATTER_Y_OPTIONS.includes(dotCol) ? dotCol : "mcap_to_cash"));
  const sx = (state.scatter && state.scatter.x) || defaultScatterX(sy);
  const scatter = lean ? null
    : {...scatterModel(focal, setRows, sx, sy, ctx, {size: get(state, "scatter.size") || "market_cap", logY: !!get(state, "scatter.logY")}), x: sx, y: sy};
  const saved = (state.bridge || {})[state.focal] || {};
  let bcol = saved.colId || null;
  if (!bcol) {
    if (primary.colId && BRIDGEABLE.includes(primary.colId)) bcol = primary.colId;
    else bcol = BRIDGEABLE.find((c) => metricAvailability(focal, statsRows, c, ctx).enabled) || null;
  }
  const bInputs = {...BRIDGE_DEFAULTS, ...saved, colId: bcol};
  const br = bridge(focal, setRows, bInputs, ctx);
  const poolsUsed = {B: Object.values(def.pools).includes("B"), C: Object.values(def.pools).includes("C")};
  const kind = info.edited ? "edited" : info.source === "saved" ? "saved" : "system";
  const label = setLabel(state, {kind, engineLabel: engineLabels[focal.engine] || focal.engine || "Peers", stage: focal.stage,
    n: setRows.length, poolsUsed: kind === "system" ? poolsUsed : {}, savedName: info.savedName, subgroup: groupName});
  return {payload, state, ctx, focal, T: focal.ticker, type: companyType(focal), preRevenue: isPreRevenue(focal),
    byTicker, companies, info, def, setRows, focalRow, included, statsRows, group, groupName, groupLeftOut: gm ? gm.leftOut : [],
    appropriate, medianRelevance, weak, defaultWarning, weakChip: weak || !!defaultWarning, mixed, standards,
    primary, pStats, focalCell, premium: prem, pct, obs, dotCol, scatter, bridge: br, label, engineLabels,
    setKind: kind, poolsUsed};
}

function emptyView() {
  return {schema: SCHEMA, error: null, focal: null, ctx: null, header: null, conclusion: null, kpis: [], primary: null,
    scope: null, table: null, dotplot: null, scatter: null, bridge: null, observations: null, peers: null,
    method: null, detail: null, states: [], lineage: null, undo: null, sectionErrors: {}, analysis: null,
    mode: "full", insight: null, footer: null, bridgeLine: null};
}

const SECTION_NAMES = {header: "Context bar", primary: "Primary metric", conclusion: "Conclusion", kpis: "Key metrics",
  scope: "Scope line", table: "Comparable companies table", dotplot: "Peer position", scatter: "Valuation against fundamentals",
  bridge: "Valuation bridge", observations: "Drivers and risks", peers: "Peer selection", method: "Methodology",
  detail: "Side panel", states: "States", lineage: "Data sources", insight: "Drivers and risks", footer: "Sources line",
  bridgeLine: "Peer-multiple value"};

/**
 * `deriveView(payload, state, extra = {})`, `extra = {context, mode}` (12.10).
 * `context` is the focal company's comps-context body (12.2), an error context
 * `{ticker, error}`, or null while it is on its way. `mode` is "full" or "bridge": the
 * bridge-only frame of the Forecast tab gets `focal`, `ctx`, `primary`, `bridge`, `bridgeLine`,
 * the bridge's own `states` and `error`; every other section stays null.
 */
export function deriveView(payload, state, extra = {}) {
  const view = emptyView();
  const mode = extra && extra.mode === "bridge" ? "bridge" : "full";
  const context = extra && extra.context != null ? extra.context : null;
  view.mode = mode;
  if (!payload || payload.schema !== SCHEMA) {
    view.error = stateMsg("schema", {expected: SCHEMA, got: payload && payload.schema != null ? payload.schema : "none"});
    return view;
  }
  const companies = Array.isArray(payload.companies) ? payload.companies : [];
  const byTicker = Object.fromEntries(companies.map((c) => [c.ticker, c]));
  const focal = byTicker[state && state.focal];
  if (!focal) {
    view.error = stateMsg("focal_missing", {T: (state && state.focal) || "the focal company"});
    return view;
  }
  let A;
  try {
    A = analyse(payload, state, byTicker, focal, {lean: mode === "bridge"});
  } catch (e) {
    view.error = stateMsg("calc_failed_section", {section: "The comparison", message: stripStop(String(e && e.message || e))});
    view.error.where = ["frame"];
    return view;
  }
  view.analysis = A;
  view.focal = {ticker: focal.ticker, name: focal.name || focal.ticker, type: A.type, preRevenue: A.preRevenue, record: focal};
  const section = (id, fn) => {
    try { view[id] = fn(); } catch (e) {
      view[id] = id === "kpis" || id === "states" ? [] : null;
      view.sectionErrors[id] = stateMsg("calc_failed_section", {section: SECTION_NAMES[id] || id, message: stripStop(String(e && e.message || e))}, {where: [id]});
    }
  };
  section("ctx", () => buildCtx(A));
  if (mode === "bridge") {
    section("primary", () => buildPrimary(A));
    section("bridge", () => A.bridge);
    section("bridgeLine", () => buildBridgeLine(A));
    section("states", () => bridgeStates(A));
    for (const m of Object.values(view.sectionErrors)) view.states.push(m);
    return view;
  }
  section("header", () => buildHeader(A));
  section("primary", () => buildPrimary(A));
  section("conclusion", () => conclusion(view));
  section("kpis", () => buildKpis(A, view));
  section("scope", () => buildScope(A));
  section("table", () => buildTable(A));
  section("dotplot", () => buildDotplot(A));
  section("scatter", () => buildScatter(A));
  section("bridge", () => A.bridge);
  section("bridgeLine", () => buildBridgeLine(A));
  section("observations", () => A.obs);
  section("insight", () => buildInsight(A, context));
  section("peers", () => buildPeers(A));
  section("method", () => buildMethod(A, view));
  section("detail", () => buildDetail(A));
  section("lineage", () => buildLineage(A));
  section("footer", () => buildFooter(A));
  view.undo = state.ui && state.ui.undo ? {label: state.ui.undo.label} : null;
  section("states", () => buildStates(A, view));
  for (const m of Object.values(view.sectionErrors)) view.states.push(m);
  return view;
}

/** The bridge's own states (section 8), all the bridge-only frame shows. */
function bridgeStates(A) {
  const out = [];
  const br = A.bridge;
  if (br && !br.enabled && br.reason) {
    out.push({id: br.reasonId || "bridge_disabled", severity: "info", where: ["bridge"], title: "No bridge", detail: br.reason, action: null});
  }
  if (br && br.negativeEquity) out.push(stateMsg("negative_equity", {}));
  if (A.payload.complete === false) out.push(stateMsg("model_not_computed", {}));
  return out.filter(Boolean);
}

function buildCtx(A) {
  const {state, payload, ctx, focal} = A;
  const rep = state.currency === "REPORTED";
  const bt = payload.basis_text || {};
  const std = (bt.standardised || "").replace(/\{cur\}/g, state.currency);
  const fy1 = ctx.fy1Label || "FY1", fy2 = ctx.fy2Label || "FY2", fy0 = ctx.fy0Label || "FY0";
  return {basis: state.basis, basisLabel: BASIS_NAMES[state.basis] || state.basis,
    basisTooltips: {NTM: `Next twelve months: ${fy1} and ${fy2} consensus EPS weighted by days, street adjusted.`,
      FY1: `${fy1}, the first fiscal year ending after the last close.`, FY2: `${fy2}.`,
      FY0: `${fy0}, the last filed fiscal year.`, LTM: "Last twelve months where interim filings allow, else the last fiscal year."},
    currency: state.currency, currencyLabel: rep ? "As reported, filing currency" : `Standardised, ${state.currency}`,
    dataState: rep ? "As reported" : "Standardised", earnings: state.earnings,
    earningsLabel: state.earnings === "adjusted" ? "Ex amort. and IPR&D" : "GAAP/IFRS",
    earningsTooltip: bt.adjusted || "", streetText: bt.street || "",
    fxText: `ECB reference rates, ${fmtDate(get(payload, "fx.as_of"))}`,
    basisText: rep ? (bt.as_reported || "") : std, displayCurrency: displayCurrency(focal, ctx)};
}

function failedSourcesFor(A) {
  const run = get(A.payload, "as_of.run") || {};
  const relevant = new Set([A.T].concat(A.included.map((r) => r.ticker)));
  return (run.failed_sources || []).filter((f) => f && VIEW_SOURCES.includes(f.source) && (f.ticker == null || relevant.has(f.ticker)));
}
function failedSourceText(A, list) {
  const run = get(A.payload, "as_of.run") || {};
  const bySource = {};
  for (const f of list) (bySource[f.source] = bySource[f.source] || []).push(f.ticker == null ? "every company" : f.ticker);
  return Object.entries(bySource).map(([src, ts]) => stateMsg("failed_source", {id: run.id, status: run.status,
    date: fmtDate(run.finished_at || run.started_at), source: src, tickers: uniq(ts).join(", ")}).detail);
}

function buildHeader(A) {
  const {focal, payload, ctx, state, T} = A;
  const L = focal.listing || {};
  let listingText;
  if (L.us_line) {
    listingText = `US line ${L.us_line}, home ${L.home_exchange || "not recorded"}`;
    if (isNum(L.adr_ratio) && L.adr_ratio !== 1) listingText += `, 1 ADR = ${fmtNumber(L.adr_ratio, L.adr_ratio % 1 ? 3 : 0).replace(/0+$/, "").replace(/\.$/, "")} ordinary shares`;
    if (L.otc) listingText += ", over the counter";
  } else {
    listingText = `${L.home_exchange || "Exchange not recorded"}: ${T}`;
  }
  const engineLabel = A.engineLabels[focal.engine] || focal.engine || "";
  const primaryLabel = A.primary.colId ? lcfirst(metricLabel(A.primary.colId, ctx.basis, ctx)) : "position measures";
  const rev = numAt(focal, "periods.FY0.revenue_usd_m");
  const period = get(focal, "periods.FY0.label") || "the last fiscal year";
  const cur = displayCurrency(focal, ctx);
  const mp = (u) => fmtMoneyProse(u, cur, ctx.fx);
  const clinical = focal.stage === "clinical";
  const stageChip = {id: "stage", text: clinical ? "Clinical" : "Commercial", tone: clinical ? "clinical" : "neutral",
    tooltip: clinical ? stateMsg("clinical", {revenue: rev !== null && rev > 0 ? `. Revenue of ${mp(rev)} in ${period} is on file` : ""}).detail
      : COLUMN_BY_ID.stage.tooltip};
  let typeChip = null;
  if (A.preRevenue) {
    typeChip = {id: "type", text: "Pre-revenue", tone: "clinical", tooltip: stateMsg("pre_revenue", {period, primary: primaryLabel}).detail};
  } else if (A.type === "loss_making") {
    const op = numAt(focal, "periods.FY0.operating_income_usd_m");
    const x = op !== null ? mp(op) : mp(numAt(focal, "periods.FY0.net_income_usd_m"));
    typeChip = {id: "type", text: "Loss-making", tone: "down", tooltip: stateMsg("loss_making", {x, period, primary: primaryLabel}).detail};
  } else if (A.type === "sub_scale") {
    typeChip = {id: "type", text: "Revenue under $100m", tone: "neutral", tooltip: stateMsg("sub_scale", {x: mp(rev), period, primary: primaryLabel}).detail};
  }
  const rc = focal.row_currency || focal.reporting_currency || "USD";
  const std = get(focal, "filer.standard") || "standard not recorded";
  const kindTxt = get(focal, "filer.kind") || "filer kind not recorded";
  const reportingText = `Reports ${rc}, ${std}, ${kindTxt}${rc !== "USD" ? " ⇄" : ""}`;
  const as = get(payload, "as_of") || {};
  const run = as.run || {};
  const lines = [
    `Prices: close ${fmtDate(as.price_date || get(focal, "market.price_as_of"))}, fetched ${fmtTime(get(focal, "market.quote_fetched_at"))} UTC`,
    `Consensus: last checked ${fmtDate(get(focal, "street.consensus_checked_at"))}`,
    `Financials: latest period ${fmtDate(get(focal, "lineage.fy_period_end") || get(focal, "periods.FY0.period_end"))}`,
    `FX: ECB ${fmtDate(get(payload, "fx.as_of"))}`,
    `Refresh run ${run.id ?? NULL}: ${run.status || "unknown"}, finished ${fmtTime(run.finished_at)} UTC`,
  ];
  const failed = failedSourcesFor(A);
  const focalStale = (focal.flags || []).some((f) => f && f.code === "stale_price");
  if (failed.length) lines.push(...failedSourceText(A, failed));
  else if (run.status && run.status !== "complete") {
    lines.push(stateMsg("partial_run", {id: run.id, date: fmtDate(run.finished_at || run.started_at), status: run.status}).detail);
  }
  if (Array.isArray(run.other_failures) && run.other_failures.length) {
    lines.push(`Other sources with errors in this run: ${run.other_failures.join(", ")}.`);
  }
  if (focalStale) {
    const f = focal.flags.find((x) => x.code === "stale_price");
    lines.push(flagText(f, focal).text);
  }
  const priceDate = as.price_date || get(focal, "market.price_as_of");
  return {ticker: T, name: focal.name || T, listingText, subsectorText: engineLabel, stageText: stageChip.text,
    subsectorChip: {id: "subsector", text: engineLabel, tone: "neutral", tooltip: COLUMN_BY_ID.subsector.tooltip},
    stageChip, typeChip, reportingText, reportingShort: `Files ${rc}`,
    reportingTooltip: rc !== "USD" ? (focal.flags || []).filter((f) => f && f.code === "fx_converted").map((f) => flagText(f, focal).text).join(" ") : "",
    peerSet: {full: A.label.full, short: A.label.short, noun: A.label.noun, tooltip: peerSetTooltip(A)},
    basis: buildBasisChip(A),
    dataAsOf: {text: `Data as of ${fmtDateShort(priceDate)}`, short: fmtDateShort(priceDate),
      tone: failed.length || focalStale ? "flag" : "neutral", lines},
    live: state.live !== false,
    liveChip: state.live === false ? {id: "live", text: "Live data", tone: "flag", tooltip: STATE_COPY.time_machine.detail} : null};
}

/** Peer set control tooltip (12.8): what the system set is. Empty for a saved or edited set. */
function peerSetTooltip(A) {
  if (A.setKind !== "system") return "";
  const cut = `A cohort of more than ${WHOLE_COHORT_MAX} is cut to the ${MAX_DEFAULT_PEERS} most relevant.`;
  if (A.def && A.def.whole && !A.poolsUsed.B && !A.poolsUsed.C) {
    const el = String(A.engineLabels[A.focal.engine] || A.focal.engine || "").toLowerCase();
    return `Every ${el} company at the ${A.focal.stage || "same"} stage. ${cut}`;
  }
  return A.def && A.def.whole ? "" : cut;
}

function buildPrimary(A) {
  const P = A.primary, ctx = A.ctx;
  return {colId: P.colId, label: P.colId ? metricLabel(P.colId, ctx.basis, ctx) : "", basis: P.basis,
    basisLabel: P.colId ? (basisChipText(P.colId, ctx.basis, ctx, true) || "") : "", state: P.state,
    reasonText: P.reasonText, fallbackFrom: P.fallbackFrom || null, override: !!P.override, k: P.k, n: P.n,
    candidates: METRIC_CANDIDATES.map((c) => ({colId: c, label: COLUMN_BY_ID[c].label, positionOnly: !PREMIUM_METRICS.includes(c),
      ...metricAvailability(A.focal, A.statsRows, c, ctx)}))};
}

function kpiMultiple(colId, v) {
  const c = COLUMN_BY_ID[colId];
  if (!isNum(v)) return NULL;
  if (c && (c.fmt === "mult1" || c.fmt === "mult2")) return fmtNumber(v, Math.abs(v) < 10 ? 2 : 1);
  return fmtCell({status: "ok", v}, c);
}
function arrowPct(p, suffix, d = 1) {
  if (!isNum(p)) return {text: "", dir: null};
  const dir = p > 0 ? "up" : p < 0 ? "down" : null;
  const g = p > 0 ? UP_GLYPH : p < 0 ? DOWN_GLYPH : "";
  return {text: `${g ? g + " " : ""}${fmtNumber(Math.abs(p) * 100, d)}% ${suffix}`, dir};
}

function buildKpis(A, view) {
  const {focal, ctx, T, primary: P, pStats} = A;
  const cur = displayCurrency(focal, ctx);
  const rate = rateFor(cur, ctx);
  const disp = (u) => (isNum(u) && rate !== null ? u / rate : null);
  const usdChip = cur !== "USD" ? "USD" : null;
  const kpis = [];
  // 1. Share price.
  const price = numAt(focal, "market.price");
  const chg = arrowPct(numAt(focal, "market.change_1d"), "on the day", 2);
  const stale = (focal.flags || []).find((f) => f && f.code === "stale_price");
  kpis.push({id: "price", label: "Share price, USD", value: isNum(price) ? fmtNumber(price, 2) : NULL, v: price, valueDir: null,
    unit: usdChip, period: `Close ${fmtDateShort(get(focal, "market.price_as_of"))}${MID}sourced`, provenance: "sourced",
    compare: chg.text, compareDir: chg.dir,
    tooltip: "Last close of the US-listed line, unadjusted. Per-share figures are in USD, the quote currency, whatever the display currency." + (stale ? " " + flagText(stale, focal).text : ""),
    flag: stale ? "amber" : null, strip: null});
  // 2. Market cap.
  const mc = numAt(focal, "market.market_cap_usd_m");
  const basisTxt = get(focal, "market.market_cap_basis") === "shares_outstanding"
    ? `Cover shares ${fmtDateShort(get(focal, "market.shares_cover_as_of"))}${MID}calc.` : `Diluted shares${MID}calc.`;
  const setMcs = [focal].concat(A.included.map((r) => r.record)).map((r) => numAt(r, "market.market_cap_usd_m")).filter(isNum);
  const rank = isNum(mc) ? setMcs.filter((v) => v > mc).length + 1 : null;
  const mcCell = cell(focal, "market_cap", ctx);
  kpis.push({id: "market_cap", label: `Market cap, ${unitText(COLUMN_BY_ID.market_cap, ctx)}`, value: mcCell.text, v: mcCell.v, valueDir: null,
    unit: null, period: basisTxt, provenance: "calc.",
    compare: rank ? `${ordinal(rank)} largest of ${setMcs.length} in the set` : "",
    compareDir: null, tooltip: `${COLUMN_BY_ID.market_cap.tooltip} ${get(focal, "market.market_cap_basis_text") || ""}`.trim(),
    flag: mcCell.amber ? "amber" : null, strip: null});
  // 3. EV.
  const evCell = cell(focal, "ev", ctx);
  const nd = numAt(focal, "ev.net_debt_usd_m");
  if (evCell.status === "ok") {
    const ndd = disp(nd);
    kpis.push({id: "ev", label: `EV, ${unitText(COLUMN_BY_ID.ev, ctx)}`, value: evCell.text, v: evCell.v, valueDir: null, unit: null,
      period: `Balance sheet ${fmtDate(get(focal, "ev.balance_sheet_as_of"))}${MID}calc.`, provenance: "calc.",
      compare: isNum(ndd) ? (ndd >= 0 ? `Net debt ${fmtNumber(ndd / 1000, 1)}` : `Net cash ${fmtNumber(-ndd / 1000, 1)}`) : "",
      compareDir: null, tooltip: COLUMN_BY_ID.ev.tooltip, flag: evCell.amber ? "amber" : null, strip: null});
  } else {
    kpis.push({id: "ev", label: `EV, ${unitText(COLUMN_BY_ID.ev, ctx)}`, value: NULL, v: null, valueDir: null, unit: null,
      period: "No debt line on file", provenance: "calc.", compare: "", compareDir: null,
      tooltip: evCell.reason || NA_TEXT.no_debt_line, flag: null, strip: null});
  }
  const state = view.conclusion ? view.conclusion.state : P.state;
  const fmtStat = (colId, v) => kpiMultiple(colId, v);
  if (state === "no_multiple" || !P.colId) {
    const c1 = cell(focal, "cash_to_mcap", ctx);
    const s1 = peerStats(A.setRows, "cash_to_mcap", ctx);
    kpis.push({id: "primary", label: "Cash / market cap, %", value: c1.text, v: c1.v, valueDir: null, unit: null,
      period: `Balance sheet ${fmtDate(get(focal, "ev.balance_sheet_as_of"))}${MID}calc.`, provenance: "calc.",
      compare: s1.n ? `Median ${fmtCell({status: "ok", v: s1.median}, "cash_to_mcap")}, n ${s1.n}` : "No peer value",
      compareDir: null, tooltip: COLUMN_BY_ID.cash_to_mcap.tooltip, flag: null, strip: null});
    const c2 = cell(focal, "runway_months", ctx);
    const s2 = peerStats(A.setRows, "runway_months", ctx);
    kpis.push({id: "position", label: "Cash runway, months", value: c2.text, v: c2.v, valueDir: null, unit: null,
      period: get(focal, "risk.runway_basis") || "Trailing burn", provenance: "calc.",
      compare: s2.n ? `Median ${fmtNumber(s2.median, 0)}` : "No peer value", compareDir: null,
      tooltip: COLUMN_BY_ID.runway_months.tooltip + (c2.status !== "ok" ? ` ${c2.reason}` : ""), flag: null,
      strip: positionStrip(focal, A.setRows, "runway_months", ctx)});
  } else {
    const c = COLUMN_BY_ID[P.colId];
    const fc = cell(focal, P.colId, ctx);
    const spot = c.bases[0] === "-";
    const bsd = get(focal, P.colId === "price_to_book" ? "periods.FY0.equity_as_of" : "ev.balance_sheet_as_of") || get(focal, "ev.balance_sheet_as_of");
    const per = spot ? `Balance sheet ${fmtDate(bsd)}${MID}calc.` : `${basisChipText(P.colId, ctx.basis, ctx, true)}${MID}calc.`;
    kpis.push({id: "primary", label: `${c.label}, ${unitText(c, ctx)}`, value: fc.status === "ok" ? kpiMultiple(P.colId, fc.v) : fc.text,
      v: fc.v, valueDir: null, unit: null, period: per, provenance: "calc.",
      compare: pStats && pStats.n ? `Median ${fmtStat(P.colId, pStats.median)}, n ${pStats.n}` : "No peer value",
      compareDir: null, tooltip: `${c.tooltip} ${P.reasonText}`, flag: fc.amber ? "amber" : null, strip: null});
    // 5. Against peer median.
    const strip = positionStrip(focal, A.setRows, P.colId, ctx);
    const pctTxt = isNum(A.pct) ? `${ordinal(Math.round(A.pct))} percentile` : "";
    if (state === "ok" && isNum(A.premium)) {
      const p = A.premium;
      const inLine = isInLine(p);
      kpis.push({id: "position", label: "Against peer median", value: `${fmtNumber(p * 100, 1, {signed: true})}%`, v: p,
        valueDir: p > 0 ? "up" : p < 0 ? "down" : null, unit: null,
        period: inLine ? "In line, within 5%" : (p >= 0 ? "Premium" : "Discount"), provenance: "calc.",
        compare: pctTxt, compareDir: null, tooltip: KPI5_TOOLTIP, flag: null, strip});
    } else if (state === "low_confidence") {
      const p = premium(fc.v, pStats ? pStats.median : null, multipleDirection(P.colId));
      kpis.push({id: "position", label: "Against peer median", value: isNum(p) ? `${fmtNumber(p * 100, 1, {signed: true})}%` : NULL, v: p,
        valueDir: isNum(p) ? (p > 0 ? "up" : p < 0 ? "down" : null) : null, unit: null,
        period: `Not stated: ${pStats ? pStats.n : 0} peers`, provenance: "calc.", compare: pctTxt, compareDir: null,
        tooltip: `${KPI5_TOOLTIP} ${lowConfidenceText(pStats ? pStats.n : 0, P.colId)}`, flag: "amber", strip});
    } else {
      kpis.push({id: "position", label: "Against peer median", value: NULL, v: null, valueDir: null, unit: null,
        period: "Not stated", provenance: "calc.", compare: pctTxt, compareDir: null, tooltip: KPI5_TOOLTIP, flag: null, strip});
    }
  }
  // 6. Implied value, else the street target.
  const br = A.bridge;
  if (state !== "no_multiple" && br && br.enabled && isNum(br.V)) {
    const up = arrowPct(br.upside, "against price", 1);
    const statTxt = isNum(br.inputs.multipleOverride) ? "Analyst" : (br.stat === "pct" ? `${ordinal(br.pct)} percentile` : STAT_LABEL[br.stat] || "Median");
    kpis.push({id: "implied", label: "Implied value, USD", value: fmtNumber(br.V, 2), v: br.V, valueDir: null, unit: usdChip,
      period: `${statTxt} ${lcfirst(br.metricLabel)} ${TIMES} ${br.operatingShort}${MID}calc.`, provenance: "calc.",
      compare: up.text, compareDir: up.dir,
      tooltip: "From the peer-multiple bridge on the Forecast tab, with its inputs. Click to open it. Per-share figures are in USD, the quote currency.",
      flag: null, strip: null});
  } else {
    const t = br ? br.streetTarget : null;
    if (t) {
      const up = arrowPct(t.upside, "against price", 1);
      kpis.push({id: "implied", label: "Street target, USD", value: fmtNumber(t.value, 2), v: t.value, valueDir: null, unit: usdChip,
        period: `12M${t.analysts ? `, ${t.analysts} analysts` : ""}${MID}sourced`, provenance: "sourced", compare: up.text, compareDir: up.dir,
        tooltip: "Upside to the 12-month consensus price target from Nasdaq, per US-listed share." + (br && br.reason ? ` The bridge is off: ${br.reason}` : ""),
        flag: null, strip: null});
    } else {
      kpis.push({id: "implied", label: "Street target, USD", value: NULL, v: null, valueDir: null, unit: usdChip,
        period: "No street target on file", provenance: "sourced", compare: "", compareDir: null,
        tooltip: br && br.reason ? br.reason : NA_TEXT.no_consensus, flag: null, strip: null});
    }
  }
  // KPI 6 opens the peer-multiple value on the Forecast tab (12.5); the other cells have no link.
  return kpis.map((k, i) => ({...k, link: i === 5 ? LINK_FORECAST : null}));
}

function filterText(f) {
  const c = COLUMN_BY_ID[f.colId];
  const lab = c ? c.label + (c.unit ? `, ${c.unit.replace("{cur} ", "")}` : "") : f.colId;
  if (f.op === ">=") return `${lab} ≥ ${f.value}`;
  if (f.op === "<=") return `${lab} ≤ ${f.value}`;
  if (f.op === "has") return `${lab}: has a value`;
  return `${c ? c.label : f.colId} contains “${f.value}”`;
}
function passesFilter(f, rec, ctx) {
  const c = COLUMN_BY_ID[f.colId];
  const cc = cell(rec, f.colId, ctx);
  if (f.op === "has") return cc.status === "ok";
  if (f.op === "text") return String(cc.text || "").toLowerCase().includes(String(f.value || "").toLowerCase());
  const dv = displayValue(cc, c);
  if (!isNum(dv) || !isNum(Number(f.value))) return false;
  return f.op === ">=" ? dv >= Number(f.value) : dv <= Number(f.value);
}

function buildScope(A) {
  const {state, setRows, statsRows} = A;
  const items = [];
  for (const r of setRows.filter((x) => x.excluded)) {
    items.push({id: `excl:${r.ticker}`, kind: "exclusion", text: r.ticker, ticker: r.ticker,
      tooltip: "Excluded from statistics. Still shown. X includes it again.", removable: true, priority: 2,
      action: {type: "TOGGLE_EXCLUDE", ticker: r.ticker}});
  }
  for (const f of state.filters || []) {
    items.push({id: `filter:${f.colId}`, kind: "filter", text: filterText(f), colId: f.colId,
      tooltip: "Filters hide rows. Statistics still use every included peer.", removable: true, priority: 3,
      action: {type: "REMOVE_FILTER", colId: f.colId}});
  }
  if (A.groupName) {
    const lo = A.groupLeftOut.length ? ` Left out: ${A.groupLeftOut.join(", ")}, not known for this grouping.` : "";
    items.push({id: "group", kind: "group", text: `Statistics over: ${A.groupName}`,
      tooltip: `Statistics use the ${A.groupName} peers only.${lo}`, removable: true, priority: 4,
      action: {type: "SET_STATS_GROUP", group: "all"}});
  }
  if (state.outliers === "exclude") {
    items.push({id: "outliers", kind: "outliers", text: "Outliers excluded",
      tooltip: "Statistics leave out values beyond 1.5 interquartile ranges from the quartiles. U includes them again.",
      removable: true, priority: 5, action: {type: "SET_OUTLIERS", mode: "include"}});
  }
  const inSet = [A.focal].concat(A.included.map((r) => r.record));
  const fye = inSet.filter((r) => (r.flags || []).some((f) => f && f.code === "fiscal_year_end"));
  if (fye.length) {
    items.push({id: "warn:fye", kind: "warning", text: `Non-December year ends: ${fye.length}`,
      tooltip: `${fye.map((r) => r.ticker).join(", ")}. Fiscal years are not calendarised, so FY figures cover a different twelve months from December filers.`,
      removable: false, priority: 6});
  }
  const stale = A.included.filter((r) => (r.record.flags || []).some((f) => f && f.code === "stale_price"));
  if (stale.length) {
    items.push({id: "warn:stale", kind: "warning", text: `Stale prices: ${stale.length}`,
      tooltip: stale.map((r) => `${r.ticker}: ${flagText(r.record.flags.find((f) => f.code === "stale_price"), r.record).text}`).join(" "),
      removable: false, priority: 6});
  }
  if (A.primary.colId && A.pStats && state.outliers !== "exclude" && A.pStats.outliers.extreme.length) {
    const n = A.pStats.outliers.extreme.length;
    items.push({id: "warn:outliers", kind: "warning", text: `${n} extreme ${plural(n, "outlier", "outliers")}`,
      tooltip: `${A.pStats.outliers.extreme.join(", ")}. ${STATE_COPY.extreme_outliers.detail}`, removable: false, priority: 6});
  }
  const failed = failedSourcesFor(A);
  if (failed.length) {
    items.push({id: "warn:failed", kind: "warning", text: `Failed sources: ${failed.length}`,
      tooltip: failedSourceText(A, failed).join(" "), removable: false, priority: 6});
  }
  const n = setRows.length, k = statsRows.length;
  return {counts: {n, k, text: `${n} ${plural(n, "peer", "peers")}, ${k} in statistics`}, items};
}

function cfMark(mode, colId, c, s, pct, vsMedian) {
  const col = COLUMN_BY_ID[colId];
  if (!col || !mode || mode === "off") return null;
  const numeric = isNumericCol(col);
  switch (mode) {
    case "premium":
      if (!numeric || c.status !== "ok" || !isNum(vsMedian)) return null;
      return {kind: "premium", frac: Math.min(1, Math.abs(vsMedian)), side: vsMedian >= 0 ? "right" : "left",
        tooltip: `${fmtNumber(Math.abs(vsMedian) * 100, 0)}% ${vsMedian >= 0 ? "above" : "below"} the peer median`};
    case "percentile":
      if (!numeric || !isNum(pct)) return null;
      return {kind: "percentile", frac: pct / 100, tooltip: `${ordinal(Math.round(pct))} percentile of peers`};
    case "trend":
      if (!TREND_COLS.includes(colId) || c.status !== "ok" || !isNum(c.v) || c.v === 0) return null;
      return {kind: "trend", dir: c.v > 0 ? "up" : "down"};
    case "quality":
      return {kind: "quality", flagged: !!(c.amber || c.red),
        derived: c.flags.includes("derived_operating_income") || c.flags.includes("derived_no_addback"), showTag: true};
    case "outliers": {
      if (!numeric || c.status !== "ok" || !s) return null;
      const lvl = outlierClass(c.v, s.all);
      return lvl ? {kind: "outlier", level: lvl} : null;
    }
    default: return null;
  }
}

function buildTable(A) {
  const {state, ctx, focal, T} = A;
  const primaryId = A.primary.colId;
  let cols = presetColumns(state);
  if (state.preset === "custom") cols = cols.filter((c) => !(state.hidden || []).includes(c));
  const pinned = (state.pinned || []).filter((c) => COLUMN_BY_ID[c]);
  let order = pinned.slice();
  if (primaryId && !cols.includes(primaryId) && !pinned.includes(primaryId)) order.push(primaryId);
  order = order.concat(cols.filter((c) => !pinned.includes(c)));
  const allRows = [A.focalRow].concat(A.setRows);
  const focalCur = displayCurrency(focal, ctx);
  const statsPer = {};
  for (const id of order) if (isNumericCol(COLUMN_BY_ID[id])) statsPer[id] = peerStats(A.setRows, id, ctx, {focalCurrency: focalCur});
  const sortDir = (id) => (state.sort && state.sort.colId === id ? state.sort.dir : null);
  const columns = FROZEN_BASE.map((fb) => ({id: fb.id, group: "company", label: fb.label, aria: fb.aria || fb.label,
    unitText: "", unitLine: "", basisChip: null, provenance: "S", provenanceWord: "sourced", tooltip: fb.tooltip || "",
    width: (state.widths || {})[fb.id] || fb.width, frozen: true, autoPinned: false, align: "left", sortDir: sortDir(fb.id),
    filter: null, fmt: "text", dir: "n", numeric: false, isPrimary: false}));
  for (const id of order) {
    const c = COLUMN_BY_ID[id];
    const chip = basisChipText(id, state.basis, ctx, false);
    const chipE = basisChipText(id, state.basis, ctx, true);
    const mixedN = chip && resolveBasis(id, state.basis) === "LTM"
      ? allRows.filter((r) => cell(r.record, id, ctx).tagDiffers).length : 0;
    const ut = unitText(c, ctx);
    const pw = PROVENANCE_WORD[c.prov];
    const star = mixedN ? "*" : "";
    columns.push({id, group: c.group, label: c.label, unitText: ut,
      basisChip: chip ? {text: chip + star, mixed: mixedN > 0, count: mixedN, earnings: c.earnings ? (chip.endsWith("E") ? "street" : "GAAP/IFRS") : null,
        tooltip: mixedN ? `${mixedN} ${plural(mixedN, "company has", "companies have")} no LTM figure, so ${plural(mixedN, "its cells show", "their cells show")} the last fiscal year, marked A.` : null} : null,
      provenance: c.prov, provenanceWord: pw, tooltip: c.tooltip, width: (state.widths || {})[id] || c.width,
      frozen: pinned.includes(id), autoPinned: id === primaryId, align: isNumericCol(c) ? "right" : "left",
      sortDir: sortDir(id), filter: (state.filters || []).find((f) => f.colId === id) || null, fmt: c.fmt, dir: c.dir,
      numeric: isNumericCol(c), isPrimary: id === primaryId,
      unitLine: [ut, chipE ? chipE + star : null, pw, id === primaryId ? "Primary" : null].filter(Boolean).join(MID)});
  }
  const groups = [];
  for (const cv of columns) {
    const last = groups[groups.length - 1];
    if (last && last.id === cv.group) last.span++;
    else groups.push({id: cv.group, label: (COLUMN_GROUPS.find((g) => g.id === cv.group) || {}).label || cv.group, span: 1});
  }
  const pOut = A.pStats ? A.pStats.outliers : {mild: [], extreme: []};
  const tInfo = tickerFlagInfo(A);
  const mkRow = (r) => {
    const rec = r.record;
    const cells = {};
    for (const id of ["company", "ticker"].concat(order)) {
      const c = cell(rec, id, ctx);
      const s = statsPer[id];
      let pct = null, vsMedian = null;
      if (s && c.status === "ok" && isNum(c.v)) {
        pct = percentileRank(c.v, s.values);
        vsMedian = isNum(s.median) && s.median !== 0 ? c.v / s.median - 1 : null;
      }
      cells[id] = {...c, pct, vsMedian, cf: cfMark(state.cfMode, id, c, s, pct, vsMedian)};
    }
    // The marker after a ticker follows the confidence points (12.7), not every amber flag on the row.
    const tf = tickerFlagsFor(A, tInfo, r);
    if (cells.ticker) {
      cells.ticker = {...cells.ticker, marks: tf.codes.slice(), flagLines: tf.lines.slice(), red: !!rec.error,
        amber: tf.codes.some((c) => c !== "calc_failed")};
    }
    return {ticker: r.ticker, name: rec.name || r.ticker, isFocal: r.isFocal, excluded: !!r.excluded,
      expanded: (state.ui.expanded || []).includes(r.ticker),
      outlier: r.isFocal ? null : (pOut.extreme.includes(r.ticker) ? "extreme" : pOut.mild.includes(r.ticker) ? "mild" : null),
      source: r.source, pool: r.pool, reason: r.reason, relevance: r.relevance, note: r.note || "",
      cells, error: rec.error ? stateMsg("calc_failed_company", {T: r.ticker, message: stripStop(String(rec.error))}).detail : null,
      tickerFlags: tf.codes, tickerLines: tf.lines};
  };
  let peers = A.setRows.filter((r) => (state.filters || []).every((f) => passesFilter(f, r.record, ctx)));
  const filteredOut = A.setRows.length - peers.length;
  if (state.sort) {
    const {colId, dir} = state.sort;
    if (colId === "rel") peers.sort((a, b) => (dir === "asc" ? 1 : -1) * (a.relevance.score - b.relevance.score) || a.ticker.localeCompare(b.ticker));
    else peers.sort((a, b) => compareCells(cell(a.record, colId, ctx), cell(b.record, colId, ctx), dir));
  } else {
    const mc = (r) => numAt(r.record, "market.market_cap_usd_m") || 0;
    peers.sort((a, b) => (b.relevance.score - a.relevance.score) || (mc(b) - mc(a)) || a.ticker.localeCompare(b.ticker));
  }
  const rows = [mkRow(A.focalRow)].concat(peers.map(mkRow));
  const k = A.statsRows.length;
  const groupText = A.groupName ? `${A.groupName} subgroup` : `${k} ${plural(k, "peer", "peers")}`;
  const summary = SUMMARY_IDS.map((sid) => {
    const cells = {};
    for (const id of order) {
      const c = COLUMN_BY_ID[id];
      const s = statsPer[id];
      if (!s) { cells[id] = {v: null, text: "", n: 0, lowN: false, reason: null}; continue; }
      if (s.mixedCurrency) { cells[id] = {v: null, text: NULL, n: 0, lowN: false, reason: MIXED_CURRENCY_TEXT}; continue; }
      const n = s.n;
      if (sid === "n") { cells[id] = {v: n, text: String(n), n, lowN: n > 0 && n < MIN_PEERS, reason: n > 0 && n < MIN_PEERS ? `${n} values, fewer than 5` : null}; continue; }
      if (n === 0) { cells[id] = {v: null, text: NULL, n, lowN: false, reason: "No peer has a value"}; continue; }
      if (n === 1) { cells[id] = {v: null, text: NULL, n, lowN: false, reason: "One peer value, no statistic"}; continue; }
      const v = s[sid];
      cells[id] = {v, text: fmtCell({status: "ok", v}, c), n, lowN: n < MIN_PEERS, reason: n < MIN_PEERS ? `${n} values, fewer than 5` : null};
    }
    return {id: sid, label: sid === "n" ? SUMMARY_LABEL.n : `${SUMMARY_LABEL[sid]}, ${groupText}`, cells};
  });
  const presetLabel = (PRESET_BY_ID[state.preset] || {}).label || state.preset;
  const n = A.setRows.length;
  let empty = null;
  if (!n) empty = stateMsg("no_peers", {}, {where: ["table"]});
  else if (!peers.length && filteredOut) empty = stateMsg("filters_empty", {});
  return {columns, groups, rows, summary, summaryVisible: state.summaryRows === false ? ["n"] : SUMMARY_IDS.slice(),
    sort: state.sort || null, cfMode: state.cfMode, density: state.density, textSize: state.textSize, preset: state.preset,
    presetLabel, hiddenCount: state.preset === "custom" ? (state.hidden || []).length : 0, hidden: (state.hidden || []).slice(),
    frozenWidth: FROZEN_BASE_WIDTH.wide + pinned.reduce((s, id) => s + ((state.widths || {})[id] || COLUMN_BY_ID[id].width), 0),
    caption: `Comparable companies for ${T}: ${n} peers, ${k} in statistics, preset ${presetLabel}, basis ${state.basis}. Summary rows follow the company rows.`,
    filteredOut, empty, presets: PRESETS.map((p) => ({id: p.id, key: p.key, label: p.label})), presetFootnote: PRESET_FOOTNOTE,
    stats: statsPer, viewBadge: buildViewBadge(A)};
}

function cohortDefs(A) {
  const {state, focal, companies, engineLabels} = A;
  const ex = new Set(state.excluded || []);
  const rowsOf = (ts) => ts.filter((t) => t !== focal.ticker && A.byTicker[t] && !A.byTicker[t].error)
    .map((t) => ({ticker: t, record: A.byTicker[t], isFocal: false, excluded: ex.has(t), inSet: true}));
  const defs = [{id: "system", label: "System set", rows: () => rowsOf(A.def.tickers)},
    {id: `all:${focal.engine}`, label: `All ${(engineLabels[focal.engine] || focal.engine || "").toLowerCase()}`,
     rows: () => rowsOf(companies.filter((c) => c.engine === focal.engine).map((c) => c.ticker))},
    {id: "stage", label: "Same stage across subsectors", rows: () => rowsOf(companies.filter((c) => c.stage === focal.stage).map((c) => c.ticker))}];
  for (const name of Object.keys(state.savedSets || {})) {
    defs.push({id: `saved:${name}`, label: `'${name}'`, rows: () => rowsOf(state.savedSets[name].tickers)});
  }
  const subs = SYSTEM_SUBGROUPS.concat(Object.keys(((state.subgroups || {})[state.focal]) || {}));
  for (const name of subs) {
    defs.push({id: `sub:${name}`, label: `${name} subgroup`, rows: () => {
      const m = subgroupMembers(name, A.setRows, state);
      return A.setRows.filter((r) => (m.tickers || []).includes(r.ticker));
    }});
  }
  return defs;
}

function buildDotplot(A) {
  const {state, ctx, focal} = A;
  const colId = A.dotCol;
  const isPrimary = colId === A.primary.colId;
  const chosen = (state.cohorts || []).map((id) => cohortDefs(A).find((d) => d.id === id)).filter(Boolean);
  const lanes = chosen.length ? chosen.map((d) => ({id: d.id, label: d.label, rows: d.rows()}))
    : [{id: "set", label: A.label.short, rows: A.setRows}];
  const target = A.bridge && A.bridge.target && A.bridge.colId === colId ? A.bridge.target : null;
  const subtitle = isPrimary && A.primary.state === "low_confidence" && A.pStats
    ? `Only ${A.pStats.n} peer values: no premium or discount is stated.` : "";
  const dp = dotplotModel(focal, A.setRows, colId, ctx, {lanes, isPrimary, target, subtitle});
  const noPeers = !A.setRows.length ? stateMsg("no_peers", {}, {where: ["dotplot"]}) : null;
  return {...dp, disabledReason: noPeers ? noPeers.detail : dp.disabledReason,
    disabledState: noPeers || (dp.disabledReason ? {id: "dotplot_disabled", severity: "info", where: ["dotplot"],
      title: "No peer position", detail: dp.disabledReason, action: null} : null), tag: isPrimary ? "Primary" : (PREMIUM_METRICS.includes(colId) ? null : "Position only"),
    useAsPrimary: !isPrimary && PREMIUM_METRICS.includes(colId) && metricAvailability(focal, A.statsRows, colId, ctx).enabled,
    notPlottedText: dp.notPlotted.nm || dp.notPlotted.na ? `Not plotted: ${dp.notPlotted.nm} not meaningful, ${dp.notPlotted.na} with no value` : ""};
}

function buildScatter(A) {
  const s = A.scatter;
  const st = A.state.scatter || DEFAULT_SCATTER;
  return {...s, size: st.size || "market_cap", colorBy: st.colorBy || "none", logY: !!s.logY, trendOn: st.trend !== false,
    logYOffered: LOG_Y_COLS.includes(s.y),
    xOptions: SCATTER_X_OPTIONS.map((id) => ({id, label: COLUMN_BY_ID[id].label})),
    yOptions: SCATTER_Y_OPTIONS.map((id) => ({id, label: COLUMN_BY_ID[id].label})),
    legend: ["Circle: big pharma", "Square: biotech", "Triangle: cell and gene", "Hollow = clinical", `Ring = ${A.T}`, "Dashed = excluded"],
    disabledState: !A.setRows.length ? stateMsg("no_peers", {}, {where: ["scatter"]})
      : s.disabledReason ? {id: "scatter_disabled", severity: "info", where: ["scatter"],
        title: STATE_COPY.scatter_disabled.title, detail: s.disabledReason, action: null} : null};
}

function componentPercents(rel) {
  const o = {};
  for (const k of Object.keys(RELEVANCE_WEIGHTS)) o[k] = rel && isNum(rel.components[k]) ? Math.round(rel.components[k] * 100) : null;
  return o;
}

function buildPeers(A) {
  const {state, focal, ctx, companies} = A;
  const src = {system: "System", analyst: "Analyst", saved: "Saved set"};
  const inStats = new Set(A.statsRows.map((r) => r.ticker));
  const peerRow = (r) => ({ticker: r.ticker, name: r.record.name || r.ticker, included: !r.excluded, inStats: inStats.has(r.ticker),
    relevance: r.relevance, components: componentPercents(r.relevance),
    missing: (r.relevance.missing || []).map((m) => ({...m, text: `not scored: ${m.reason}`})),
    subsector: A.engineLabels[r.record.engine] || r.record.engine, stage: r.record.stage,
    source: src[r.source] || "System", sourceId: r.source, pool: r.pool, reason: r.reason, note: r.note || "",
    region: r.record.region ?? null, standard: get(r.record, "filer.standard") ?? null,
    marketCap: cell(r.record, "market_cap", ctx).text});
  const rows = A.setRows.map(peerRow);
  const inSet = new Set(A.setRows.map((r) => r.ticker));
  const candidates = companies.filter((c) => c.ticker !== focal.ticker && !inSet.has(c.ticker) && !c.error)
    .map((c) => ({c, rel: relevance(focal, c)}))
    .sort((a, b) => (b.rel.score - a.rel.score) || a.c.ticker.localeCompare(b.c.ticker)).slice(0, 20)
    .map(({c, rel}) => peerRow({ticker: c.ticker, record: c, excluded: false, source: null, pool: null,
      reason: `Relevance ${rel.score}`, relevance: rel, note: ""}));
  const savedSets = Object.entries(state.savedSets || {}).map(([name, s]) => ({name, n: s.tickers.length, created: s.created,
    createdText: s.created ? fmtDate(s.created) : "", engine: s.engine, active: state.activeSet === `saved:${name}`}));
  const subgroups = SYSTEM_SUBGROUPS.map((name) => {
    const m = subgroupMembers(name, A.setRows, state);
    const lo = m.leftOut.length ? ` Left out: ${m.leftOut.join(", ")}, whose ${name === "US" || name === "Europe" ? "region" : "accounting standard"} is not known.` : "";
    return {name, system: true, tickers: m.tickers || [], leftOut: m.leftOut, tooltip: `${name}: ${(m.tickers || []).length} peers.${lo}`, active: state.statsGroup === name};
  }).concat(Object.entries(((state.subgroups || {})[state.focal]) || {}).map(([name, ts]) => ({name, system: false,
    tickers: ts.filter((t) => inSet.has(t)), leftOut: [], tooltip: `${name}: ${ts.length} peers.`, active: state.statsGroup === name})));
  const defs = cohortDefs(A);
  const P = A.primary;
  const cohorts = (state.cohorts || []).map((id) => defs.find((d) => d.id === id)).filter(Boolean).map((d) => {
    if (!P.colId) return {id: d.id, label: d.label, n: 0, median: null, p25: null, p75: null, premium: null, pct: null, text: {}};
    const s = peerStats(d.rows(), P.colId, ctx);
    const fv = cell(focal, P.colId, ctx).v;
    const p = s.n >= MIN_PEERS ? premium(fv, s.median, multipleDirection(P.colId)) : null;
    const pc = percentileRank(fv, s.values);
    const f = (v) => fmtCell({status: "ok", v}, COLUMN_BY_ID[P.colId]);
    return {id: d.id, label: d.label, n: s.n, median: s.median, p25: s.p25, p75: s.p75, premium: p, pct: pc,
      text: {median: isNum(s.median) ? f(s.median) : NULL, iqr: isNum(s.p25) ? `${f(s.p25)} to ${f(s.p75)}` : NULL,
        premium: isNum(p) ? signedWholePct(p) : NULL, pct: isNum(pc) ? ordinal(Math.round(pc)) : NULL}};
  });
  let weak = null;
  if (A.defaultWarning === "too_few") weak = stateMsg("default_short", {n: A.def.tickers.length, T: A.T});
  else if (A.defaultWarning === "padded") {
    const low = A.def.tickers.filter((t) => A.def.pools[t] !== "A" && A.def.scores[t] < MIN_DEFAULT_RELEVANCE).length;
    weak = stateMsg("padded", {k: low, n: A.def.tickers.length});
  } else if (A.weak) weak = stateMsg("weak", {a: A.appropriate, n: A.included.length});
  return {rows, candidates, savedSets, subgroups, cohorts,
    cohortOptions: defs.map((d) => ({id: d.id, label: d.label})),
    mixed: A.mixed ? stateMsg("mixed_models", {k: A.mixed.k, n: A.mixed.n, other: A.mixed.otherType, T: A.T, focalType: A.mixed.focalType}) : null,
    weak, setLabel: A.label, n: A.setRows.length, k: A.statsRows.length, activeSet: state.activeSet,
    outliers: state.outliers, statsGroup: state.statsGroup, storageLine: "Saved in this browser only.",
    open: !!(state.ui && state.ui.peers), search: !!(state.ui && state.ui.peers && state.ui.peersSearch), title: "Edit peers"};
}

function buildMethod(A, view) {
  const conf = view.conclusion ? view.conclusion.confidence : {reasons: []};
  const bt = A.payload.basis_text || {};
  const sections = [
    {id: "stats", title: "Peer statistics", body: [
      "Statistics exclude the focal company, excluded peers and peers outside the statistics group. Filters hide rows but never change statistics.",
      "Quantiles interpolate linearly between closest ranks (R type 7, the numpy default and Excel PERCENTILE.INC). A percentile is the mid-rank percent of the peer values.",
      "Every statistic, percentile and quartile side for a column comes from one value set, so a top-quartile statement always agrees with the 75th percentile row."]},
    {id: "primary", title: "Primary metric", body: [
      "Profitable companies: P/E, then EV/EBITDA, then EV/Revenue, then market cap / revenue.",
      "Loss-making companies: EV/Revenue, then market cap / revenue, then market cap / cash. P/B is not used: on a cash-heavy balance sheet it measures the cash.",
      "Clinical-stage and sub-scale companies: market cap / cash, the one scale-free valuation measure every company in the universe has.",
      "The first candidate with a value for the focal company and 5 or more peer values is primary. With 2 to 4 peer values no premium or discount is stated.",
      A.primary.reasonText]},
    {id: "confidence", title: "Confidence", body: conf.reasons.map((r) => r + ".").concat([
      "Points: 8 or more peer values add 2, 5 to 7 add 1. One point is lost each for fewer than 5 peers scoring 40 or more on relevance, a median relevance under 50, mixed business models, mixed standards on a metric that uses filed figures, fiscal-year figures in an LTM column, more than a quarter of peer values on derived operating income, an amber flag on the focal company's own value, an interquartile range over 60% of the median and an extreme outlier.",
      "High at 2 or more, medium at 1, low at 0 or below."])},
    {id: "relevance", title: "Relevance", body: [
      "Subsector 25%, business model 20%, scale 20%, profitability or clinical stage 15%, growth 15%, geography 5%. A component with no data for either company is dropped and the weights renormalise.",
      "An appropriate peer scores 40 or more. A set with fewer than 5 appropriate peers is weak."]},
    {id: "outliers", title: "Outliers", body: [
      "Mild outliers sit more than 1.5 interquartile ranges beyond the quartiles, extreme outliers more than 3. Statistics include them unless you exclude outliers (U)."]},
    {id: "nm", title: "Not meaningful", body: [
      "Revenue multiples, margins and R&D share are not meaningful under $100m of revenue. EV/Revenue and market cap / revenue over 100× are not meaningful.",
      "Revenue growth needs $10m of revenue at both ends; EBITDA growth a prior year of $10m or more; EPS growth a base EPS of 0.10 or more. Growth over 500% is not meaningful.",
      "Margins below −100% are not meaningful. P/E is not meaningful when earnings are at or below zero, and P/E NTM when consensus changes sign within the twelve months."]},
    {id: "bases", title: "Bases", body: [bt.standardised ? bt.standardised.replace(/\{cur\}/g, A.state.currency === "REPORTED" ? "USD" : A.state.currency) + "." : "",
      bt.as_reported ? bt.as_reported + "." : "", bt.adjusted ? `Ex amort. and IPR&D: ${bt.adjusted}.` : "",
      STATE_COPY.street_vs_reported.detail,
      "Under IFRS 16 lease costs sit below EBITDA and lease payments in financing cash flow, which lifts IFRS filers' EBITDA and free cash flow against US GAAP peers."].filter(Boolean).map((s) => s.replace(/\.\.$/, "."))},
    {id: "definitions", title: "Definitions", body: [],
      items: COLUMNS.map((c) => ({colId: c.id, group: (COLUMN_GROUPS.find((g) => g.id === c.group) || {}).label, label: c.label, text: c.tooltip}))},
  ];
  return {sections, open: A.state.ui ? A.state.ui.method : null};
}

const AGAINST_ROWS = [
  {id: "revenue", label: "Revenue", better: "+"},
  {id: "revenue_growth", label: "Revenue growth", better: "+"},
  {id: "net_margin", label: "Net margin", better: "+"},
  {id: "rd_pct", label: "R&D share of revenue", better: null},
  {id: "market_cap", label: "Market cap", better: null},
  {id: "pe", label: "P/E FY0", better: null, basis: "FY0"},
  {id: "ev_revenue", label: "EV/Revenue FY0", better: null, basis: "FY0"},
  {id: "late_trials", label: "Late-stage trials", better: "+"},
  {id: "catalysts_12m", label: "Catalysts in 12 months", better: null},
  {id: "loe_share_5y", label: "Losing exclusivity 5y", better: "-"},
  {id: "ttm_price_change", label: "Share price, 12 months", better: null},
];

function buildDetail(A) {
  const t = A.state.ui && A.state.ui.detail;
  if (!t) return null;
  const rec = A.byTicker[t];
  if (!rec) return null;
  const {focal, ctx} = A;
  const isFocal = t === focal.ticker;
  const row = A.setRows.find((r) => r.ticker === t);
  const fy0ctx = {...ctx, basis: "FY0", cache: new Map()};
  const against = isFocal ? [] : AGAINST_ROWS.map((d) => {
    const c = d.basis ? fy0ctx : {...ctx, basis: "FY0", cache: fy0ctx.cache};
    const pc = cell(rec, d.id, c), fc = cell(focal, d.id, c);
    let better = null;
    if (d.better && pc.status === "ok" && fc.status === "ok" && isNum(pc.v) && isNum(fc.v) && pc.v !== fc.v) {
      better = (d.better === "+" ? pc.v > fc.v : pc.v < fc.v) ? "peer" : "focal";
    }
    const unit = unitText(COLUMN_BY_ID[d.id], ctx);
    return {id: d.id, label: unit ? `${d.label}, ${unit}` : d.label, peer: pc.text, focal: fc.text, better,
      peerReason: pc.status !== "ok" ? pc.reason : null, focalReason: fc.status !== "ok" ? fc.reason : null};
  });
  const hist = (r) => r.history || {};
  const rel = row ? row.relevance : (isFocal ? null : relevance(focal, rec));
  const cur = displayCurrency(rec, ctx);
  const chips = [{id: "subsector", text: A.engineLabels[rec.engine] || rec.engine || "", tone: "neutral", tooltip: COLUMN_BY_ID.subsector.tooltip},
    {id: "stage", text: rec.stage === "clinical" ? "Clinical" : "Commercial", tone: rec.stage === "clinical" ? "clinical" : "neutral", tooltip: COLUMN_BY_ID.stage.tooltip}];
  const model = rec.model || {};
  return {ticker: t, name: rec.name || t, isFocal, record: rec, detail: rec.detail && Object.keys(rec.detail).length ? rec.detail : null,
    inPeers: !!row, excluded: row ? row.excluded : false, relevance: rel, flags: detailFlags(A, rec),
    relevanceText: rel ? `${rel.score} of 100` : null, source: row ? row.source : null, reason: row ? row.reason : null,
    chips, against, focalTicker: focal.ticker,
    overTime: {labels: hist(rec).labels || hist(focal).labels || [],
      series: {revenue_growth: {peer: hist(rec).revenue_growth || [], focal: hist(focal).revenue_growth || []},
               net_margin: {peer: hist(rec).net_margin || [], focal: hist(focal).net_margin || []}}},
    range52w: get(rec, "market.range_52w") || null, price: numAt(rec, "market.price"),
    note: (A.state.notes || {})[t] || null,
    model: model.state === "modelled" ? {fairValue: model.fair_value_per_share, rating: model.rating, rangeToday: model.range_today,
      forward12m: model.forward_12m, pipelinePerShare: model.pipeline_per_share, pipelineUnrisked: model.pipeline_per_share_unrisked,
      note: "Model output. It does not drive the summary."} : null,
    modelState: model.state || null, currency: cur,
    actions: {makeFocal: !isFocal, exclude: !!row, excludeLabel: row && row.excluded ? "Include" : "Exclude from statistics",
      peerLabel: row ? "Remove from peers" : "Add to peers", openForecast: "Open in Forecast tab"}};
}

function buildLineage(A) {
  const {payload, focal} = A;
  const as = payload.as_of || {};
  return {priceDate: as.price_date || null, priceTradingDaysOld: as.price_trading_days_old ?? null,
    fxDate: get(payload, "fx.as_of") || null, fxSource: get(payload, "fx.source") || null,
    rates: get(payload, "fx.usd_per_unit") || {}, consensusStarts: as.consensus_history_starts || null,
    run: as.run || null, complete: payload.complete !== false, incompleteReason: payload.incomplete_reason || null,
    generatedAt: payload.generated_at || null, focal: focal.lineage || null, errors: payload.errors || [],
    universe: payload.universe || null};
}

function buildStates(A, view) {
  const out = [];
  const {payload, focal, T, state} = A;
  const c = view.conclusion;
  const cs = c ? c.state : A.primary.state;
  const as = payload.as_of || {};
  if (isNum(as.price_trading_days_old) && as.price_trading_days_old >= 1) {
    out.push(stateMsg("stale_price_universe", {date: fmtDate(as.price_date), n: as.price_trading_days_old}));
  }
  const failed = failedSourcesFor(A);
  if (failed.length) {
    const run = as.run || {};
    const bySource = {};
    for (const f of failed) (bySource[f.source] = bySource[f.source] || []).push(f.ticker == null ? "every company" : f.ticker);
    for (const [src, ts] of Object.entries(bySource)) {
      out.push(stateMsg("failed_source", {id: run.id, status: run.status, date: fmtDate(run.finished_at || run.started_at), source: src, tickers: uniq(ts).join(", ")}));
    }
  }
  const P = A.primary;
  const metric = P.colId ? proseLabel(P.colId) : "";
  if (cs === "no_peers") out.push(stateMsg("no_peers", {}));
  if (cs === "low_confidence") out.push(stateMsg("low_confidence", {k: A.pStats ? A.pStats.n : 0, metric}));
  if (cs === "too_few") {
    const fc = cell(focal, P.colId, A.ctx);
    out.push(stateMsg("too_few", {T, metric, v: proseValue(P.colId, fc.v, A.ctx, focal), who: P.k === 1 ? "one peer has" : "no peer has"}));
  }
  if (cs === "no_multiple") {
    const first = P.firstCandidate;
    const fc = first ? cell(focal, first, A.ctx) : null;
    out.push(stateMsg("no_multiple", {T, first: first ? metricLabel(first, A.ctx.basis, A.ctx) : "No candidate", reason: fc ? fc.reason : ""}));
  }
  if (A.defaultWarning === "too_few") out.push(stateMsg("default_short", {n: A.def.tickers.length, T}));
  if (A.defaultWarning === "padded") {
    const low = A.def.tickers.filter((t) => A.def.pools[t] !== "A" && A.def.scores[t] < MIN_DEFAULT_RELEVANCE).length;
    out.push(stateMsg("padded", {k: low, n: A.def.tickers.length}));
  }
  if (A.weak) out.push(stateMsg("weak", {a: A.appropriate, n: A.included.length}));
  if (A.mixed) out.push(stateMsg("mixed_models", {k: A.mixed.k, n: A.mixed.n, other: A.mixed.otherType, T, focalType: A.mixed.focalType}));
  if (view.header && view.header.typeChip) {
    const chip = view.header.typeChip;
    const id = chip.text === "Pre-revenue" ? "pre_revenue" : chip.text === "Loss-making" ? "loss_making" : "sub_scale";
    out.push({id, severity: "info", where: ["context"], title: chip.text, detail: chip.tooltip, action: null});
  }
  if (focal.stage === "clinical" && view.header) {
    out.push({id: "clinical", severity: "info", where: ["context"], title: "Clinical", detail: view.header.stageChip.tooltip, action: null});
  }
  if ((focal.flags || []).some((f) => f && f.code === "no_consensus")) {
    out.push(stateMsg("missing_estimates", {T, period: get(focal, "periods.FY0.label") || "FY0"}));
  }
  if (P.colId && A.pStats && A.pStats.outliers.extreme.length) out.push(stateMsg("extreme_outliers", {}));
  if (A.standards.ifrs > 0 && A.standards.gaap > 0) out.push(stateMsg("mixed_standards", {i: A.standards.ifrs, g: A.standards.gaap}));
  if (["NTM", "FY1", "FY2"].includes(state.basis)) out.push(stateMsg("street_vs_reported", {}));
  if (view.table) {
    const mixedCols = view.table.columns.filter((cv) => cv.basisChip && cv.basisChip.mixed);
    if (mixedCols.length) {
      const n = Math.max(...mixedCols.map((cv) => cv.basisChip.count || 0));
      out.push(stateMsg("mixed_periods", {n}));
    }
    if (view.table.empty && view.table.empty.id === "filters_empty") out.push(view.table.empty);
    for (const r of view.table.rows) if (r.error) out.push({id: `calc_failed:${r.ticker}`, severity: "red", where: ["row"], title: "Calculation failed", detail: r.error, action: null});
  }
  if (payload.complete === false) out.push(stateMsg("model_not_computed", {}));
  if (state.live === false) out.push(stateMsg("time_machine", {}));
  const br = A.bridge;
  if (br && !br.enabled && br.reason) {
    out.push({id: br.reasonId || "bridge_disabled", severity: "info", where: ["bridge"], title: "No bridge", detail: br.reason, action: null});
  }
  if (br && br.negativeEquity) out.push(stateMsg("negative_equity", {}));
  const ins = view.insight;
  if (ins) {
    if (ins.message) out.push(ins.message);
    else for (const g of [ins.catalysts, ins.competition]) if (g && g.empty) out.push(g.empty);
    if (ins.competition && ins.competition.lead) out.push(stateMsg("ranked_by_contest", {T}));
  }
  if (view.undo) out.push(stateMsg("undo", {label: view.undo.label}));
  if (state.singleKeys === false) out.push(stateMsg("single_keys_off", {}));
  out.push(stateMsg("absent_subsectors", {}));
  return out.filter(Boolean);
}

// ---------------------------------------------------------------------------------------------
// 12.3 Drivers and risks: view.insight, built from the focal context
// (GET /companies/{ticker}/comps-context, 12.2). Every string the panel draws is worded here.
// ---------------------------------------------------------------------------------------------

/** Reason codes of the context payload (12.2), worded. `{T}` is the focal ticker. */
export const CONTEXT_NA_TEXT = {
  no_asset: "The event names no asset on file.",
  no_price: "No share price on file.",
  not_modelled: "No modelled value for this asset.",
  model_not_computed: "The model value has not been computed yet. Reload in a minute.",
  no_outcome_legs: "The model holds no success and failure probabilities for this asset, so no value at stake is stated.",
  not_in_stakes: "The catalyst record names no asset, so no value at stake is stated.",
  no_indication_link: "No indication on file for this event.",
  no_attributed_asset: "No modelled asset is counted in this indication.",
  no_pool: "No modelled drug draws on a sized patient pool here.",
  single_claimant: "One modelled drug draws on this pool, so nothing is shared.",
  flow_pool: "The model sizes this disease by each year's new patients, so there is no standing pool to share.",
  claims_exceed_pool: "The modelled claims exceed the stated population, so no share of the pool is stated.",
  share_under_1pct: "The modelled drugs together claim under 1% of the pool.",
  no_claimant: "{T} has no modelled drug in the shared pool.",
};
const CONTEXT_NA_FALLBACK = "The model states no figure here.";
function contextNa(code, T) {
  if (!code) return null;
  return fill(CONTEXT_NA_TEXT[code] || CONTEXT_NA_FALLBACK, {T});
}

export const INSIGHT_COPY = {
  catalystsTitle: "Catalysts ahead",
  catalystsLink: "Open the Catalysts tab",
  catalystsNote: "Dates marked est. come from trial records. A catalyst is two-sided: it can raise or lower the value. Value figures are model output.",
  competitionTitle: "Competition by indication",
  competitionLink: "Open Comps, Indications",
  competitionNote: "Rivals are big pharma candidates that are marketed or in Phase 2 or later. Value counts each modelled asset in the indication the model sizes it in, else in its lead indication. Pool figures are model output and leave out marketed products valued off reported revenue.",
  marketedNoValue: "Marketed product. The model states no value for this {event}.",
  estimatedDate: "The date is the trial's estimated primary completion.",
  indicationsAbsent: "The Indications view opens for big pharma companies.",
  contestWhileComputing: "Model values are not computed yet, so indications are ordered by how many companies contest them.",
  premiumHeading: "Potential premium drivers",
  discountHeading: "Potential discount drivers",
  emptySide: "No observation passes the tests.",
  sectionTag: "Observations, not conclusions",
};

const CHIP_MODEL = {id: "model", text: "Model output", tone: "neutral",
  tooltip: "From the terminal's forecast model, not from a filing or a market price."};
const CHIP_TWO_SIDED = {id: "two_sided", text: "Two-sided", tone: "neutral",
  tooltip: "The outcome can raise or lower the value."};
const CHIP_DERIVED_DATE = {id: "derived_date", text: "Derived, estimated date", tone: "flag",
  tooltip: "Derived from a trial record. The date is an estimate, not a company statement."};
const CHIP_CURATED = {id: "curated", text: "Curated", tone: "neutral", tooltip: "Entered and checked by hand."};
const LINK_CATALYSTS = {kind: "tab", tab: "Catalysts"};
const LINK_FORECAST = {kind: "tab", tab: "Forecast"};

// Proper names MeSH descriptors carry. They keep their capital when a name is put in prose.
const INDICATION_EPONYMS = new Set(["alzheimer", "parkinson", "crohn", "hodgkin", "huntington", "duchenne",
  "cushing", "sjogren", "behcet", "castleman", "waldenstrom", "fabry", "gaucher", "pompe", "kawasaki", "graves",
  "paget", "raynaud", "tourette", "wilms", "ewing", "kaposi", "burkitt", "merkel", "barrett", "dravet", "rett",
  "angelman", "marfan", "niemann", "hirschsprung", "addison", "meniere", "guillain", "barre", "lennox", "gastaut",
  "prader", "willi", "friedreich", "charcot", "marie", "stargardt", "leber", "hashimoto", "takayasu", "bowen"]);
function indicationWord(word) {
  return word.split("-").map((part) => {
    const bare = part.replace(/['’]s$/, "").replace(/[^A-Za-z0-9]/g, "");
    if (!bare) return part;
    if (/^[A-Z0-9]+$/.test(bare)) return part;                        // HIV, IGA, the B of B-Cell, a number
    if (/^[A-Z]/.test(bare) && INDICATION_EPONYMS.has(bare.toLowerCase())) return part;
    return part.toLowerCase();
  }).join("-");
}
/**
 * `indicationProse(name)`: the stored MeSH name with its comma-separated parts reversed, in lower
 * case ("Pulmonary Disease, Chronic Obstructive" -> "chronic obstructive pulmonary disease").
 * Acronyms, single letters and proper names keep their capitals ("B-cell", "HIV", "Alzheimer").
 */
export function indicationProse(name) {
  const parts = String(name == null ? "" : name).split(",").map((p) => p.trim()).filter(Boolean);
  return parts.reverse().join(" ").split(/\s+/).filter(Boolean).map(indicationWord).join(" ");
}
/** `indicationTitle(name)`: `indicationProse` with a capital first letter. */
export function indicationTitle(name) { return ucfirst(indicationProse(name)); }

function usdShare(v) { return isNum(v) ? "$" + fmtNumber(v, 2) : NULL; }
function pct1(v) { return isNum(v) ? fmtNumber(v * 100, 1) + "%" : NULL; }
/** A share of price in a row: one decimal, and "under 0.1%" rather than a zero for a small positive share. */
function pctRow(v) { return isNum(v) && v > 0 && v < 0.0005 ? "under 0.1%" : pct1(v); }
function pct0(v) { return isNum(v) ? wholePct(v) + "%" : NULL; }
/** Patients in prose: "107.6m" from a million, "644k" from a thousand, the whole number below. */
export function fmtPatients(v) {
  if (!isNum(v)) return NULL;
  const a = Math.abs(v);
  if (a >= 999950) return fmtNumber(v / 1e6, 1) + "m";
  if (a >= 1000) return fmtNumber(v / 1000, 0) + "k";
  return fmtNumber(v, 0);
}

function isRegulatory(it) { return it.regulatory === true || REGULATORY_KINDS.includes(it.kind); }
function isReadout(it) { return /readout/i.test(String(it.kind || "")); }
function isLateReadout(it) { return isReadout(it) && LATE_PHASES.includes(it.phase); }
function catalystEvent(it) {
  const k = String(it.kind || "").toLowerCase();
  if (k === "data readout") return it.phase ? `${it.phase} readout` : "data readout";
  if (k === "pdufa") return "PDUFA date";
  if (k === "adcom") return "advisory committee";
  if (k === "regulatory decision") return "regulatory decision";
  if (k === "ema decision") return "EMA decision";
  return k || "event";
}
function catalystDate(it) {
  const iso = typeof it.date === "string" ? it.date : "";
  const conf = it.date_confidence;
  const estimated = !(conf === "confirmed" || conf === "stated");
  const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(iso);
  if (!m) return {dateIso: iso, dateShort: NULL, dateText: "on a date not on file", estimated};
  const y = Number(m[1]), mo = Number(m[2]), d = m[3] ? Number(m[3]) : null;
  let prec = it.date_precision || (d ? "day" : "month");
  if (prec === "day" && !d) prec = "month";
  const mon = MONTHS[mo - 1] || "";
  if (prec === "quarter") { const s = `Q${Math.ceil(mo / 3)} ${y}`; return {dateIso: iso, dateShort: s, dateText: `in ${s}`, estimated}; }
  if (prec === "half") { const s = `H${mo <= 6 ? 1 : 2} ${y}`; return {dateIso: iso, dateShort: s, dateText: `in ${s}`, estimated}; }
  if (prec === "month") { const s = `${mon} ${y}`; return {dateIso: iso, dateShort: s, dateText: `in ${s}`, estimated}; }
  const s = `${d} ${mon} ${y}`;
  return {dateIso: iso, dateShort: s, dateText: `${estimated ? "around" : "on"} ${s}`, estimated};
}
function catalystTier(it) {
  if (it.stake && isNum(it.stake.pct_of_price)) return 0;
  if (isRegulatory(it)) return 1;
  if (isLateReadout(it)) {
    return it.asset && !it.asset.is_marketed && it.asset_value && isNum(it.asset_value.pct_of_price) ? 2 : 3;
  }
  return 4;
}
function byDateThenId(a, b) {
  const da = String(a.date || ""), db = String(b.date || "");
  if (da !== db) return da < db ? -1 : 1;
  return (Number(a.id) || 0) - (Number(b.id) || 0);
}
/** Tier, then the order inside the tier (12.3), then date, then catalyst id. */
function compareCatalysts(a, b) {
  const ta = catalystTier(a), tb = catalystTier(b);
  if (ta !== tb) return ta - tb;
  if (ta === 0 && a.stake.pct_of_price !== b.stake.pct_of_price) return b.stake.pct_of_price - a.stake.pct_of_price;
  if (ta === 2 && a.asset_value.pct_of_price !== b.asset_value.pct_of_price) return b.asset_value.pct_of_price - a.asset_value.pct_of_price;
  return byDateThenId(a, b);
}
function sourceHost(url) {
  const m = /^[a-z][a-z0-9+.-]*:\/\/([^/?#]+)/i.exec(String(url || ""));
  return m ? m[1].replace(/^www\./, "") : null;
}

/** The one catalyst item a side list can carry (12.3): `catalyst_stake`, else `catalyst_value`. */
function catalystSideItem(items) {
  const sorted = items.slice().sort(byDateThenId);
  let best = null;
  for (const it of sorted) {
    if (it.stake && isNum(it.stake.pct_of_price) && (!best || it.stake.pct_of_price > best.stake.pct_of_price)) best = it;
  }
  const base = {kind: "catalyst", side: "discount", strength: 50, severity: "amber", provenance: "M", twoSided: true,
    chips: [CHIP_MODEL, CHIP_TWO_SIDED], link: LINK_CATALYSTS, linkLabel: "Catalysts tab"};
  if (best && best.stake.pct_of_price >= CATALYST_MIN_PCT) {
    const d = catalystDate(best);
    const name = best.asset && best.asset.name ? best.asset.name : "the asset";
    return {...base, id: "catalyst_stake", tag: "binary catalyst in 12 months (model)",
      text: `${pct1(best.stake.pct_of_price)} of the price, ${usdShare(Math.abs(best.stake.per_share))} a share, separates success from failure at the ${name} ${catalystEvent(best)} due ${d.dateText}. The outcome can move the value either way. Model output.`,
      catalystId: best.id, assetId: best.asset ? best.asset.id : null};
  }
  const elig = sorted.filter((it) => (isRegulatory(it) || isLateReadout(it)) && it.asset && !it.asset.is_marketed &&
    it.asset_value && it.asset_value.counted === true && isNum(it.asset_value.pct_of_price));
  let top = null;
  for (const it of elig) if (!top || it.asset_value.pct_of_price > top.asset_value.pct_of_price) top = it;
  if (!top || top.asset_value.pct_of_price < CATALYST_MIN_PCT) return null;
  // The asset's earliest such event is the one named: `elig` is in date order.
  const first = elig.find((it) => it.asset.id === top.asset.id) || top;
  const d = catalystDate(first);
  return {...base, id: "catalyst_value", tag: "pipeline value on one event (model)",
    text: `${pct1(first.asset_value.pct_of_price)} of the price, ${usdShare(first.asset_value.per_share)} a share, is the risk-adjusted value the model carries for ${first.asset.name}, whose ${catalystEvent(first)} is due ${d.dateText}. The outcome can move it either way. Model output.`,
    catalystId: first.id, assetId: first.asset.id};
}

function catalystRows(items, T, sideItem) {
  const sorted = items.slice().sort(compareCatalysts);
  const groups = new Map();
  for (const it of sorted) {
    const key = it.asset && it.asset.id != null ? `a${it.asset.id}` : `e${it.id}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(it);
  }
  const rows = [];
  for (const list of groups.values()) {
    const it = list[0];
    const d = catalystDate(it);
    const event = catalystEvent(it);
    const na = it.na || {};
    const marketed = !!(it.asset && it.asset.is_marketed);
    let modelText = null, modelKind = null, naText = null;
    if (it.stake && isNum(it.stake.per_share)) {
      modelKind = "stake";
      modelText = `at stake ${usdShare(Math.abs(it.stake.per_share))} a share` +
        (isNum(it.stake.pct_of_price) ? `, ${pctRow(it.stake.pct_of_price)} of price` : "");
    } else if (it.asset && !marketed && it.asset_value && isNum(it.asset_value.per_share)) {
      modelKind = "asset_value";
      modelText = `${usdShare(it.asset_value.per_share)} a share` +
        (isNum(it.asset_value.pct_of_price) ? `, ${pctRow(it.asset_value.pct_of_price)} of price` : "") +
        (isNum(it.asset_value.pos) ? `, PoS ${pct0(it.asset_value.pos)}` : "");
      naText = contextNa(na.stake, T);
    } else if (marketed) {
      naText = fill(INSIGHT_COPY.marketedNoValue, {event: isReadout(it) ? "readout" : "event"});
    } else {
      naText = contextNa(na.stake, T) || contextNa(na.asset_value, T) || contextNa(na.asset, T) || CONTEXT_NA_FALLBACK;
    }
    const chips = [CHIP_TWO_SIDED];
    if (modelText) chips.push(CHIP_MODEL);
    if (it.is_curated) chips.push(CHIP_CURATED);
    else if (d.estimated) chips.push(CHIP_DERIVED_DATE);
    const tooltip = [];
    if (it.title) tooltip.push(String(it.title));
    const src = it.nct_id || sourceHost(it.source_url);
    if (src) tooltip.push(`Source: ${src}`);
    if (d.estimated && !it.is_curated && it.nct_id) tooltip.push(INSIGHT_COPY.estimatedDate);
    const name = it.asset && it.asset.name ? it.asset.name : null;
    rows.push({id: `cat-${it.id}`, assetId: it.asset && it.asset.id != null ? it.asset.id : null, tier: catalystTier(it),
      dateIso: d.dateIso, dateShort: d.dateShort, dateText: d.dateText, estimated: d.estimated,
      label: name ? `${name}: ${event}` : cutAt(String(it.title || event), 60),
      indicationText: it.indication && it.indication.name ? indicationTitle(it.indication.name) : null,
      indicationNa: it.indication && it.indication.name ? null : contextNa(na.indication || "no_indication_link", T),
      moreText: list.length > 1 ? `and ${list.length - 1} more for this asset` : null,
      modelText, modelKind, naText,
      side: sideItem && ((sideItem.assetId != null && it.asset && it.asset.id === sideItem.assetId) || sideItem.catalystId === it.id) ? "discount" : null,
      chips, link: LINK_CATALYSTS, sourceUrl: it.source_url || null, tooltip});
  }
  return rows;
}

const STAGE_PARTS = [["marketed", "marketed"], ["phase3", "Phase 3"], ["phase2", "Phase 2"], ["other", "earlier"]];
function stageCounts(block) {
  const b = (block && block.by_stage) || {};
  const n0 = (k) => (isNum(b[k]) ? b[k] : 0);
  return {n: block && isNum(block.n) ? block.n : 0, marketed: n0("marketed"), phase3: n0("phase3"), phase2: n0("phase2"), other: n0("other")};
}
function stageText(c) {
  return STAGE_PARTS.filter(([k]) => c[k] > 0).map(([k, w]) => `${c[k]} ${w}`).join(", ");
}

function competitionRow(r, T) {
  const ind = r.indication || {};
  const stored = String(ind.name || "");
  const title = indicationTitle(stored);
  const prose = indicationProse(stored);
  const na = r.na || {};
  const value = r.value || {};
  const own = stageCounts(r.own);
  const rivals = {...stageCounts(r.rivals), companies: r.rivals && isNum(r.rivals.companies) ? r.rivals.companies : 0};
  const hasValue = isNum(value.per_share) && value.per_share !== 0;
  const valueText = hasValue ? usdShare(value.per_share) + (isNum(value.pct_of_price) ? `${MID}${pctRow(value.pct_of_price)}` : "") : null;
  // An indication's value is the company's, so "not modelled" is worded for the company here.
  const valueNa = hasValue ? null : (na.value === "not_modelled" ? NA_TEXT.not_modelled : contextNa(na.value || "no_attributed_asset", T));
  const ownParts = stageText(own), rivalParts = stageText(rivals);
  const ownText = `${own.n} own${ownParts ? `: ${ownParts}` : ""}`;
  const rivalsText = `${rivals.n} ${plural(rivals.n, "rival", "rivals")}` +
    (rivals.n > 0 ? ` from ${rivals.companies} ${plural(rivals.companies, "company", "companies")}` : "") +
    (rivalParts ? `: ${rivalParts}` : "");
  const pool = r.pool || null, crowd = r.crowding || null;
  const cp = crowd && r.company_pool ? r.company_pool : null;
  const poolReason = contextNa(na.pool, T) || contextNa(na.crowding, T);
  const poolText = crowd && isNum(crowd.uncrowded_share) && isNum(crowd.crowded_share)
    ? `${pct0(crowd.uncrowded_share)} → ${pct0(crowd.crowded_share)}` : null;
  const poolNa = poolText ? null : (poolReason || CONTEXT_NA_FALLBACK);
  const shareText = cp && isNum(cp.share_of_claims) && isNum(cp.rank) && isNum(cp.of_companies)
    ? `${pct0(cp.share_of_claims)}, ${ordinal(cp.rank)} of ${cp.of_companies}` : null;
  const shareNa = shareText ? null : (contextNa(na.company_pool, T) || poolReason || CONTEXT_NA_FALLBACK);
  const link = {kind: "indication", indicationId: ind.id, name: title};
  const pctOk = isNum(value.pct_of_price) && value.pct_of_price >= COMPETITION_MIN_PCT;
  const items = [];
  if (cp && pool && pctOk) {
    const k = isNum(cp.claimants) ? cp.claimants : 0;
    const base = {kind: "competition", strength: 50, provenance: "M", twoSided: false, chips: [CHIP_MODEL], link,
      linkLabel: `${title}, landscape`};
    const n = isNum(pool.pooled_claimants) ? pool.pooled_claimants : pool.claimants;
    if (k >= 1 && isNum(n) && isNum(pool.patients) && isNum(cp.keeps) && cp.keeps <= POOL_KEEP_MAX) {
      const lead = k === 1
        ? `${pct0(cp.keeps)} of its own forecast is what ${T}'s 1 modelled ${prose} candidate keeps`
        : `${pct0(cp.keeps)} of their own forecast is what ${T}'s ${k} modelled ${prose} candidates keep`;
      items.push({...base, id: `pool_rationed:${ind.id}`, side: "discount", severity: "amber", tag: "shared patient pool (model)",
        text: `${lead} once ${n} modelled drugs share one pool of ${fmtPatients(pool.patients)} patients. Model output.`});
    }
    if (k >= 1 && cp.rank === 1 && isNum(cp.of_companies) && cp.of_companies >= POOL_LEAD_MIN_COMPANIES &&
        isNum(cp.share_of_claims) && cp.share_of_claims >= POOL_LEAD_MIN_SHARE) {
      items.push({...base, id: `pool_lead:${ind.id}`, side: "premium", severity: "info", tag: "largest share of a shared pool (model)",
        text: `${pct0(cp.share_of_claims)} of the patients the modelled drugs start in ${prose} go to ${T}'s ${k} ${plural(k, "candidate", "candidates")}, the largest share of ${cp.of_companies} companies. Model output.`});
    }
  }
  const sides = items.map((i) => i.side);
  const side = sides.includes("premium") && sides.includes("discount") ? "both" : (sides[0] || null);
  const members = Array.isArray(ind.members) ? ind.members.filter(Boolean) : [];
  const tooltip = [`Stored as ${stored}.`];
  if (members.length > 1) tooltip.push(`One population under ${members.length} names: ${members.join("; ")}.`);
  if (crowd && pool && poolText) {
    const n = isNum(pool.pooled_claimants) ? pool.pooled_claimants : pool.claimants;
    const from = isNum(pool.companies) ? ` from ${pool.companies} ${plural(pool.companies, "company", "companies")}` : "";
    const peak = crowd.peak_year != null ? ` at the ${crowd.peak_year} peak` : "";
    if (isNum(n) && isNum(pool.patients)) {
      tooltip.push(`${n} modelled ${plural(n, "drug", "drugs")}${from} ${plural(n, "claims", "claim")} ${pct0(crowd.uncrowded_share)} of ${fmtPatients(pool.patients)} patients${peak}. Counted once, the pool supplies ${pct0(crowd.crowded_share)}.`);
    }
  }
  if (cp && isNum(cp.keeps) && isNum(cp.claimants)) {
    const k = cp.claimants;
    tooltip.push(`${T}'s ${k} ${plural(k, "keeps", "keep")} ${pct0(cp.keeps)} of ${plural(k, "its own forecast", "their own forecasts")}` +
      (isNum(cp.share_of_pool) ? ` and ${pct0(cp.share_of_pool)} of the pool.` : "."));
  }
  const cands = (r.own && Array.isArray(r.own.candidates)) ? r.own.candidates : [];
  const stageWord = (s) => (STAGE_PARTS.find(([k]) => k === s) || [null, "stage not on file"])[1];
  for (const c of cands) {
    tooltip.push(`${c.name}: ${stageWord(c.stage)}, ${isNum(c.per_share) ? `${usdShare(c.per_share)} a share` : "no modelled value counted here"}.`);
  }
  if (r.own && isNum(r.own.more) && r.own.more > 0) tooltip.push(`And ${r.own.more} more own ${plural(r.own.more, "candidate", "candidates")}.`);
  const row = {id: `ind-${ind.id}`, indicationId: ind.id, name: title, storedName: stored, valueText, valueNa,
    own, rivals, ownText, rivalsText, poolText, poolNa, shareText, shareNa, side,
    provenance: valueText || poolText || shareText ? "M" : "S", link, tooltip};
  return {row, items};
}

/**
 * `insightFor(A, context)` -> view.insight (12.3). `A` is the analysis of deriveView. The
 * metric-linked observations always show; the two evidence groups follow the context's state.
 */
function buildInsight(A, context) {
  const T = A.T;
  const obs = A.obs || {premium: [], discount: [], notAssessed: [], suppressed: []};
  const metricItem = (o) => ({id: o.id, kind: "metric", side: o.side, text: o.long, tag: o.tag, strength: o.strength,
    severity: o.severity, provenance: o.provenance, twoSided: false, chips: o.provenance === "M" ? [CHIP_MODEL] : [],
    link: {kind: "column", colId: o.colId}, linkLabel: (COLUMN_BY_ID[o.colId] || {}).label || o.colId});
  const notAssessed = (obs.notAssessed || []).concat((obs.suppressed || []).map((s) => s.text).filter(Boolean));
  const out = {ticker: T, state: "ok", message: null, notice: null,
    valuation: {premium: obs.premium.map(metricItem), discount: obs.discount.map(metricItem), notAssessed,
      premiumHeading: INSIGHT_COPY.premiumHeading, discountHeading: INSIGHT_COPY.discountHeading,
      emptyText: INSIGHT_COPY.emptySide, maxMetric: INSIGHT_ROWS},
    catalysts: {state: "pending", title: INSIGHT_COPY.catalystsTitle, countText: "", rows: [], note: INSIGHT_COPY.catalystsNote,
      empty: null, link: LINK_CATALYSTS, linkLabel: INSIGHT_COPY.catalystsLink},
    competition: {state: "pending", title: INSIGHT_COPY.competitionTitle, countText: "", rows: [], note: INSIGHT_COPY.competitionNote,
      empty: null, lead: null, link: null, linkLabel: INSIGHT_COPY.competitionLink,
      columns: ["Indication", `${T} value, $ a share${MID}of price`, "Own / rivals", "Pool claimed → supplied", `${T} share`]}};
  const blockBoth = (state, msg) => {
    out.state = state; out.message = msg;
    out.catalysts.state = state; out.catalysts.empty = msg;
    out.competition.state = state; out.competition.empty = msg;
    return out;
  };
  if (!context || typeof context !== "object" || context.ticker !== T) {
    return blockBoth("pending", stateMsg("context_pending", {T}));
  }
  if (context.error != null) {
    return blockBoth("error", stateMsg("context_error", {T, error: stripStop(String(context.error)) || "no answer"}));
  }
  if (context.schema !== CONTEXT_SCHEMA) {
    return blockBoth("error", stateMsg("schema", {expected: CONTEXT_SCHEMA, got: context.schema != null ? context.schema : "none"},
      {where: ["catalysts", "competition"], severity: "amber"}));
  }
  if (context.complete === false) out.notice = CONTEXT_NA_TEXT.model_not_computed;

  // Catalysts ahead.
  const cat = context.catalysts;
  let sideItem = null;
  if (!cat || !Array.isArray(cat.items)) {
    out.catalysts.state = "error";
    out.catalysts.empty = stateMsg("context_error", {T, error: "the answer carries no catalysts"}, {where: ["catalysts"]});
  } else {
    const items = cat.items.filter((it) => it && typeof it === "object");
    const total = isNum(cat.total) ? cat.total : items.length;
    if (total > 0 && !items.length) {
      out.catalysts.state = "error";
      out.catalysts.empty = stateMsg("context_error", {T, error: "the answer counts catalysts and carries none"}, {where: ["catalysts"]});
    } else if (total === 0) {
      out.catalysts.state = "empty";
      const w = context.window || {};
      out.catalysts.empty = stateMsg("no_catalysts", {T, from: fmtDate(w.from), to: fmtDate(w.to)});
      out.catalysts.countText = "0 in 12 months";
    } else {
      sideItem = catalystSideItem(items);
      out.catalysts.rows = catalystRows(items, T, sideItem);
      out.catalysts.state = "ok";
      const n = out.catalysts.rows.length;
      out.catalysts.countText = `${total} in 12 months, ${n} ${plural(n, "asset", "assets")}`;
    }
  }

  // Competition by indication.
  const comp = context.competition;
  const poolItems = [];
  if (!comp || typeof comp !== "object") {
    out.competition.state = "error";
    out.competition.empty = stateMsg("context_error", {T, error: "the answer carries no competition"}, {where: ["competition"]});
  } else if (comp.covered === false && comp.reason !== "no_indications") {
    out.competition.state = "not_covered";
    const n = numAt(A.payload, "universe.engines.pharma") || A.companies.filter((c) => c.engine === "pharma").length || null;
    const engine = A.engineLabels[A.focal.engine] || A.focal.engine || "another";
    const m = stateMsg("competition_not_covered", {T, n, engine});
    if (!n) m.detail = m.detail.replace("the {n} big pharma", "the big pharma");
    if (comp.reason && comp.reason !== "not_big_pharma") m.detail = `The API gives the reason as ${String(comp.reason).replace(/_/g, " ")}.`;
    out.competition.empty = m;
  } else if (comp.covered === false || !Array.isArray(comp.indications) || !comp.indications.length) {
    out.competition.state = "empty";
    out.competition.empty = stateMsg("no_indications", {T});
  } else {
    out.competition.state = "ok";
    for (const r of comp.indications) {
      if (!r || !r.indication) continue;
      const built = competitionRow(r, T);
      out.competition.rows.push(built.row);
      poolItems.push(...built.items);
    }
    const n = out.competition.rows.length;
    if (comp.ranked_by === "contest") {
      out.competition.countText = `${n} of ${isNum(comp.total) ? comp.total : n} indications, by contest`;
      // A company with a model whose values are still being computed is not "without a modelled value".
      const waiting = context.complete === false || (context.model && context.model.state === "not_computed");
      out.competition.lead = waiting ? INSIGHT_COPY.contestWhileComputing : fill(STATE_COPY.ranked_by_contest.detail, {T});
    } else {
      out.competition.countText = `${n} of ${isNum(comp.valued) ? comp.valued : n} valued indications`;
    }
    out.competition.link = out.competition.rows.length ? out.competition.rows[0].link : null;
  }

  // Side lists: metric items by strength, then the catalyst item, then competition items in row order.
  if (sideItem) {
    out.valuation.discount = out.valuation.discount.filter((i) => i.id !== "binary_catalysts");
    const {catalystId, assetId, ...item} = sideItem;
    out.valuation.discount.push(item);
  }
  for (const i of poolItems) (i.side === "premium" ? out.valuation.premium : out.valuation.discount).push(i);
  return out;
}

/** Footer line (12.6): one line of dates and the run, amber under the "Data as of" rule. */
function buildFooter(A) {
  const {payload, focal} = A;
  const as = payload.as_of || {};
  const run = as.run || {};
  const priceDate = as.price_date || get(focal, "market.price_as_of");
  const cons = get(focal, "street.consensus_checked_at");
  const fxDate = get(payload, "fx.as_of");
  const parts = [
    priceDate ? `Prices close ${fmtDate(priceDate)}` : "No price date on file",
    cons ? `consensus checked ${fmtDate(cons)}` : "no consensus check on file",
    fxDate ? `FX ECB ${fmtDate(fxDate)}` : "no FX date on file",
    run.id != null ? `refresh run ${run.id}, ${run.status || "status not recorded"}` : "no refresh run on file",
    "saved in this browser only",
  ];
  const focalStale = (focal.flags || []).some((f) => f && f.code === "stale_price");
  return {text: parts.join(MID), tone: failedSourcesFor(A).length || focalStale ? "flag" : "neutral",
    buttonLabel: "Sources and method", anchor: "sources"};
}

/** Basis chip of the context bar (12.6): names each choice that is not the default. */
function buildBasisChip(A) {
  const {state, payload} = A;
  const bt = payload.basis_text || {};
  const parts = [];
  if (state.currency === "REPORTED") parts.push("as reported");
  else if (state.currency && state.currency !== "USD") parts.push(state.currency);
  if (state.earnings === "adjusted") parts.push("ex amort.");
  const rep = state.currency === "REPORTED";
  const base = rep ? (bt.as_reported || "") : (bt.standardised || "").replace(/\{cur\}/g, state.currency || "USD");
  const lines = [];
  if (base) lines.push(stripStop(base) + ".");
  lines.push(state.earnings === "adjusted"
    ? `Earnings ex amort. and IPR&D${bt.adjusted ? `: ${lcfirst(stripStop(bt.adjusted))}` : ""}.`
    : "Earnings as filed under GAAP or IFRS.");
  if (["NTM", "FY1", "FY2"].includes(state.basis) && bt.street) lines.push(`Forward earnings: ${stripStop(bt.street)}.`);
  return {text: parts.length ? `Basis: ${parts.join(", ")}` : "Basis", nonDefault: parts.length > 0, tooltip: lines.join(" ")};
}

/** "View" button badge of the table toolbar (12.7): the settings away from their defaults. */
function buildViewBadge(A) {
  const s = A.state;
  const lines = [];
  if (A.groupName) lines.push(`Statistics over ${A.groupName}`);
  if (s.outliers === "exclude") lines.push("Outliers excluded");
  if (s.cfMode && s.cfMode !== "off") lines.push(`Format: ${lcfirst(CF_MODE_LABEL[s.cfMode] || s.cfMode)}`);
  if (s.density && s.density !== "default") lines.push(`${ucfirst(s.density)} rows`);
  if (isNum(s.textSize) && s.textSize !== 13) lines.push(`Text ${s.textSize} px`);
  if (s.summaryRows === false) lines.push("Summary rows off");
  return {count: lines.length, lines, label: lines.length ? `View${MID}${lines.length}` : "View"};
}

/** Context line of the bridge-only frame (12.5). */
function buildBridgeLine(A) {
  const br = A.bridge;
  const head = `${A.T} against ${A.label.full}`;
  const linkLabel = "Change peers or metric in Comps";
  const storageLine = "Peer set and inputs are saved in this browser only.";
  const c = br ? COLUMN_BY_ID[br.colId] : null;
  if (!br || !br.enabled || !c || !isNum(br.M)) return {text: `${head}.`, linkLabel, storageLine};
  const label = c.bases.length > 1 ? `${c.label} (${basisWord(br.basis, A.ctx)})` : c.label;
  const M = br.colId === "fcf_yield" ? fmtPctProse(br.M) : fmtNumber(br.M, br.colId === "peg" ? 2 : 1) + TIMES;
  const n = A.statsRows.length, k = br.peerN;
  const what = isNum(br.inputs.multipleOverride) ? `analyst ${label} of ${M}` : `peer ${statWord(br.stat, br.pct)} ${label} of ${M}`;
  return {text: `${head}: ${what}, ${k} of ${n} ${plural(n, "peer", "peers")} with a value.`, linkLabel, storageLine};
}

/** What marks a ticker (12.7): only a flag that cost a confidence point, a failed source, a failed calculation. */
function tickerFlagInfo(A) {
  const out = {focal: [], derivedPeers: new Set()};
  const P = A.primary;
  const scored = !["too_few", "no_multiple", "no_peers", "error"].includes(conclusionState(A)) && P && P.colId && A.pStats;
  if (!scored) return out;
  out.focal = uniq(costingFlags(A).map((f) => f.code));
  const st = A.pStats;
  const flagsOf = (t) => cell(A.byTicker[t], P.colId, A.ctx).flags;
  const derived = st.tickers.filter((t) => flagsOf(t).includes("derived_operating_income")).length;
  if (st.n > 0 && derived / st.n > MAX_DERIVED_SHARE) {
    for (const t of st.tickers) {
      const fl = flagsOf(t);
      if (fl.includes("derived_operating_income") || fl.includes("derived_no_addback")) out.derivedPeers.add(t);
    }
  }
  return out;
}
function tickerFlagsFor(A, info, r) {
  const rec = r.record;
  const codes = [], lines = [];
  const add = (code, text) => { if (!codes.includes(code)) codes.push(code); if (text && !lines.includes(text)) lines.push(text); };
  const textOf = (code) => {
    const f = (rec.flags || []).find((x) => x && x.code === code);
    return flagText(f || code, rec).text;
  };
  if (rec.error) add("calc_failed", flagText({code: "calc_failed", params: {message: rec.error}}).text);
  if (r.isFocal) for (const code of info.focal) add(code, textOf(code));
  else if (info.derivedPeers.has(r.ticker)) {
    for (const code of cell(rec, A.primary.colId, A.ctx).flags) {
      if (code === "derived_operating_income" || code === "derived_no_addback") add(code, textOf(code));
    }
  }
  for (const f of rec.flags || []) {
    if (f && f.code === "source_failed" && VIEW_SOURCES.includes(get(f, "params.source"))) add("source_failed", flagText(f, rec).text);
  }
  return {codes, lines};
}

const SEVERITY_RANK = {red: 0, amber: 1, info: 2};
/** Every flag of a company with the column labels it marks (12.7, side panel "Data flags"). */
function detailFlags(A, rec) {
  if (rec.error) {
    return [{code: "calc_failed", severity: "red", text: flagText({code: "calc_failed", params: {message: rec.error}}).text, cells: []}];
  }
  const ctx = A.ctx;
  const cells = COLUMNS.map((c) => ({c, cc: cell(rec, c.id, ctx)}));
  const out = [];
  const recCodes = new Set();
  for (const f of rec.flags || []) {
    if (!f || !f.code) continue;
    recCodes.add(f.code);
    out.push({code: f.code, severity: sevOf(f), text: flagText(f, rec).text,
      cells: cells.filter(({c, cc}) => flagMarks(f, c.id, cc.periodKey, rec)).map(({c}) => c.label)});
  }
  const client = new Map();
  for (const {c, cc} of cells) {
    for (const code of cc.flags) {
      if (recCodes.has(code)) continue;
      if (!client.has(code)) client.set(code, []);
      if (cc.marks.includes(code)) client.get(code).push(c.label);
    }
  }
  for (const [code, labels] of client) out.push({code, severity: sevOf(code), text: flagText(code, rec).text, cells: labels});
  return out.map((f, i) => ({f, i})).sort((a, b) => ((SEVERITY_RANK[a.f.severity] ?? 3) - (SEVERITY_RANK[b.f.severity] ?? 3)) || (a.i - b.i)).map((x) => x.f);
}

/**
 * `paletteExtras(view, state)`: the generated palette entries of 7.3, for
 * `matchCommands(query, COMMANDS, paletteExtras(view, state))`. Each entry is
 * {id, label, group, key: null, command?: string, action?: object, target?: object, link?: Link}: run
 * `command` like a COMMANDS id, dispatch `action`, scroll to `target` (a column, or one of the
 * sections "obs", "charts" and "table"), or follow `link` with `ctx.openLink` (12.9).
 */
export function paletteExtras(view, state) {
  const out = [];
  if (!view || !view.analysis) return out;
  const A = view.analysis;
  const inSet = new Set(A.setRows.map((r) => r.ticker));
  for (const c of COLUMNS) {
    out.push({id: `col:${c.id}`, label: `Go to column ${lcfirst(c.label)}`, group: "Columns", key: null,
      action: {type: "SHOW_COLUMN", colId: c.id}, target: {kind: "column", colId: c.id}});
  }
  for (const [id, name] of [["obs", "drivers and risks"], ["charts", "peer position"], ["table", "comparable companies"]]) {
    out.push({id: `section:${id}`, label: `Go to section ${name}`, group: "Sections", key: null, target: {kind: "section", id}});
  }
  const compRows = (view.insight && view.insight.competition && view.insight.competition.rows) || [];
  for (const r of compRows) {
    out.push({id: `indication:${r.indicationId}`, label: `${INSIGHT_COPY.competitionLink}: ${r.name}`, group: "Sections", key: null, link: r.link});
  }
  for (const c of A.companies) {
    if (c.ticker === A.T) continue;
    if (inSet.has(c.ticker)) out.push({id: `remove:${c.ticker}`, label: `Remove peer ${c.ticker}`, group: "Peers", key: null, action: {type: "REMOVE_PEER", ticker: c.ticker}});
    else if (!c.error) out.push({id: `add:${c.ticker}`, label: `Add peer ${c.ticker} ${c.name || ""}`.trim(), group: "Peers", key: null, action: {type: "ADD_PEER", ticker: c.ticker}});
    out.push({id: `open:${c.ticker}`, label: `Open ${c.ticker}`, group: "Companies", key: null, action: {type: "OPEN_DETAIL", ticker: c.ticker}});
    out.push({id: `focal:${c.ticker}`, label: `Make ${c.ticker} focal`, group: "Companies", key: null, command: "focus", ticker: c.ticker});
  }
  for (const b of BASES) out.push({id: `basis:${b}`, label: `Set period ${b}`, group: "Basis", key: null, action: {type: "SET_BASIS", basis: b}});
  for (const cur of CURRENCIES) {
    out.push({id: `cur:${cur}`, label: `Set currency ${cur === "REPORTED" ? "as reported" : cur}`, group: "Basis", key: null, action: {type: "SET_CURRENCY", currency: cur}});
  }
  for (const name of Object.keys((state && state.savedSets) || {})) {
    out.push({id: `loadset:${name}`, label: `Load peer set '${name}'`, group: "Peers", key: null, action: {type: "LOAD_SET", name}});
  }
  for (const name of Object.keys((state && state.layouts) || {})) {
    out.push({id: `loadlayout:${name}`, label: `Load layout '${name}'`, group: "Table", key: null, action: {type: "LOAD_LAYOUT", name}});
    out.push({id: `deletelayout:${name}`, label: `Delete layout '${name}'`, group: "Table", key: null, action: {type: "DELETE_LAYOUT", name}});
  }
  out.push({id: "export:csv", label: "Export CSV", group: "Export", key: null, command: "export.csv"});
  out.push({id: "singlekeys", label: `Turn single-key shortcuts ${state && state.singleKeys === false ? "on" : "off"}`, group: "General", key: null,
    action: {type: "SET_SINGLE_KEYS", on: !!(state && state.singleKeys === false)}});
  return out;
}

// ---------------------------------------------------------------------------------------------
// Export: CSV, TSV and the plain-text summary
// ---------------------------------------------------------------------------------------------

function csvEscape(s) {
  const t = s == null ? "" : String(s);
  return /[",\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
}
function exportColumns(view) {
  return ((view.table && view.table.columns) || []).filter((c) => !["exp", "incl", "rel"].includes(c.id));
}
function exportHeader(cv) {
  if (cv.id === "company" || cv.id === "ticker") return cv.label;
  const parts = [cv.unitText, cv.basisChip ? cv.basisChip.text : null, cv.provenanceWord].filter(Boolean);
  return `${cv.label} (${parts.join(", ")})`;
}
function exportValue(cv, c) {
  if (!c) return "";
  if (cv.id === "company" || cv.id === "ticker") return c.text;
  const col = COLUMN_BY_ID[cv.id];
  if (c.status === "nm") return "n.m.";
  if (c.status === "nb") return "no burn";
  if (c.status !== "ok") return "";
  if (isNumericCol(col)) { const v = displayValue(c, col); return isNum(v) ? String(v) : ""; }
  if (col && col.fmt === "spark") return "";
  return c.text || "";
}
function exportRows(view) {
  const cols = exportColumns(view);
  const rows = [cols.map(exportHeader)];
  for (const r of (view.table && view.table.rows) || []) rows.push(cols.map((cv) => exportValue(cv, r.cells[cv.id])));
  const summary = [];
  for (const s of (view.table && view.table.summary) || []) {
    summary.push(cols.map((cv, i) => {
      if (i === 0) return s.label;
      const sc = s.cells[cv.id];
      if (!sc || !isNum(sc.v)) return "";
      if (s.id === "n") return String(sc.v);
      const v = displayValue({status: "ok", v: sc.v}, COLUMN_BY_ID[cv.id]);
      return isNum(v) ? String(v) : "";
    }));
  }
  return {rows, summary};
}

export function toCSV(view) {
  if (!view || !view.table) return "";
  const T = view.focal ? view.focal.ticker : "";
  const setFull = view.header ? view.header.peerSet.full : "";
  const basis = view.ctx ? view.ctx.basis : "";
  const curLabel = view.ctx ? view.ctx.currencyLabel : "";
  const gen = view.lineage ? view.lineage.generatedAt : "";
  const {rows, summary} = exportRows(view);
  const lines = [`# Comps for ${T}, ${setFull}, basis ${basis}, ${curLabel}, generated ${gen}`];
  for (const r of rows) lines.push(r.map(csvEscape).join(","));
  lines.push("");
  for (const r of summary) lines.push(r.map(csvEscape).join(","));
  lines.push("");
  const fxText = view.ctx ? view.ctx.fxText : "";
  const bt = view.ctx ? view.ctx.basisText : "";
  lines.push(`# Prices ${view.lineage ? view.lineage.priceDate : ""}; FX ${fxText}; ${bt}`);
  return lines.join("\n") + "\n";
}

export function toTSV(view) {
  if (!view || !view.table) return "";
  const {rows, summary} = exportRows(view);
  const clean = (s) => String(s == null ? "" : s).replace(/[\t\r\n]+/g, " ");
  const lines = rows.map((r) => r.map(clean).join("\t"));
  lines.push("");
  for (const r of summary) lines.push(r.map(clean).join("\t"));
  return lines.join("\n") + "\n";
}

export function csvFilename(view) {
  const T = view && view.focal ? view.focal.ticker : "view";
  const basis = view && view.ctx ? view.ctx.basis : "";
  const d = isoToCompact(view && view.lineage ? (view.lineage.generatedAt || view.lineage.priceDate) : "");
  return `comps_${T}_${basis}_${d}.csv`;
}

export function summaryText(view) {
  if (!view || !view.conclusion) return "";
  const c = view.conclusion;
  const lines = [c.headline, c.support, c.label];
  if (c.confidence && c.confidence.level) lines.push(`Confidence: ${c.confidence.level}`);
  for (const k of view.kpis || []) {
    lines.push(`${k.label}: ${k.value}${k.unit ? " " + k.unit : ""} (${k.period})${k.compare ? "; " + k.compare : ""}`);
  }
  if (view.bridge && view.bridge.description) lines.push(`Bridge: ${view.bridge.description}`);
  if (view.header) lines.push(`Peers: ${view.header.peerSet.full}`);
  if (view.ctx) lines.push(`Basis: ${view.ctx.basisLabel}, ${view.ctx.currencyLabel}, ${view.ctx.earningsLabel}`);
  return lines.filter(Boolean).join("\n");
}
