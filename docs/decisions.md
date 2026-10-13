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
| Section location is regex-based | An unusual layout fails loudly, and the fallback is an analyst pasting the clause, never a second model call |
