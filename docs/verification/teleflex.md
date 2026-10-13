# Verification worksheet â€” Teleflex golden case

Deal `teleflex-2025q2`, test date **2025-06-29**, formula version 1.

Reproduce with `python scripts/verify_teleflex.py`. That script imports nothing
from `backend/` and re-derives every figure below from the raw companyfacts
JSON using only the standard library.

> **Read the "Reporting basis" section before trusting any TTM figure here.**
> Teleflex restated 2024 and 2025 for discontinued operations, and the window
> straddles the restatement.

## Agreement and covenant

| What | Value |
| --- | --- |
| Exhibit | EX-10.1 to the 8-K filed 2025-06-30 |
| Exhibit URL | <https://www.sec.gov/Archives/edgar/data/96943/000009694325000107/ex101to6-27x20258xkrecredi.htm> |
| Accession | `0000096943-25-000107` |
| Normalised text | 716,914 characters, `sha256:60e01cb1890d539072ac6db1a1acda0ae8cb75bce69db248be3d6c9cf7f5f926` |

| Covenant | Threshold | Offsets | Quote (verified against the text at those offsets) |
| --- | --- | --- | --- |
| `max_total_net_leverage` | 4.50x from 2022-09-30 | 546344â€“546573 | "The Borrower will not permit the Consolidated Total Net Leverage Ratio, as at the last day of any period of four consecutive fiscal quarters of the Borrower which period ends on or after September 30, 2022 to exceed 4.50 to 1.00." |
| `min_interest_coverage` | 3.50x from 2022-09-30 | 547832â€“548047 | "The Borrower will not permit the Consolidated Interest Coverage Ratio for any period of four consecutive fiscal quarters of the Borrower which period ends on or after September 30, 2022 to be less than 3.50 to 1.00." |
| Cap pool `clause_x` | 5% of EBITDA before the pool | 85264â€“85571 | "â€¦the aggregate amount of such charges permitted to be added back pursuant to this clause (x) during any four consecutive fiscal quarter period of the Borrower shall not exceed 5% of Consolidated EBITDA for such period (calculated without giving effect to the add-back of any item pursuant to this clause (x))" |

Both covenant spans and the cap pool span re-verify against `agreement.txt`.

## The four TTM quarters

| # | Start | End | Days |
| --- | --- | --- | --- |
| 1 | 2024-07-01 | 2024-09-29 | 91 |
| 2 | 2024-09-30 | 2024-12-31 | 93 |
| 3 | 2025-01-01 | 2025-03-30 | 89 |
| 4 | 2025-03-31 | 2025-06-29 | 91 |

Span 364 days, contiguous, ending exactly on the test date.

## Every input, fact by fact

Values are as the application used them. *(derived)* means the quarter was not
reported and was computed as the longer year-to-date period minus the shorter
one; for quarter 2 that is FY2024 minus the nine months to 2024-09-29.

| Formula item | Concept | Period | Value (USD) | Form | Accession | Filing index | Where to look |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `net_income` | NetIncomeLoss | 2024-07-01 to 2024-09-29 | 111,004,000 | 10-K | `0000096943-26-000019` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000019/0000096943-26-000019-index.htm) | Income statement |
| `net_income` | NetIncomeLoss | 2024-09-30 to 2024-12-31 | -136,656,000 | 10-K | `0000096943-26-000019` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000019/0000096943-26-000019-index.htm) | Income statement |
| `net_income` | NetIncomeLoss | 2025-01-01 to 2025-03-30 | 95,002,000 | 10-Q | `0000096943-26-000095` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000095/0000096943-26-000095-index.htm) | Income statement |
| `net_income` | NetIncomeLoss | 2025-03-31 to 2025-06-29 | 122,580,000 | 10-Q | `0000096943-26-000095` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000095/0000096943-26-000095-index.htm) | Income statement |
| `income_tax_expense` | IncomeTaxExpenseBenefit | 2024-07-01 to 2024-09-29 | 19,633,000 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Income statement (taxes on income from continuing operations) |
| `income_tax_expense` | IncomeTaxExpenseBenefit | 2024-09-30 to 2024-12-31 *(derived)* | -26,315,000 | 10-K | `0000096943-26-000019` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000019/0000096943-26-000019-index.htm) | Income statement (taxes on income from continuing operations) |
| `income_tax_expense` | IncomeTaxExpenseBenefit | 2025-01-01 to 2025-03-30 | 6,417,000 | 10-Q | `0000096943-26-000050` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000050/0000096943-26-000050-index.htm) | Income statement (taxes on income from continuing operations) |
| `income_tax_expense` | IncomeTaxExpenseBenefit | 2025-03-31 to 2025-06-29 | 2,489,000 | 10-Q | `0000096943-26-000095` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000095/0000096943-26-000095-index.htm) | Income statement (taxes on income from continuing operations) |
| `interest_expense` | InterestExpenseNonoperating | 2024-07-01 to 2024-09-29 | 21,058,000 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Income statement (interest expense) |
| `interest_expense` | InterestExpenseNonoperating | 2024-09-30 to 2024-12-31 *(derived)* | 18,604,000 | 10-K | `0000096943-26-000019` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000019/0000096943-26-000019-index.htm) | Income statement (interest expense) |
| `interest_expense` | InterestExpenseNonoperating | 2025-01-01 to 2025-03-30 | 18,537,000 | 10-Q | `0000096943-26-000050` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000050/0000096943-26-000050-index.htm) | Income statement (interest expense) |
| `interest_expense` | InterestExpenseNonoperating | 2025-03-31 to 2025-06-29 | 21,703,000 | 10-Q | `0000096943-26-000095` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000095/0000096943-26-000095-index.htm) | Income statement (interest expense) |
| `depreciation_amortization` | DepreciationAndAmortization | 2024-07-01 to 2024-09-29 | 68,636,000 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Cash flow statement (operating add-backs) |
| `depreciation_amortization` | DepreciationAndAmortization | 2024-09-30 to 2024-12-31 *(derived)* | -41,275,000 | 10-K | `0000096943-26-000019` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000019/0000096943-26-000019-index.htm) | Cash flow statement (operating add-backs) |
| `depreciation_amortization` | DepreciationAndAmortization | 2025-01-01 to 2025-03-30 | 38,620,000 | 10-Q | `0000096943-26-000050` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000050/0000096943-26-000050-index.htm) | Cash flow statement (operating add-backs) |
| `depreciation_amortization` | DepreciationAndAmortization | 2025-03-31 to 2025-06-29 | 36,888,000 | 10-Q | `0000096943-26-000095` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000095/0000096943-26-000095-index.htm) | Cash flow statement (operating add-backs) |
| `stock_based_compensation` | ShareBasedCompensation | 2024-07-01 to 2024-09-29 *(derived)* | 7,988,000 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Cash flow statement (operating add-backs) |
| `stock_based_compensation` | ShareBasedCompensation | 2024-09-30 to 2024-12-31 *(derived)* | 2,233,000 | 10-K | `0000096943-26-000019` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000019/0000096943-26-000019-index.htm) | Cash flow statement (operating add-backs) |
| `stock_based_compensation` | ShareBasedCompensation | 2025-01-01 to 2025-03-30 | 6,630,000 | 10-Q | `0000096943-26-000050` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000050/0000096943-26-000050-index.htm) | Cash flow statement (operating add-backs) |
| `stock_based_compensation` | ShareBasedCompensation | 2025-03-31 to 2025-06-29 *(derived)* | 5,657,000 | 10-Q | `0000096943-26-000095` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000095/0000096943-26-000095-index.htm) | Cash flow statement (operating add-backs) |
| `restructuring_charges` | RestructuringCharges | 2024-07-01 to 2024-09-29 | 285,000 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Income statement / restructuring note |
| `restructuring_charges` | RestructuringCharges | 2024-09-30 to 2024-12-31 *(derived)* | 940,000 | 10-K | `0000096943-26-000019` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000019/0000096943-26-000019-index.htm) | Income statement / restructuring note |
| `restructuring_charges` | RestructuringCharges | 2025-01-01 to 2025-03-30 | 1,422,000 | 10-Q | `0000096943-26-000050` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000050/0000096943-26-000050-index.htm) | Income statement / restructuring note |
| `restructuring_charges` | RestructuringCharges | 2025-03-31 to 2025-06-29 | 1,253,000 | 10-Q | `0000096943-26-000095` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000095/0000096943-26-000095-index.htm) | Income statement / restructuring note |
| `impairment_charges` | analyst value | TTM to 2025-06-29 | 253,841,000 | — | — | — | hand-summed; see the impairment table |
| `transaction_costs` | analyst value | TTM to 2025-06-29 | 0 | — | — | — | hand-summed; see the impairment table |
| `other_non_cash_gains` | analyst value | TTM to 2025-06-29 | 0 | — | — | — | hand-summed; see the impairment table |
| `long_term_debt` | LongTermDebtNoncurrent | at 2025-06-29 | 1,801,645,000 | 10-Q | `0000096943-25-000115` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000115/0000096943-25-000115-index.htm) | Balance sheet (long-term borrowings) |
| `current_portion_long_term_debt` | LongTermDebtCurrent | at 2025-06-29 | 100,000,000 | 10-Q | `0000096943-25-000115` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000115/0000096943-25-000115-index.htm) | Balance sheet (current borrowings) |
| `cash_and_equivalents` | CashAndCashEquivalentsAtCarryingValue | at 2025-06-29 | 253,697,000 | 10-Q | `0000096943-25-000115` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000115/0000096943-25-000115-index.htm) | Balance sheet (cash and cash equivalents) |

## The $240m impairment add-back

The golden set records `impairment_charges` as a hand-summed analyst value of
**253,841,000** because neither concept has a fact in all four quarters â€”
Teleflex tags them only in quarters with a non-zero amount, so no TTM window
can be built mechanically.

| Concept | Quarter | Value | Form | Accession | Filing index | Where to look |
| --- | --- | ---: | --- | --- | --- | --- |
| GoodwillImpairmentLoss | 2024-07-01 to 2024-09-29 | 0 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Income statement / goodwill note |
| GoodwillImpairmentLoss | 2024-09-30 to 2024-12-31 *(derived)* | 240,000,000 | 10-K | `0000096943-25-000031` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000031/0000096943-25-000031-index.htm) | Income statement / goodwill note |
| GoodwillImpairmentLoss | 2025 quarters | not reported | â€” | â€” | â€” | nil |
| ImpairmentOfIntangibleAssetsExcludingGoodwill | 2024-09-30 to 2024-12-31 *(derived)* | 5,724,000 | 10-K | `0000096943-26-000019` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000019/0000096943-26-000019-index.htm) | Intangible assets note |
| ImpairmentOfIntangibleAssetsExcludingGoodwill | 2025-01-01 to 2025-03-30 | 0 | 10-Q | `0000096943-25-000077` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000077/0000096943-25-000077-index.htm) | Intangible assets note |
| ImpairmentOfIntangibleAssetsExcludingGoodwill | 2025-03-31 to 2025-06-29 *(derived)* | 8,117,000 | 10-Q | `0000096943-26-000095` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000095/0000096943-26-000095-index.htm) | Intangible assets note |
| | **Total** | **253,841,000** | | | | |

**Formula component it maps to:** clause **(b)(v)**, "any non-cash charges,
expenses or losses", offsets 84343â€“84383, sign `+`, category `non_cash`. The
reviewer note records that the clause is a catch-all mapped to
`impairment_charges` because impairment is the only non-cash charge Teleflex
quantifies in the period besides stock compensation, which clause (b)(vii)
adds back separately.

The independent script recomputes this total as **253,841,000**. It matches.

**But** the Q4 2024 intangible figure is itself derived across a restatement
boundary: 7,834,000 (FY2024 as restated in the 2026 10-K) minus 2,110,000 (nine
months as published in 2025). See below.

## Reporting basis â€” the material finding

Teleflex restated 2024 and 2025 when it separated its business. The
application takes, for each period independently, the **most recently filed**
value. Where a period has only ever been reported once, that is the original
figure; where it was restated, that is the continuing-operations figure. The
TTM window therefore mixes the two.

The visible symptom is quarter 2:

| Item | FY2024 as first filed (2025-02-28) | FY2024 as restated (2026-02-27) | 9M 2024 (only ever original) | Derived Q4 used by the app |
| --- | ---: | ---: | ---: | ---: |
| DepreciationAndAmortization | 274,601,000 | 161,534,000 | 202,809,000 | **âˆ’41,275,000** |
| IncomeTaxExpenseBenefit | 5,316,000 | âˆ’30,901,000 | âˆ’4,586,000 | **âˆ’26,315,000** |
| InterestExpenseNonoperating | 83,544,000 | 83,513,000 | 64,909,000 | 18,604,000 |

**A quarter cannot have negative depreciation and amortisation.** The figure is
restated-FY minus original-9M, a subtraction of two numbers measured on
different bases that was never reported by anybody.

The same window built from each period's **first** published figure, so that
every quarter is on one basis:

| Item | Latest-filed basis (what the app uses) | Original basis | Difference |
| --- | ---: | ---: | ---: |
| `net_income` | 191,930,000 | 191,930,000 | 0 |
| `income_tax_expense` | 2,224,000 | 56,036,000 | 53,812,000 |
| `interest_expense` | 79,902,000 | 79,945,000 | 43,000 |
| `depreciation_amortization` | 102,869,000 | 273,471,000 | 170,602,000 |
| `stock_based_compensation` | 22,508,000 | 30,376,000 | 7,868,000 |
| `restructuring_charges` | 3,900,000 | 8,446,000 | 4,546,000 |
| **S3 covenant EBITDA** | **376,925,000** | **601,382,000** | **224,457,000** |

Neither column is right. The original-basis column is internally consistent but
the Q1 and Q2 2025 figures in it were superseded; the latest-filed column uses
current figures but cannot cover quarters the company never restated, and mixes
total-company net income with continuing-operations expenses.

Consequences if the original basis is the correct one:

| Figure | As the app reports it | On the original basis |
| --- | ---: | ---: |
| S3 leverage | 4.37x | 2.74x |
| S3 cushion | 2.8% | 39.1% |
| S3 verdict | TIGHT | PASS |

The headline claim that the borrower sits 2.8% from a breach on plain EBITDA
does not survive the basis question.

## Also not machine-checkable

| Item | Golden value | Status |
| --- | ---: | --- |
| `transaction_costs` | 0 | Asserted nil from reading the filings. Teleflex tags no acquisition-cost concept, so this cannot be confirmed or refuted from XBRL. |
| `other_non_cash_gains` | 0 | Asserted nil. The rationale itself flags this as the one non-conservative assumption. |

Both need a human to read the four reports covering the window.
