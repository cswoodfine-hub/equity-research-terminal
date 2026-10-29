# Brief: read US loss-of-exclusivity dates that filers state in their FY2025 annual reports

You are reading annual reports (10-K or 20-F, fiscal 2025, filed 2026) of large pharma
companies, already converted to one-line plain text. For each product in your input file,
find whether the filer itself states **when that product loses US market exclusivity**,
and quote it word for word.

## Input
`<group>_in.json`: `filings` (ticker -> form, accession, text_file path) and `products`
(ticker, brand, modality, and the date and basis an internal model currently holds for
the US: `model_us_date`, `model_basis`). The model's date is context only. Do not let it
steer what you read; report what the filing says.

Read the text files with grep/Python (they are large, 0.3 to 1.5 MB, one line). Look in
particular for:
- the patent table in Item 1 / "Intellectual Property" / "Patents" (10-K) or the patent
  section of a 20-F: rows like `Keytruda 2028 (10) 2031 2032-2033 2028`, where the
  column order is given by the table header just before the rows (often U.S., EU, Japan,
  China) and footnote markers like (10) refer to footnotes after the table;
- footnotes to that table;
- MD&A or risk-factor sentences such as "expects to lose U.S. market exclusivity for X
  in 2028", "generic entry is not expected until July 2030" (settlements), "biosimilar
  competition could begin in December 2028", "X lost exclusivity in 2025".

## Rules for what counts
- The date is the **molecule's**: compound, basic product, composition of matter or new
  molecular entity patent, or regulatory/data exclusivity where that runs later. Never a
  formulation, device or method-of-use patent.
- A settled or expected generic or biosimilar entry date the filer states beats the
  patent year. Record it.
- Extensions: take a year that includes a **granted** extension; a year "with pending
  PTE" or "absent PTE" must be flagged in `notes` (do not resolve it).
- For a biologic, a compound patent that ends before 12 years from US approval is not a
  date the market opens: still report what is printed, and say so in `notes`.
- "Expired" or "lost exclusivity" with no year: report `stated_us` as "expired".
- If the product's name in the filing differs (e.g. "Simponi/Simponi Aria", "NovoLog"),
  use the filing's name in the quote and say so in notes.
- If the filing states nothing about this product's US exclusivity, return
  `stated_us: null`. Do not infer a year from anything else.

## Output
Write `<group>_out.json`: a list with one object per input product, same order:
```
{"ticker": "...", "brand": "... (as in input)",
 "stated_us": "2028" | "2028-12" | "2030-07-01" | "expired" | null,
 "kind": "compound patent" | "data exclusivity" | "settled generic entry" | ... | null,
 "quote": "exact text copied from the text file, at most 400 characters; for a table row
           include the header columns and the row joined by ' ... '",
 "location": "patent table" | "patent table footnote (n)" | "MD&A" | "risk factors" | ...,
 "notes": "pending PTE, later patents expected to be litigated, column order, etc."}
```
Every `quote` must be a verbatim substring of the text file (or, for a table, verbatim
substrings joined by " ... "). It will be checked mechanically, and a quote that is not
found is discarded. Do not paraphrase inside `quote`.

Finish by replying with: counts of products with a stated date, with "expired", and with
null; and any product where you were unsure, with why. Do not edit any file except your
`_out.json`.
