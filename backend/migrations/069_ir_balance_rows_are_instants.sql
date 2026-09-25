-- Balance sheet rows written from a company's own workbook were stored as fiscal years.
--
-- financials_ir wrote every row with period_type 'FY', a balance sheet line included. Every
-- reader of a balance sheet asks for an instant, the way EDGAR's rows are stored, so Roche's
-- debt, cash and equity were on file and seen by nothing: net debt read as missing, the
-- statements view showed an empty balance sheet and the sum of the parts stopped at the
-- enterprise value with no equity figure. The fetcher now writes instants; these are the
-- rows it wrote before, which a refresh would otherwise leave beside the corrected ones.
DELETE FROM financials
 WHERE source = 'financials_ir'
   AND period_type = 'FY'
   AND metric IN ('Assets', 'Liabilities', 'StockholdersEquity', 'LongTermDebt',
                  'ShortTermDebt', 'TotalDebt', 'Inventory', 'AccountsReceivable',
                  'AccountsPayable', 'CashAndEquivalents', 'ShortTermInvestments',
                  'Goodwill', 'IntangibleAssets', 'PropertyPlantAndEquipmentNet',
                  'TotalCurrentAssets', 'TotalCurrentLiabilities');
