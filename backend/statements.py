"""Three-statement line map and period classification for EDGAR company facts.

Two jobs, both pure:

1. ``LINES`` names every line we present on the income statement, balance sheet, and
   cash flow statement, and lists the XBRL concepts each one may live under. Concept
   choice is per filer and drifts over time, so every line is a priority list rather
   than a single tag. Lilly never tags GrossProfit and JNJ stopped tagging
   OperatingIncomeLoss in 2015, so a line that resolves for one filer is routinely
   absent for the next. Absent means absent: it renders as a dash, never a zero.

2. ``classify_period`` turns a company-facts entry into a period key. The same concept
   carries full years, discrete quarters, cumulative year-to-date spans, and balance
   sheet instants in one list, distinguished only by their start and end dates.

Cash flow in a 10-Q is cumulative from the year start, not a discrete quarter: Lilly's
Q3 2025 operating cash flow reads 13.588bn covering January to September. Those land
under YTD and are presented as reported. Differencing consecutive quarters would look
tidier and would silently go wrong whenever an earlier quarter is restated, and it
would publish a figure the filer never did.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

# Forms that carry the periods we present. Annual reports for US and foreign filers,
# and the interim reports each of them files.
FORMS = ("10-K", "10-Q", "20-F", "6-K")

# Period types, as stored in financials.period_type.
FY = "FY"            # a full reported year
Q = "Q"              # a discrete three month period
YTD = "YTD"          # cumulative from the year start: six or nine months
INSTANT = "instant"  # a balance sheet date

DURATION_TYPES = (FY, Q, YTD)


@dataclass(frozen=True)
class Line:
    """One row of one statement.

    ``candidates`` are tried in order and the first that reaches the latest period wins
    (see pick_series). ``derived`` computes the line from two other lines when the filer
    does not tag it; it is exact arithmetic on reported values, and the API marks any
    value produced this way so the UI can say so.
    """

    key: str                      # stored in financials.metric
    label: str
    statement: str                # income | balance | cashflow
    kind: str                     # duration | instant
    candidates: tuple[tuple[str, str], ...] = ()
    derived: tuple[str, str, str] | None = None   # (left_key, "-", right_key)
    role: str = "item"            # item | subtotal | total | memo
    note: str = ""
    # Whether consecutive periods of this line sum. Flows do; per-share figures and
    # averages do not. A fourth quarter is the reported year less the reported nine
    # months, which is only a fact for a line that adds up: doing it to earnings per
    # share would invent a number, since the share count moves between periods.
    additive: bool = True


# Keys that predate this module stay spelled exactly as they were. comps.py and the
# financials snapshot read them by name, and renaming would orphan the stored history.
_INCOME = (
    Line("Revenues", "Revenue", "income", "duration", role="total", candidates=(
        ("us-gaap", "Revenues"),
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
        ("us-gaap", "SalesRevenueNet"),
        # What a filer used before ASC 606 moved revenue to the contract concepts
        # in 2018. Johnson & Johnson tagged this from 2009 to 2017 and nothing
        # else, so without it their history starts in 2018.
        ("us-gaap", "SalesRevenueGoodsNet"),
        ("us-gaap", "SalesRevenueServicesNet"),
        ("ifrs-full", "Revenue"),
        ("ifrs-full", "RevenueFromContractsWithCustomers"),
        ("ifrs-full", "RevenueFromSaleOfGoods"),
    )),
    Line("CostOfRevenue", "Cost of sales", "income", "duration", candidates=(
        ("us-gaap", "CostOfGoodsAndServicesSold"),
        ("us-gaap", "CostOfRevenue"),
        ("us-gaap", "CostOfGoodsSold"),
        ("ifrs-full", "CostOfSales"),
    )),
    Line("GrossProfit", "Gross profit", "income", "duration", role="subtotal",
         derived=("Revenues", "-", "CostOfRevenue"), candidates=(
             ("us-gaap", "GrossProfit"),
             ("ifrs-full", "GrossProfit"),
         )),
    # The excluding-acquired concept is tried first on purpose. A filer tagging both is
    # using the plain one for the acquired in-process component alone: JNJ puts 0.11bn
    # there against 14.66bn of real spend.
    Line("ResearchAndDevelopmentExpense", "R&D", "income", "duration", candidates=(
        ("us-gaap", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"),
        ("us-gaap", "ResearchAndDevelopmentExpense"),
        ("ifrs-full", "ResearchAndDevelopmentExpense"),
    )),
    Line("SellingGeneralAndAdministrative", "SG&A", "income", "duration", candidates=(
        ("us-gaap", "SellingGeneralAndAdministrativeExpense"),
        ("us-gaap", "GeneralAndAdministrativeExpense"),
        ("ifrs-full", "SellingGeneralAndAdministrativeExpense"),
        ("ifrs-full", "AdministrativeExpense"),
    )),
    Line("OperatingIncomeLoss", "Operating income", "income", "duration", role="subtotal",
         note="Many filers stop tagging this; JNJ last did in 2015.", candidates=(
             ("us-gaap", "OperatingIncomeLoss"),
             ("ifrs-full", "ProfitLossFromOperatingActivities"),
         )),
    Line("IncomeBeforeTax", "Income before tax", "income", "duration", role="subtotal",
         candidates=(
             ("us-gaap",
              "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
             ("us-gaap",
              "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
             ("ifrs-full", "ProfitLossBeforeTax"),
         )),
    Line("IncomeTaxExpense", "Income tax", "income", "duration", candidates=(
        ("us-gaap", "IncomeTaxExpenseBenefit"),
        ("ifrs-full", "IncomeTaxExpenseContinuingOperations"),
    )),
    Line("NetIncomeLoss", "Net income", "income", "duration", role="total", candidates=(
        ("us-gaap", "NetIncomeLoss"),
        ("ifrs-full", "ProfitLoss"),
    )),
    Line("EarningsPerShareDiluted", "Diluted EPS", "income", "duration", role="memo",
         additive=False, candidates=(
             ("us-gaap", "EarningsPerShareDiluted"),
             ("ifrs-full", "DilutedEarningsLossPerShare"),
         )),
    Line("WeightedAverageDilutedShares", "Diluted shares", "income", "duration",
         role="memo", additive=False, candidates=(
             ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding"),
             ("ifrs-full",
              "WeightedAverageNumberOfDilutedOrdinarySharesOutstanding"),
         )),
)

_BALANCE = (
    Line("CashAndEquivalents", "Cash and equivalents", "balance", "instant", candidates=(
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
        ("us-gaap",
         "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
        ("ifrs-full", "CashAndCashEquivalents"),
    )),
    # A clinical-stage biotech keeps its runway in marketable securities, not in the
    # cash line, and tags them half a dozen ways. Reading only the two tags this began
    # with put Intellia's liquidity at 135m against a real 376m, and its runway at four
    # months against twelve, which is the difference between a going-concern alarm and a
    # normal financing calendar.
    Line("ShortTermInvestments", "Short-term investments", "balance", "instant",
         candidates=(
             ("us-gaap", "ShortTermInvestments"),
             ("us-gaap", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"),
             ("us-gaap", "MarketableSecuritiesCurrent"),
             ("us-gaap", "AvailableForSaleSecuritiesCurrent"),
             ("us-gaap", "DebtSecuritiesAvailableForSaleCurrent"),
             ("us-gaap", "OtherShortTermInvestments"),
             ("ifrs-full", "CurrentFinancialAssetsAtFairValueThroughProfitOrLoss"),
         )),
    # Held separately because it is not working capital. A company can reach it, and its
    # own runway guidance counts it, but a reader should be able to see the split.
    Line("LongTermInvestments", "Long-term investments", "balance", "instant",
         candidates=(
             ("us-gaap", "MarketableSecuritiesNoncurrent"),
             ("us-gaap", "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent"),
             ("us-gaap", "AvailableForSaleSecuritiesNoncurrent"),
             ("us-gaap", "LongTermInvestments"),
         )),
    Line("AccountsReceivable", "Receivables", "balance", "instant", candidates=(
        ("us-gaap", "AccountsReceivableNetCurrent"),
        ("ifrs-full", "TradeAndOtherCurrentReceivables"),
    )),
    Line("Inventory", "Inventory", "balance", "instant", candidates=(
        ("us-gaap", "InventoryNet"),
        ("ifrs-full", "Inventories"),
    )),
    Line("TotalCurrentAssets", "Total current assets", "balance", "instant",
         role="subtotal", candidates=(
             ("us-gaap", "AssetsCurrent"),
             ("ifrs-full", "CurrentAssets"),
         )),
    Line("PropertyPlantAndEquipmentNet", "Property, plant and equipment", "balance",
         "instant", candidates=(
             ("us-gaap", "PropertyPlantAndEquipmentNet"),
             ("ifrs-full", "PropertyPlantAndEquipment"),
         )),
    Line("Goodwill", "Goodwill", "balance", "instant", candidates=(
        ("us-gaap", "Goodwill"),
        ("ifrs-full", "Goodwill"),
    )),
    Line("IntangibleAssets", "Intangibles excluding goodwill", "balance", "instant",
         candidates=(
             ("us-gaap", "IntangibleAssetsNetExcludingGoodwill"),
             ("us-gaap", "FiniteLivedIntangibleAssetsNet"),
             ("ifrs-full", "IntangibleAssetsOtherThanGoodwill"),
         )),
    Line("Assets", "Total assets", "balance", "instant", role="total", candidates=(
        ("us-gaap", "Assets"),
        ("ifrs-full", "Assets"),
    )),
    Line("AccountsPayable", "Payables", "balance", "instant", candidates=(
        ("us-gaap", "AccountsPayableCurrent"),
        ("ifrs-full", "TradeAndOtherCurrentPayables"),
    )),
    Line("TotalCurrentLiabilities", "Total current liabilities", "balance", "instant",
         role="subtotal", candidates=(
             ("us-gaap", "LiabilitiesCurrent"),
             ("ifrs-full", "CurrentLiabilities"),
         )),
    # TotalDebt has its own fallback ladder (combined tag, else long-term split, else
    # the single long-term tag) and is resolved by select_total_debt, not from here.
    Line("TotalDebt", "Total debt", "balance", "instant"),
    Line("Liabilities", "Total liabilities", "balance", "instant", role="subtotal",
         candidates=(
             ("us-gaap", "Liabilities"),
             ("ifrs-full", "Liabilities"),
         )),
    Line("StockholdersEquity", "Total equity", "balance", "instant", role="total",
         candidates=(
             ("us-gaap", "StockholdersEquity"),
             ("us-gaap",
              "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
             ("ifrs-full", "Equity"),
         )),
    Line("NetDebt", "Net debt", "balance", "instant", role="memo",
         derived=("TotalDebt", "-", "CashAndEquivalents")),
)

_CASHFLOW = (
    Line("CashFlowOperating", "Cash from operations", "cashflow", "duration",
         role="total", candidates=(
             ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
             ("us-gaap",
              "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
             ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
         )),
    # Tagged as a positive outflow, which is how the filer presents it and what makes
    # free cash flow a plain subtraction. Nothing is re-signed.
    Line("CapitalExpenditure", "Capital expenditure", "cashflow", "duration",
         note="Reported as a positive outflow.", candidates=(
             ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
             ("us-gaap", "PaymentsToAcquireOtherPropertyPlantAndEquipment"),
             ("us-gaap", "PaymentsToAcquireProductiveAssets"),
             ("ifrs-full", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
             # Sanofi reports one payments line covering fixed and intangible assets
             # together and no PP&E-only figure, so this is its capital expenditure as
             # filed; it sits last, so a filer with the narrower line keeps that one.
             ("ifrs-full",
              "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwill"
              "InvestmentPropertyAndOtherNoncurrentAssets"),
         )),
    Line("FreeCashFlow", "Free cash flow", "cashflow", "duration", role="subtotal",
         derived=("CashFlowOperating", "-", "CapitalExpenditure")),
    Line("CashFlowInvesting", "Cash from investing", "cashflow", "duration",
         role="subtotal", candidates=(
             ("us-gaap", "NetCashProvidedByUsedInInvestingActivities"),
             ("us-gaap",
              "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"),
             ("ifrs-full", "CashFlowsFromUsedInInvestingActivities"),
         )),
    Line("CashFlowFinancing", "Cash from financing", "cashflow", "duration",
         role="subtotal", candidates=(
             ("us-gaap", "NetCashProvidedByUsedInFinancingActivities"),
             ("us-gaap",
              "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"),
             ("ifrs-full", "CashFlowsFromUsedInFinancingActivities"),
         )),
    Line("DepreciationAndAmortisation", "Depreciation and amortisation", "cashflow",
         "duration", role="memo", candidates=(
             ("us-gaap", "DepreciationDepletionAndAmortization"),
             ("us-gaap", "DepreciationAmortizationAndAccretionNet"),
             ("ifrs-full", "DepreciationAndAmortisationExpense"),
         )),
    # Filers that tag no combined figure tag these two instead. Kept apart, and summed
    # only where the combined line is absent: AbbVie's depreciation is 0.8bn against
    # 7.4bn of amortisation, so taking depreciation for the pair understates it tenfold.
    Line("Depreciation", "Depreciation", "cashflow", "duration", role="memo",
         candidates=(
             ("us-gaap", "Depreciation"),
             ("ifrs-full", "DepreciationPropertyPlantAndEquipment"),
         )),
    Line("AmortisationOfIntangibles", "Amortisation of intangibles", "cashflow",
         "duration", role="memo", candidates=(
             ("us-gaap", "AmortizationOfIntangibleAssets"),
             ("ifrs-full", "AmortisationIntangibleAssetsOtherThanGoodwill"),
         )),
    # Cash paid for assets rather than whole businesses: a licence, a molecule, an
    # in-process programme. Lilly buys this way more than it buys companies, so its
    # business-combination line reads 0.3bn against 3.0bn of in-process R&D bought. Kept
    # as separate lines and summed, since a filer may report one, the other, or both.
    Line("AcquiredIprd", "In-process R&D acquired", "cashflow", "duration", role="memo",
         candidates=(
             ("us-gaap", "PaymentsToAcquireInProcessResearchAndDevelopment"),
         )),
    Line("AcquiredIntangibles", "Intangible assets acquired", "cashflow", "duration",
         role="memo", candidates=(
             ("us-gaap", "PaymentsToAcquireIntangibleAssets"),
             ("ifrs-full",
              "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"),
         )),
    # Cash actually paid for businesses, which is the hard number behind the deal feed.
    Line("AcquisitionsNet", "Acquisitions, net of cash acquired", "cashflow", "duration",
         role="memo", note="Cash paid for businesses, net of cash acquired.",
         candidates=(
             ("us-gaap", "PaymentsToAcquireBusinessesNetOfCashAcquired"),
             ("us-gaap", "PaymentsToAcquireBusinessesGross"),
             # Last, so it is only read where a filer publishes no primary line. Lilly
             # files this and nothing else for its business combinations.
             ("us-gaap", "OtherPaymentsToAcquireBusinesses"),
             ("ifrs-full",
              "CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities"),
         )),
    Line("ShareBasedCompensation", "Share-based compensation", "cashflow", "duration",
         role="memo", candidates=(
             ("us-gaap", "ShareBasedCompensation"),
             ("ifrs-full", "ShareBasedPaymentsExpense"),
         )),
    Line("DividendsPaid", "Dividends paid", "cashflow", "duration", role="memo",
         note="Reported as a positive outflow.", candidates=(
             ("us-gaap", "PaymentsOfDividends"),
             ("us-gaap", "PaymentsOfOrdinaryDividends"),
             ("us-gaap", "PaymentsOfDividendsCommonStock"),
             ("ifrs-full", "DividendsPaidClassifiedAsFinancingActivities"),
         )),
    Line("ShareRepurchases", "Buybacks", "cashflow", "duration", role="memo",
         note="Reported as a positive outflow.", candidates=(
             ("us-gaap", "PaymentsForRepurchaseOfCommonStock"),
             ("ifrs-full", "PaymentsToAcquireOrRedeemEntitysShares"),
         )),
)

LINES: tuple[Line, ...] = _INCOME + _BALANCE + _CASHFLOW
LINES_BY_KEY: dict[str, Line] = {line.key: line for line in LINES}
STATEMENTS = ("income", "balance", "cashflow")
STATEMENT_LABELS = {"income": "Income statement", "balance": "Balance sheet",
                    "cashflow": "Cash flow"}

# What a common-size column divides by. Sales for the two flow statements, the balance
# sheet total for the balance sheet. Cash flow's base is not one of its own lines, and
# its columns are cumulative while the income statement's are discrete, so the base has
# to be read at each column's own period rather than borrowed from another statement's
# grid position.
COMMON_SIZE_BASE = {"income": "Revenues", "balance": "Assets", "cashflow": "Revenues"}


def lines_for(statement: str) -> tuple[Line, ...]:
    return tuple(line for line in LINES if line.statement == statement)


# --- period classification ----------------------------------------------
def classify_period(entry: dict) -> tuple[str, str] | None:
    """Map a company-facts entry to (period_end, period_type), or None to ignore it.

    Duration buckets are deliberately loose. Fiscal years run 52 or 53 weeks, so JNJ's
    2025 "year" is 364 days ending on a Sunday, and a quarter is anywhere from 89 to 92
    days. Anything that fits no bucket (a two month stub, a five year cumulative) is
    dropped rather than guessed at.
    """
    end = entry.get("end")
    if not end or entry.get("form") not in FORMS:
        return None
    start = entry.get("start")
    if not start:
        return end, INSTANT
    try:
        days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
    except ValueError:
        return None
    if 340 <= days <= 380:
        return end, FY
    if 80 <= days <= 100:
        return end, Q
    if 150 <= days <= 300:      # six or nine months, cumulative from the year start
        return end, YTD
    return None


def duration_label(entry: dict) -> str | None:
    """"3M", "6M", "9M" or "12M" for a duration entry; None for an instant.

    The months a figure covers are a fact about the filing. Which fiscal quarter that
    makes it is not, since it depends on the filer's year end, so that is worked out in
    the API layer where the whole series is in hand.
    """
    start, end = entry.get("start"), entry.get("end")
    if not start or not end:
        return None
    try:
        days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
    except ValueError:
        return None
    for months, low, high in ((3, 80, 100), (6, 150, 200), (9, 250, 300),
                              (12, 340, 380)):
        if low <= days <= high:
            return f"{months}M"
    return None
