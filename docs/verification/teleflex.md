# Verification worksheet — Teleflex golden case

Deal `teleflex-2025q2`, test date **2025-06-29**, formula version 1.

Reproduce with `python scripts/verify_teleflex.py`. That script imports nothing
from `backend/` and re-derives every figure below from the raw companyfacts
JSON using only the standard library.

> **Read the "Reporting basis" section before trusting any TTM figure here.**
> Teleflex restated 2024 and 2025 for discontinued operations, and the window
> straddles the restatement. Every figure in this worksheet is built from the
> figures **as originally reported**, which is the basis the run settled on.
> All of them are an analyst's estimates from public filings, not the
> borrower's compliance numbers.

## Agreement and covenant

| What | Value |
| --- | --- |
| Exhibit | EX-10.1 to the 8-K filed 2025-06-30 |
| Exhibit URL | <https://www.sec.gov/Archives/edgar/data/96943/000009694325000107/ex101to6-27x20258xkrecredi.htm> |
| Accession | `0000096943-25-000107` |
| Normalised text | 716,914 characters, `sha256:60e01cb1890d539072ac6db1a1acda0ae8cb75bce69db248be3d6c9cf7f5f926` |

| Covenant | Threshold | Offsets | Quote (verified against the text at those offsets) |
| --- | --- | --- | --- |
| `max_total_net_leverage` | 4.50x from 2022-09-30 | 546344–546573 | "The Borrower will not permit the Consolidated Total Net Leverage Ratio, as at the last day of any period of four consecutive fiscal quarters of the Borrower which period ends on or after September 30, 2022 to exceed 4.50 to 1.00." |
| `min_interest_coverage` | 3.50x from 2022-09-30 | 547832–548047 | "The Borrower will not permit the Consolidated Interest Coverage Ratio for any period of four consecutive fiscal quarters of the Borrower which period ends on or after September 30, 2022 to be less than 3.50 to 1.00." |
| Cap pool `clause_x` | 5% of EBITDA before the pool | 85264–85571 | "…the aggregate amount of such charges permitted to be added back pursuant to this clause (x) during any four consecutive fiscal quarter period of the Borrower shall not exceed 5% of Consolidated EBITDA for such period (calculated without giving effect to the add-back of any item pursuant to this clause (x))" |

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

Values are as the application used them, all on one reporting basis: the
figures **as originally reported**. *(derived)* means the quarter was not
reported and was computed as the longer year-to-date period minus the shorter
one within that basis; for the fourth quarter of 2024 that is the full year as
first filed minus the nine months as first filed.

| Formula item | Concept | Period | Value (USD) | Form | Accession | Filing index | Where to look |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `net_income` | NetIncomeLoss | 2024-07-01 to 2024-09-29 | 111,004,000 | 10-K | `0000096943-26-000019` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000019/0000096943-26-000019-index.htm) | Income statement |
| `net_income` | NetIncomeLoss | 2024-09-30 to 2024-12-31 | -136,656,000 | 10-K | `0000096943-26-000019` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000019/0000096943-26-000019-index.htm) | Income statement |
| `net_income` | NetIncomeLoss | 2025-01-01 to 2025-03-30 | 95,002,000 | 10-Q | `0000096943-26-000095` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000095/0000096943-26-000095-index.htm) | Income statement |
| `net_income` | NetIncomeLoss | 2025-03-31 to 2025-06-29 | 122,580,000 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Income statement |
| `income_tax_expense` | IncomeTaxExpenseBenefit | 2024-07-01 to 2024-09-29 | 19,633,000 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Income statement (taxes on income from continuing operations) |
| `income_tax_expense` | IncomeTaxExpenseBenefit | 2024-09-30 to 2024-12-31 *(derived)* | 9,902,000 | 10-K | `0000096943-25-000031` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000031/0000096943-25-000031-index.htm) | Income statement (taxes on income from continuing operations) |
| `income_tax_expense` | IncomeTaxExpenseBenefit | 2025-01-01 to 2025-03-30 | 13,839,000 | 10-Q | `0000096943-25-000077` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000077/0000096943-25-000077-index.htm) | Income statement (taxes on income from continuing operations) |
| `income_tax_expense` | IncomeTaxExpenseBenefit | 2025-03-31 to 2025-06-29 | 12,662,000 | 10-Q | `0000096943-25-000115` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000115/0000096943-25-000115-index.htm) | Income statement (taxes on income from continuing operations) |
| `interest_expense` | InterestExpenseNonoperating | 2024-07-01 to 2024-09-29 | 21,058,000 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Income statement (interest expense) |
| `interest_expense` | InterestExpenseNonoperating | 2024-09-30 to 2024-12-31 *(derived)* | 18,635,000 | 10-K | `0000096943-25-000031` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000031/0000096943-25-000031-index.htm) | Income statement (interest expense) |
| `interest_expense` | InterestExpenseNonoperating | 2025-01-01 to 2025-03-30 | 18,544,000 | 10-Q | `0000096943-25-000077` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000077/0000096943-25-000077-index.htm) | Income statement (interest expense) |
| `interest_expense` | InterestExpenseNonoperating | 2025-03-31 to 2025-06-29 | 21,708,000 | 10-Q | `0000096943-25-000115` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000115/0000096943-25-000115-index.htm) | Income statement (interest expense) |
| `depreciation_amortization` | DepreciationAndAmortization | 2024-07-01 to 2024-09-29 | 68,636,000 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Cash flow statement (operating add-backs) |
| `depreciation_amortization` | DepreciationAndAmortization | 2024-09-30 to 2024-12-31 *(derived)* | 71,792,000 | 10-K | `0000096943-25-000031` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000031/0000096943-25-000031-index.htm) | Cash flow statement (operating add-backs) |
| `depreciation_amortization` | DepreciationAndAmortization | 2025-01-01 to 2025-03-30 | 67,331,000 | 10-Q | `0000096943-25-000077` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000077/0000096943-25-000077-index.htm) | Cash flow statement (operating add-backs) |
| `depreciation_amortization` | DepreciationAndAmortization | 2025-03-31 to 2025-06-29 | 65,712,000 | 10-Q | `0000096943-25-000115` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000115/0000096943-25-000115-index.htm) | Cash flow statement (operating add-backs) |
| `stock_based_compensation` | ShareBasedCompensation | 2024-07-01 to 2024-09-29 *(derived)* | 7,988,000 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Cash flow statement (operating add-backs) |
| `stock_based_compensation` | ShareBasedCompensation | 2024-09-30 to 2024-12-31 *(derived)* | 7,621,000 | 10-K | `0000096943-25-000031` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000031/0000096943-25-000031-index.htm) | Cash flow statement (operating add-backs) |
| `stock_based_compensation` | ShareBasedCompensation | 2025-01-01 to 2025-03-30 | 7,826,000 | 10-Q | `0000096943-25-000077` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000077/0000096943-25-000077-index.htm) | Cash flow statement (operating add-backs) |
| `stock_based_compensation` | ShareBasedCompensation | 2025-03-31 to 2025-06-29 *(derived)* | 6,941,000 | 10-Q | `0000096943-25-000115` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000115/0000096943-25-000115-index.htm) | Cash flow statement (operating add-backs) |
| `restructuring_charges` | RestructuringCharges | 2024-07-01 to 2024-09-29 | 285,000 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Income statement / restructuring note |
| `restructuring_charges` | RestructuringCharges | 2024-09-30 to 2024-12-31 *(derived)* | 5,468,000 | 10-K | `0000096943-25-000031` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000031/0000096943-25-000031-index.htm) | Income statement / restructuring note |
| `restructuring_charges` | RestructuringCharges | 2025-01-01 to 2025-03-30 | 1,528,000 | 10-Q | `0000096943-25-000077` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000077/0000096943-25-000077-index.htm) | Income statement / restructuring note |
| `restructuring_charges` | RestructuringCharges | 2025-03-31 to 2025-06-29 | 1,165,000 | 10-Q | `0000096943-25-000115` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000115/0000096943-25-000115-index.htm) | Income statement / restructuring note |
| `impairment_charges` | analyst value | TTM to 2025-06-29 | 253,841,000 | — | — | — | hand-summed; see the impairment table |
| `transaction_costs` | analyst value | TTM to 2025-06-29 | 0 | — | — | — | hand-summed; see the impairment table |
| `other_non_cash_gains` | analyst value | TTM to 2025-06-29 | 0 | — | — | — | hand-summed; see the impairment table |
| `long_term_debt` | LongTermDebtNoncurrent | at 2025-06-29 | 1,801,645,000 | 10-Q | `0000096943-25-000115` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000115/0000096943-25-000115-index.htm) | Balance sheet (long-term borrowings) |
| `current_portion_long_term_debt` | LongTermDebtCurrent | at 2025-06-29 | 100,000,000 | 10-Q | `0000096943-25-000115` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000115/0000096943-25-000115-index.htm) | Balance sheet (current borrowings) |
| `cash_and_equivalents` | CashAndCashEquivalentsAtCarryingValue | at 2025-06-29 | 253,697,000 | 10-Q | `0000096943-25-000115` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000115/0000096943-25-000115-index.htm) | Balance sheet (cash and cash equivalents) |

The four quarters of `net_income` are quoted from the most recent filing that
carries them, which for 2024 is the 2026 10-K. That is not a basis mix: those
quarters were never restated, so the single presentation they have belongs to
both bases, and the subtraction a derived quarter needs never crosses a
boundary. See "Reporting basis" below.

## The $240m impairment add-back

The golden set records `impairment_charges` as a hand-summed analyst value of
**253,841,000** because neither concept has a fact in all four quarters —
Teleflex tags them only in quarters with a non-zero amount, so no TTM window
can be built mechanically.

| Concept | Quarter | Value | Form | Accession | Filing index | Where to look |
| --- | --- | ---: | --- | --- | --- | --- |
| GoodwillImpairmentLoss | 2024-07-01 to 2024-09-29 | 0 | 10-Q | `0000096943-25-000138` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000138/0000096943-25-000138-index.htm) | Income statement / goodwill note |
| GoodwillImpairmentLoss | 2024-09-30 to 2024-12-31 *(derived)* | 240,000,000 | 10-K | `0000096943-25-000031` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000031/0000096943-25-000031-index.htm) | Income statement / goodwill note |
| GoodwillImpairmentLoss | 2025 quarters | not reported | — | — | — | nil |
| ImpairmentOfIntangibleAssetsExcludingGoodwill | 2024-09-30 to 2024-12-31 *(derived)* | 5,724,000 | 10-K | `0000096943-26-000019` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000019/0000096943-26-000019-index.htm) | Intangible assets note |
| ImpairmentOfIntangibleAssetsExcludingGoodwill | 2025-01-01 to 2025-03-30 | 0 | 10-Q | `0000096943-25-000077` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694325000077/0000096943-25-000077-index.htm) | Intangible assets note |
| ImpairmentOfIntangibleAssetsExcludingGoodwill | 2025-03-31 to 2025-06-29 *(derived)* | 8,117,000 | 10-Q | `0000096943-26-000095` | [index](https://www.sec.gov/Archives/edgar/data/96943/000009694326000095/0000096943-26-000095-index.htm) | Intangible assets note |
| | **Total** | **253,841,000** | | | | |

**Formula component it maps to:** clause **(b)(v)**, "any non-cash charges,
expenses or losses", offsets 84343–84383, sign `+`, category `non_cash`. The
reviewer note records that the clause is a catch-all mapped to
`impairment_charges` because impairment is the only non-cash charge Teleflex
quantifies in the period besides stock compensation, which clause (b)(vii)
adds back separately.

The independent script recomputes this total as **253,841,000**. It matches.

### This value is on one basis - an earlier version of this page said otherwise

An earlier version of this worksheet claimed the Q4 2024 intangible figure was
"derived across a restatement boundary", taking 7,834,000 from the 2026 10-K.
**That was wrong**, and the claim propagated into `docs/decisions.md` and the
README before it was checked.

The facts: `ImpairmentOfIntangibleAssetsExcludingGoodwill` for FY2024 was first
filed **2025-02-28** in `0000096943-25-000031` at 7,834,000, and the 2026 10-K
repeated the same 7,834,000 unchanged. That series has **no restatement
boundary**, so both figures belong to both cohorts and the subtraction
7,834,000 - 2,110,000 happens inside one presentation. The same is true of the
goodwill series (9M of 0 in `0000096943-25-000138`, FY of 240,000,000 in
`0000096943-25-000031`) and of the six months to 2025-06-29 (8,117,000, first
filed 2025-07-31 in `0000096943-25-000115`).

Deriving a quarter across two *filings* is normal - a fiscal Q4 can never be
derived from one - and is not the same thing as deriving it across two *bases*.
Confusing the two is what produced the wrong claim.

The mapping record is therefore tagged `analyst_value_basis:
as_originally_reported`, and the guard added alongside it refuses any analyst
value whose basis differs from the one the run settled on
(`inconsistent_basis`; see `backend/edgar/ttm.py`, `_analyst_value`, and
`tests/test_basis.py`). A multi-concept mapping that sums reported concepts
directly, instead of relying on a hand-summed total, is still the better answer
and is still future work.

## Reporting basis - the material finding, and what was done about it

Teleflex restated 2024 and 2025 when it separated its business.

**What this used to do, and why it was wrong.** The application took, for each
period independently, the most recently filed value. Where a period had only
ever been reported once that was the original figure; where it had been
restated that was the continuing-operations figure. One TTM window therefore
mixed the two, and a quarter derived across the seam was a subtraction of two
numbers that were never measured the same way:

| Item | FY2024 as first filed (2025-02-28) | FY2024 as restated (2026-02-27) | 9M 2024 (only ever original) | Derived Q4, mixed basis |
| --- | ---: | ---: | ---: | ---: |
| DepreciationAndAmortization | 274,601,000 | 161,534,000 | 202,809,000 | **-41,275,000** |
| IncomeTaxExpenseBenefit | 5,316,000 | -30,901,000 | -4,586,000 | **-26,315,000** |
| InterestExpenseNonoperating | 83,544,000 | 83,513,000 | 64,909,000 | 18,604,000 |

A quarter cannot have negative depreciation and amortisation. Nothing
downstream could detect it, because the TTM total it summed into looked
entirely ordinary.

**What it does now.** Each year-to-date series is cut at the first filing that
reported one of its periods with a different value, and a window is built from
one side of the cut only. The whole run commits to one basis: the restated
figures when they can produce a complete window, the figures as originally
reported when they cannot. A derived quarter that comes out negative for an
item that cannot be negative is refused as `implausible_value`. The basis is
recorded on the inputs, shown on the deal screen, and part of the output hash.

### Why this run is on the figures as originally reported

The restated cohort cannot produce the window. For each of the five expense
items, these are the quarters each basis can supply:

| Quarter | as restated | as originally reported |
| --- | --- | --- |
| 2024-07-01..2024-09-29 | available | available |
| 2024-09-30..2024-12-31 | **cannot be formed** | derived: 12M to 2024-12-31 minus 9M to 2024-09-29 |
| 2025-01-01..2025-03-30 | **cannot be formed** | available |
| 2025-03-31..2025-06-29 | available | available |

Two separate reasons, both of which refuse rather than mix:

1. **The fourth quarter of 2024 has nothing to be derived from.** A fiscal
   fourth quarter is never stated directly; it is the full year minus the nine
   months. The restating 10-K (`0000096943-26-000019`, filed 2026-02-27)
   reissued the 2024 full year at 161,534,000 of depreciation but never
   reissued the nine months to 2024-09-29. On the restated cohort the 2024
   year-to-date series holds exactly one fact, the full year, so there is no
   shorter cumulative period to subtract.
2. **The first quarter of 2025 falls outside the restated cohort.** That series
   was restated twice: the three months to 2025-03-30 changed in the 10-Q filed
   2026-05-07 (67,331,000 to 38,620,000), and the six months to 2025-06-29
   changed again in the 10-Q filed 2026-08-06 (133,043,000 to 75,507,000). The
   restated cohort is cut at the *latest* boundary so that one cohort sits
   inside one presentation, which leaves only the six-month fact. This is
   deliberately conservative: it makes the restated basis unusable here rather
   than straddling two presentations of 2025.

`net_income` is the one item that resolves on both bases, and it is identical
on each. Restating for discontinued operations moves amounts between lines
without changing the bottom line, so the four quarters of `NetIncomeLoss` are
unchanged across every filing that reported them, bar a 1,000 presentational
difference in the 2026 10-K for the June 2025 quarter, where the pre-cut
cohort keeps the 122,580,000 the original 10-Q published.

### What the basis is worth, in figures

| Item | Mixed basis (old, wrong) | As originally reported (used) | Difference |
| --- | ---: | ---: | ---: |
| `net_income` | 191,930,000 | 191,930,000 | 0 |
| `income_tax_expense` | 2,224,000 | 56,036,000 | 53,812,000 |
| `interest_expense` | 79,902,000 | 79,945,000 | 43,000 |
| `depreciation_amortization` | 102,869,000 | 273,471,000 | 170,602,000 |
| `stock_based_compensation` | 22,508,000 | 30,376,000 | 7,868,000 |
| `restructuring_charges` | 3,900,000 | 8,446,000 | 4,546,000 |
| **S3 covenant EBITDA** | **376,925,000** | **601,382,000** | **224,457,000** |

| Figure | Mixed basis (old) | As originally reported (now) |
| --- | ---: | ---: |
| S0 covenant EBITDA | 657,174,000 | 894,045,000 |
| S0 leverage | 2.51x | 1.84x |
| S0 cushion | 44.3% | 59.0% |
| S3 leverage | 4.37x | 2.74x |
| S3 cushion | 2.8% | 39.1% |
| S3 verdict | TIGHT | PASS |
| Adjustment dependence | 42.6% | 32.7% |

The previous headline, that the borrower sat 2.8% from a breach on plain
EBITDA, did not survive the basis question: it was an artefact of a quarter
with negative depreciation. The finding that does survive is the sensitivity
itself. A third of covenant EBITDA is discretionary, and stripping it moves
leverage from 1.84x to 2.74x.

### Every derived quarter, checked for sign

| Item | Quarters derived | Range across the four quarters | Plausible |
| --- | --- | ---: | --- |
| `depreciation_amortization` | 2024-09-30..2024-12-31 | 65,712,000 - 71,792,000 | yes |
| `interest_expense` | 2024-09-30..2024-12-31 | 18,544,000 - 21,708,000 | yes |
| `income_tax_expense` | 2024-09-30..2024-12-31 | 9,902,000 - 19,633,000 | yes, all four positive |
| `stock_based_compensation` | three of the four | 6,941,000 - 7,988,000 | yes |
| `restructuring_charges` | 2024-09-30..2024-12-31 | 285,000 - 5,468,000 | yes, all four positive |

No derived quarter is negative. `tests/test_golden.py` asserts this against
the committed filing data for the items that cannot be negative, and
`tests/test_basis.py` pins the synthetic shape of the original defect.

### What is still open

Whether the credit agreement's Consolidated EBITDA should be measured on the
figures as originally reported or on the continuing-operations figures is a
question about the contract, not about the data. It is **not resolved**; see
`docs/decisions.md`. The run names the basis it used so a reader can disagree
with it.

## Results

Covenant EBITDA, leverage against the 4.50x cap, and coverage against the 3.50x
floor. Net debt at the test date is 1,647,948,000: 1,801,645,000 of long-term
debt plus 100,000,000 current, less 253,697,000 of cash netted without a cap.
All figures on the figures as originally reported.

| Scenario | Covenant EBITDA | Leverage | Cushion | Debt capacity | Coverage | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| S0 Contractual | 894,045,000 | 1.84x | 59.04% | 2,375,254,500 | 11.18x | PASS |
| S1 No pro forma | 894,045,000 | 1.84x | 59.04% | 2,375,254,500 | 11.18x | PASS |
| S2 No one-time | 885,599,000 | 1.86x | 58.65% | 2,337,247,500 | 11.08x | PASS |
| S3 Standard adjustments only | 601,382,000 | 2.74x | 39.11% | 1,058,271,000 | 7.52x | PASS |

Adjustment dependence, `(S0 - S3) / S0`, is **32.73%**. S0 and S1 are identical
because the agreement permits no pro forma add-back.

The clause (b)(x) restructuring cap does not bind: 8,446,000 requested against
a cap of 44,279,950, which is 5% of the 885,599,000 of EBITDA calculated
without giving effect to that clause.

Three implementations agree on every figure in this table: the evaluator,
`scripts/hand_calc.py` (longhand, no evaluator import) and
`scripts/verify_teleflex.py` (standard library only, no `backend` import,
re-derived from the raw companyfacts JSON).

## Also not machine-checkable

| Item | Golden value | Status |
| --- | ---: | --- |
| `transaction_costs` | 0 | Asserted nil from reading the filings. Teleflex tags no acquisition-cost concept, so this cannot be confirmed or refuted from XBRL. |
| `other_non_cash_gains` | 0 | Asserted nil. The rationale itself flags this as the one non-conservative assumption. |

Both need a human to read the four reports covering the window.
