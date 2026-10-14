# Decisions and known limitations

Every decision below changed the output, not just the code. Where the PRD said
one thing and the data said another, the conflict is written down rather than
resolved silently.

## Where the build departs from the PRD

### `temperature: 0` is not available on current models

The PRD specifies the LLM call at temperature 0. Current Claude models reject
the sampling parameters outright — `temperature` returns a 400 on Opus 5 and
every model in its family. The determinism Headroom needs is not bought from
the sampler anyway, so the call instead uses:

* a closed JSON schema with `strict: true`, so the arguments validate exactly;
* span verification against the agreement text, so a citation that does not
  exist is rejected;
* one retry carrying the exact validation errors;
* human approval of every component before anything computes.

A drafted formula is a proposal either way, and nothing downstream of approval
touches the model. `drafted_with` records the model id, prompt version and
attempt count on every version so a formula approved last quarter still says
what produced it.

### The fiscal year in `companyfacts` is the filing's, not the period's

The PRD says a quarter may be derived from two cumulative periods only when
they share "concept, unit, fiscal year and start date". Taking `fy` from
`companyfacts` literally breaks real filers: the field carries the fiscal year
of the *report a fact appeared in*, not of the period it covers. Teleflex's
nine-month 2025 fact carries `fy: 2025` while its six-month 2025 fact carries
`fy: 2026`, because the latter was restated in a later report. Keying on `fy`
splits one year-to-date series in two and silently loses the quarter at the
split — which is exactly the quarter a TTM window needs.

The compatibility key is therefore concept, unit and **start date**. A
year-to-date series starts on the first day of its fiscal year, so a shared
start date identifies the fiscal year exactly and does so from the data rather
than from a label. `tests/test_facts.py` pins this with a case built from the
real shape.

### Quarters are derived from any two year-to-date periods, not only Q4

The PRD names `Q4 = FY − 9M YTD`. That is one case of a general rule, and only
the general rule is enough: filers routinely report depreciation, stock
compensation and impairment year-to-date only, so Q2 and Q3 need the same
subtraction. The compatibility check is identical, and a reported quarter
always beats a derived one for the same period.

### An excluded unsupported clause is disclosed, not fatal

The PRD lists `unsupported_adjustment` among the reason codes that produce
NOT_COMPUTABLE, and also says a reviewer may unblock approval by excluding an
unsupported component with a note. Both cannot hold: if excluding a clause
still made every later run NOT_COMPUTABLE, the exclusion would be pointless.

Headroom resolves it this way:

* a component whose item is `unmapped` or `unsupported` and which has **not**
  been excluded blocks approval, and makes a run NOT_COMPUTABLE if one is
  somehow attempted;
* a component the reviewer **excluded** with a note is left out of the
  calculation and recorded as a `unsupported_adjustment` *disclosure* on every
  scenario that would otherwise have included it.

The disclosure is shown on the deal and on the audit trail, so an exclusion is
never invisible — it just does not pretend the whole run is unusable.

### S3 drops deductions as well as add-backs

The PRD defines S3 as "base plus `standard` components". A deduction such as
"non-cash gains" is categorised `non_cash`, so S3 drops it too and S3 can
exceed S0 for an agreement whose deductions outweigh its add-backs. That makes
adjustment dependence negative. Headroom reports it as it falls out rather than
clamping it, because a negative number there is a true statement about the
agreement: its covenant EBITDA is *lower* than plain EBITDA.

## Arithmetic

### Verdicts are decided by cross-multiplication, never by a rounded ratio

`D / E ≤ T` is not computable exactly — the division rarely terminates.
`D ≤ T × E` is exact. Every verdict and every band test is written in the
second form, so a borrower exactly at 4.50x is never reported as a breach
because of a division remainder. The displayed ratio and cushion are rounded
for reading only.

### Multiple cap pools

The PRD defines a pool's cap against "EBITDA from every other component
included in that scenario", which is ambiguous once there are two pools. The
engine resolves it so that the result never depends on the order components are
listed in:

* `E_base` = the base term plus every component outside any pool;
* a `fixed` or `before_pool` percentage pool is measured on `E_base`, because
  "calculated before such add-backs" means before *all* the capped add-backs;
* the single `after_pool` pool, if there is one, is measured on `E_base` plus
  the allowances of the other pools, since it is defined on EBITDA including
  its own pool;
* two `after_pool` pools would depend on each other, so the schema rejects that
  as unsupported.

A Hypothesis property test asserts the order-independence this buys.

### Pro-rata attribution is quantised

When a pool binds, the allowance is split across its items pro rata by amount.
A third of an allowance has no exact decimal form, so each share is rounded to
the allowance's own quantum and the residual lands on the largest requested
item, with ties broken by component key. The split sums exactly to the allowed
amount and changes only the trace, never EBITDA.

### `dec_str` must not use `Decimal.normalize`

Found while wiring the API: `normalize()` rounds to the *ambient* decimal
context, so the canonical JSON — and therefore the output hash — depended on
which thread rendered it. FastAPI serves sync endpoints from a worker thread
with the default precision of 28, while the hand calculation ran at 40, and the
same run hashed two different ways. The function now formats the digits in full
and strips only trailing fractional zeros, which is exact and context-free.
`tests/test_scenarios.py` runs the same evaluation at three precisions in three
threads and asserts one hash.

## The add-back taxonomy

### The categories are the argument a lender has, not a description of the accounts

The first version classified add-backs as `standard`, `non_cash`, `one_time`
and `pro_forma`. That is a neutral description of where a charge sits in the
accounts, and it made the tool answer the wrong question. Treating a $240m
goodwill impairment as a "discretionary adjustment" put it in the same bucket
as projected synergies, which no credit professional would accept: impairment
and amortisation of acquired intangibles are add-backs a lender normally
allows. The result was a headline claiming 32.7% of Teleflex's covenant EBITDA
was discretionary and that the borrower sat 2.8% from a breach on plain
EBITDA. Both numbers were arithmetically correct in the old taxonomy and both were misleading.

The categories are now the ones that get argued about in a credit committee:

| Category | What is in it | Who decides |
| --- | --- | --- |
| `standard` | interest, taxes, D&A | the clause |
| `accepted_non_cash` | impairment, amortisation of acquired intangibles, stock-based compensation | the clause |
| `one_time` | a charge the contract calls unusual that the filings do not show recurring | the clause, then the filings |
| `aggressive_recurring` | a "one-time" charge reported in most of the last four fiscal years | **the filings** |
| `aggressive_pro_forma` | projected cost savings, synergies, run-rate adjustments | the clause |

**Stock-based compensation is the uncomfortable one.** It sits in
`accepted_non_cash` because that is where the market puts it, not because it is
obviously right - it is a real cost of paying people, settled in dilution
rather than cash. `ARGUABLY_ACCEPTED_ITEMS` marks it and the UI says
"arguably accepted" beside it rather than filing it away silently.

**Why `one_time` and `aggressive_recurring` are both needed.** The scenario
definitions require it: S2 removes the *recurring* "one-time" charges and keeps
the genuinely non-recurring ones, so the two cannot be one category. A
specification that named only four categories would have forced non-recurring
one-time charges into either the aggressive bucket or the accepted one, and
both would be wrong.

### Recurrence is decided from the filings, deterministically

Whether a charge is non-recurring is a question about the borrower's history,
not about the contract, and it is answerable: `backend/edgar/recurrence.py`
counts the fiscal years in which the mapped concept carries a **non-zero**
annual fact, over the last four fiscal years ending on or before the test
date. Three of four, by default, means it recurs. Both numbers are arguments
(`min_years`, `window_years`), and every year's amount, form and accession
number travels into the stored run.

Two decisions inside that are worth stating:

* **A charge of zero is not a charge.** Filers tag a sparse concept only in the
  periods where the amount is non-zero, so an absent year and a zero year mean
  the same thing. Counting zeros would make any consistently tagged concept
  look like it recurs.
* **Only fiscal years ending on or before the test date count.** A run is a
  statement about what was knowable at that date. Without the cut-off, the same
  run would change answer as later years were filed.

The promotion itself happens in the evaluator, not in the formula: the clause's
category is a property of the contract and never changes, while
`ComponentLine.effective_category` records what it was judged as and
`recurrence_evidence` records why. The contract says one thing and the history
says another, and the result has to show both.

### What it did to the golden deal, reported as it fell out

Teleflex's clause (b)(x) adds back "cash restructuring and restructuring
related charges". `RestructuringCharges` is reported in FY2021 (14,999,000),
FY2022 (18,802,000), FY2023 (4,224,000) and FY2024 (14,157,000) - four of four
- so the add-back is judged `aggressive_recurring`.

| Figure | Old taxonomy | Credit taxonomy |
| --- | ---: | ---: |
| S0 Contractual | 894,045,000 | 894,045,000 |
| S2 | 885,599,000 ("no one-time") | 885,599,000 (without aggressive) |
| S3 | 601,382,000 (standard only) | 885,599,000 (conservative) |
| Dependence | 32.7% on discretionary adjustments | **0.94% on aggressive adjustments** |
| Accepted non-cash share | not reported | **31.8%** |
| S3 leverage | 2.74x | 1.86x |

**This is a much weaker finding, and it is the right one.** Teleflex's covenant
EBITDA is heavily adjusted but not aggressively adjusted: 284m of the 894m is
impairment and stock compensation, and 8.4m is the only add-back a lender would
argue with. The deal passes on every scenario. The dramatic version of this
case did not survive either the basis fix or the taxonomy fix, and nothing was
tuned to keep it.

It also says something about the sample: Teleflex was chosen because its
agreement exercised the formula language, not because its EBITDA definition was
aggressive. Finding a borrower whose definition *is* aggressive is a selection
problem, and the honest way to report the current golden set is that it
contains one conservative borrower.

### Aggressive dependence is measured against S2, not S3

`(S0 - S2) / S0`. The old metric measured against S3 and so counted every
non-cash charge as a dependence. The accepted non-cash share is reported
alongside it and is computed from the component contributions directly, because
no pair of scenarios isolates that class - S2 still holds the genuinely
non-recurring one-time charges.

## Reporting basis

### One reporting basis per window, and the restatement that forced it

The PRD says a quarter may be derived from two cumulative periods when they
share concept, unit, fiscal year and start date. That is necessary and not
sufficient. A filer that restates rarely republishes every period the
restatement affected, so two facts can satisfy all four conditions and still be
two different measurements.

Teleflex restated 2024 and 2025 when it separated its business. The 2026 10-K
reissued the 2024 full year — depreciation from 274,601,000 to 161,534,000 —
and never reissued the nine months to 29 September 2024. Taking the most
recently filed value for each period independently, which is what the build did
before this change, therefore derived the fourth quarter of 2024 as the
restated year minus the originally reported nine months:

    161,534,000 − 202,809,000 = −41,275,000

A quarter cannot have negative depreciation. Nothing downstream could catch it,
because the TTM total it summed into — 102,869,000 — looked like an ordinary
number. It reached `expected.json`, the README's headline table and the
verification worksheet, and it was the reason the golden deal appeared to sit
2.8% from a breach on plain EBITDA.

Three rules now hold, all of which refuse rather than approximate:

* **A window is built from one vintage.** A year-to-date series is cut at the
  first filing that reported one of its periods with a different value, and
  only one side of the cut survives. A series nobody restated is kept whole,
  because its single presentation is both the original and the current figure.
  Several restatements leave several boundaries; the restated cohort is cut at
  the latest and the original cohort at the earliest, so a cohort sits inside
  one presentation rather than straddling two.
* **The run commits to one basis for every item.** `choose_basis` prefers the
  restated figures, because they are the filer's current statement, and falls
  back to the figures as originally reported when the restated ones cannot
  produce everything the other basis could. An item only the rejected basis
  could have built is reported as `inconsistent_basis`, never mixed in. The
  basis is recorded on the inputs and travels into the canonical output hash,
  because two runs that chose differently are not the same measurement.
* **An arithmetic impossibility is refused.** A derived quarter is a
  subtraction, which is where a basis error surfaces as something the item
  cannot be. A negative derived quarter for depreciation or interest is
  reported as `implausible_value` rather than summed. Tax is deliberately
  excluded: a tax benefit is a real negative. A negative quarter the filer
  actually *reported* is also kept — that is the filer's statement, and
  Headroom does not overrule it.

For the golden deal the restated basis is unusable for two separate reasons,
and the worksheet records both: the fourth quarter of 2024 has no shorter
cumulative period to subtract, and the first quarter of 2025 falls outside the
restated cohort because that series was restated twice. The run uses the
figures as originally reported and says so.

What it cost: S0 covenant EBITDA moved from 657,174,000 to 894,045,000, S3 from
376,925,000 to 601,382,000, adjustment dependence from 42.6% to 32.7%, and the
S3 leverage verdict from TIGHT to PASS. The old figures were wrong. The finding
the deal exists to show survives — a third of covenant EBITDA is discretionary,
and stripping it moves leverage from 1.84x to 2.74x — but the dramatic version
of it, a borrower two percent from a breach, was an artefact of an impossible
quarter and is gone.

The same change turned the 31 December 2025 run from a confident BREACH into
four scenarios that decline. S3 there needs only the standard adjustments, but
depreciation at that date can only be derived as the restated year minus the
originally reported nine months, giving −33,230,000; it is refused. A run that
declines is the correct answer and the previous one was not.

### An analyst value carries a reporting basis, and a claim about one was wrong

The one-basis rule was written for the facts the pipeline selects. An analyst
value is a figure a human hand-summed from a period's filings, and it is just
as basis-bound: twelve months of impairment is a different number either side
of a restatement. `MappingRecord.analyst_value_basis` now records which vintage
it was sourced from, and a run built on the other basis refuses it with
`inconsistent_basis` rather than mixing it in. An untagged value is still used,
with the provenance saying the basis is unstated - refusing those outright
would be a migration rather than a guard.

**A correction.** While adding this, the claim that Teleflex's impairment value
mixed two vintages turned out to be false. The intangible FY2024 figure of
7,834,000 was first filed 2025-02-28 and merely repeated in the 2026 10-K, so
that series has no restatement boundary and the derivation sits inside one
cohort. The original claim confused deriving a quarter across two *filings* -
which every fiscal fourth quarter requires - with deriving it across two
*bases*. The value is tagged `as_originally_reported` and the worksheet records
what was wrong and why.

## Open: whether Consolidated EBITDA should include discontinued operations

**This is not resolved, and the figures above depend on it.**

Teleflex's restatement was a reclassification for discontinued operations. The
two bases are therefore not merely two vintages of the same measurement: the
figures as originally reported describe the whole company as it was, and the
restated figures describe continuing operations only. For the trailing twelve
months to 29 June 2025 the difference in depreciation alone is of the order of
100m.

Which one the covenant means is a question about the credit agreement, not
about the data. The agreement defines Consolidated EBITDA from Consolidated Net
Income with enumerated add-backs, and clauses (b)(ix) and (c)(iii) address net
losses and gains "from disposed, abandoned or discontinued operations or
assets" — which shows the drafters contemplated discontinued operations, but
does not settle how the base figure is measured once a disposal is classified
as discontinued. Resolving it needs the full definitions of Consolidated Net
Income and the GAAP clause read together, and in practice the borrower's own
compliance certificate, which is not public.

Headroom does not resolve it. What it does instead:

* it builds every item in a run on one basis, so whichever answer is right, the
  window is internally consistent;
* it names the basis on the deal screen, in the audit trail and in the output
  hash, so a reader can see which set of figures they are looking at;
* it refuses to mix them, which is the one answer that is wrong under either
  interpretation.

A reader who concludes the covenant is measured on continuing operations should
treat this run's figures as the wrong basis, not as a wrong calculation. The
restated basis cannot currently produce a complete window for this quarter at
all, so the honest position is that the question is open and the available
answer is the one the filings can support.

## Data

### A contractual item can span several reported concepts

Teleflex's clause (b)(v) adds "any non-cash charges", which for the test period
is goodwill impairment plus intangible impairment — two concepts, neither of
which has a fact in all four quarters, because filers tag sparse concepts only
in the quarters where the amount is non-zero. No mechanical TTM window can be
built from either.

Headroom's answer is the mapping gate: the analyst records a sourced value with
a rationale naming the filings and the accession numbers, and the run marks the
input `analyst` rather than `reported`. Multi-concept mappings that sum several
reported concepts would be a better answer and are future work; a sourced
analyst value is the honest one available today.

### Three of the golden deal's twelve inputs are analyst-sourced

Reported as a finding, not hidden: public XBRL does not carry everything a
credit agreement's EBITDA definition names. For the golden deal, impairment
charges, transaction costs and non-cash gains all needed an analyst value. Two
of the three are recorded as nil, and each rationale states the direction of
the resulting error. Nil transaction costs understate covenant EBITDA, which
never flatters the covenant; nil non-cash gains overstate it, which does, and
that one is flagged as a limitation rather than presented as a measurement.

### Only quarters with a complete TTM window are offered

The run screen lists the quarter ends for which four contiguous quarters exist
for the anchor concept, so an analyst cannot pick a date that is certain to
fail closed. Picking one that fails for a *different* item is still possible,
and then the reason codes say which item and which scenarios it affected.

## Scope

* One agreement version per deal. An amendment is a new agreement, not a diff;
  amendment tracking is future work.
* Public filings only. No compliance certificates, no private data, so every
  figure is an analyst's estimate and the UI says so on the deal screen.
* No authentication and no deployment. One analyst, one SQLite file.
* The frontend is light-only. A dark variant would need its own verdict
  palette to stay accessible, and half-inverting one would be worse than not
  offering it.

## Known limitations

| Limitation | Consequence |
| --- | --- |
| Capital lease obligations are not separately reported | Net debt is understated for the golden deal; the mapping rationale says so |
| Accrued interest stands in for cash interest | The coverage covenant is measured against accrued interest; conservative when accrued exceeds cash |
| The Acquisition Holiday raising the leverage cap to 5.00x is not representable | Only the standing 4.50x threshold is recorded, so a borrower inside a holiday is reported tighter than it is |
| Clause (b)(iv), (b)(vi), (b)(viii)–(ix), (b)(xi), (b)(xiii) and (c)(i), (c)(iii)–(iv) have no vocabulary item | Excluded with notes; the net effect understates covenant EBITDA on the add-back side and overstates it on the deduction side |
| The cross-period claw-back proviso needs state across periods | Recorded as `unsupported` and excluded; overstates covenant EBITDA if such payments occurred |
| A vocabulary change invalidates stored approvals | A formula version is JSON revalidated against the live schema, so renaming a category makes an approved version fail to load. That is the right behaviour for an approval gate - the reviewer approved categories that no longer exist - but it means `make clean` and a re-seed after a taxonomy change, and in a deployed system it would need a migration with re-approval |
| Section location is regex-based | An unusual layout fails loudly, and the fallback is an analyst pasting the clause, never a second model call |
| Whether the covenant is measured on continuing operations is unresolved | The run is built on the figures as originally reported and names that basis; on the other reading the figures are the wrong basis rather than a wrong calculation |
| The restated basis cannot build this quarter's window at all | The choice is forced rather than argued: the filer reissued the 2024 year without reissuing the nine months, and restated the 2025 series twice |
| An analyst value is only as good as the reading behind it | It is now tagged with the basis it was sourced on and refused with `inconsistent_basis` on a run built the other way, but nothing can check the arithmetic a human did in their head |

## An analyst value is bound to the period it was sourced for

Found by the integration test, and it was a real hole. A mapping record with an
analyst value had no period attached, so a run for a *different* quarter reused
last quarter's hand-summed figure without saying anything. For the golden deal
that turned a NOT_COMPUTABLE Q4 2025 into a confident BREACH built partly on
Q2 2025 numbers.

An analyst value is a figure for one TTM period, hand-summed from that period's
filings, so the record now carries `analyst_value_as_of` and the schema refuses
a value without one. A run for another test date reports
`missing_analyst_input` naming both dates, which is the same fail-closed rule
that already applied to a missing fact: reusing a stale number is the same
silent assumption as substituting zero.

The later-quarter case is worth looking at in the UI. At 2025-12-31, S0, S1 and
S2 all report `missing_analyst_input` naming both dates. S3 needs only the
standard adjustments, but depreciation at that date can only be derived as the
restated year minus the originally reported nine months, which comes to
−33,230,000 for the quarter, so it is refused as `implausible_value`. All four
scenarios decline, each naming the item that stopped it.

An earlier version of this section said S3 still computed there, to a loss, and
returned a BREACH. That answer was built on the impossible quarter; see "One
reporting basis per window" above.
