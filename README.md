# Headroom

A covenant sensitivity engine for private credit. It shows how much of a
borrower's covenant cushion depends on the add-backs its credit agreement
allows, by recalculating every covenant under alternative EBITDA assumptions.

An LLM is used for exactly one thing: drafting a typed formula from clause
text. A human reviews every component against its clause and approves an
immutable formula version, and approves every financial data mapping. After
those two gates, everything is deterministic arithmetic with a full audit
trail.

## What it found on the golden deal

Teleflex Incorporated, TTM to 29 June 2025, against its Third Amended and
Restated Credit Agreement:

| Scenario | Covenant EBITDA | Leverage | Cushion | Verdict |
| --- | ---: | ---: | ---: | --- |
| S0 Contractual | 657,174,000 | 2.51x | 44.3% | PASS |
| S1 No pro forma | 657,174,000 | 2.51x | 44.3% | PASS |
| S2 No one-time | 653,274,000 | 2.52x | 43.9% | PASS |
| S3 Standard adjustments only | 376,925,000 | 4.37x | 2.8% | TIGHT |

The covenant allows a maximum net leverage of 4.50x. On the agreement's own
terms the borrower is comfortable, with 44% of cushion. **42.6% of that
covenant EBITDA comes from discretionary adjustments** — mostly a $240m
non-cash goodwill impairment added back under the "any non-cash charges"
clause. On plain EBITDA the ratio is 4.37x and the cushion is 2.8%.

That gap is the entire point of the tool. Nothing about the business changed
between the first row and the last.

S0 and S1 are identical because this agreement permits no pro forma add-back:
there are no projected cost savings to remove. The ladder still works; its
first step is simply empty, and the UI says so.

## Running it

Needs Python 3.11+ and Node 20+.

```bash
make install     # virtualenv, Python deps, npm deps
make test        # the full suite
make demo        # load the golden deal through both gates and run its quarter
```

`make demo` works offline from the committed golden fixtures. `make demo-live`
fetches the agreement and the financials from EDGAR instead, and fails loudly
if the agreement text no longer hashes to what the approved formula was
written against.

Then, in two terminals:

```bash
make api         # http://127.0.0.1:8000  (and /docs for the typed API)
make ui          # http://localhost:5173
```

Drafting a formula with the LLM needs Anthropic credentials
(`ANTHROPIC_API_KEY`, or `ant auth login`). Everything else — the golden deal,
the runs, all four screens — works without them.

## The two loops

```
  compile, once per agreement                  evaluate, every test quarter
  ───────────────────────────                  ────────────────────────────
  fetch exhibit                                fetch companyfacts
  normalise to text + hash                     build TTM with compatibility checks
  locate definitions + covenants   ┐           resolve each item through its mapping
  resolve references to depth 2    │           recalculate S0..S3 from scratch
  draft typed formula (LLM)        │           evaluate caps inside each scenario
  verify every span                │           test each covenant, exactly
  ── HUMAN APPROVES COMPONENTS ────┴──────┐    ── needs APPROVED MAPPINGS ──
  immutable formula version ──────────────┴──> canonical output hash
```

The approved formula version is the only thing that crosses from the left loop
to the right one. Quarterly reruns need no LLM call, which is why they are
cheap, repeatable and checkable.

## Screens

| Screen | Question | What it shows |
| --- | --- | --- |
| Deal | How much protection does the lender have? | The finding in a sentence, the four scenarios per covenant, debt capacity |
| Formula review | Does the formula match the contract? | Agreement text beside the formula, clause highlighted on selection, per-component review, the mapping table |
| Stress testing | How much rests on adjustments? | Adjustment dependence, the scenario ladder with the components behind each fall, per-scenario component states |
| Audit trail | Can I verify this myself? | Every input with its accession numbers, cap pool workings, mapping rationales, source clauses, versions and the output hash |

Clicking any figure opens its working, down to the filing it came from.

## How it is kept honest

**Fail closed.** A missing input is never a zero. Each one carries a reason
code (`missing_quarter`, `missing_instant`, `incompatible_facts`,
`ambiguous_mapping`, `missing_analyst_input`, `unsupported_adjustment`,
`unapproved_formula`) reported per component and per scenario, so the analyst
sees which fact is missing and which results it affects.

**Exact arithmetic.** Every amount is a `Decimal` parsed from a string; floats
are rejected at the schema boundary. Verdicts are decided by cross
multiplication (`D ≤ T × E`), never by comparing a rounded ratio, so a borrower
exactly at the threshold is never reported as a breach.

**Every scenario recalculated from scratch.** Shared caps make subtraction
wrong: if a pool capped at 20 holds restructuring of 15 and savings of 15, S0
allows 20 and S1 allows the full 15, not 5.

**Span verification.** A drafted span is rejected unless the agreement text at
its offsets equals the quote. That proves the text exists. It does *not* prove
the clause was read correctly — that is what the component-level review and the
measured semantic accuracy are for.

**Reproducibility.** A run stores the formula version, source hash, mapping
versions, evaluator version, every fact's accession number, each pool's
working, and a canonical output hash over sorted-key JSON with decimals as
strings. The same inputs and versions always produce the same hash.

## Results

| Metric | Target | Result |
| --- | --- | --- |
| Scenario consistency | 100% | All four scenarios and both covenants match `scripts/hand_calc.py`, a second implementation that never imports the evaluator |
| Determinism | 100% | One hash across 10 identical runs, and across three decimal precisions in three threads |
| Span fidelity | 0 fabricated spans accepted | Fabricated quotes, drifted offsets and out-of-range spans are all rejected |
| Fail-closed | 100% | Each removed fact produces its correct reason code; no scenario falls back to zero |
| Mapping coverage | Reported | 12 of 12 required items verified, of which 9 from reported concepts and 3 from sourced analyst values |
| Compiler semantic accuracy | Reported | `make measure` runs a real compile against the golden agreement and scores it clause by clause; it needs credentials, so it is not part of the test suite |

The test suite is 171 tests covering the arithmetic, the cap engine, XBRL
handling, the compiler, the API and the golden deal end to end, including
Hypothesis property tests for the three evaluator invariants: removing a
positive add-back never raises the cushion, a pool's allowance never exceeds
its cap, and results never depend on the order components are listed in. One
further test fetches from EDGAR and is skipped unless `HEADROOM_LIVE=1`.

### What it looks like when it cannot answer

Run the same deal at 31 December 2025 and three of the four scenarios decline.
Teleflex tags impairment only in the quarters where the amount is non-zero, so
no TTM window can be built mechanically, and the analyst values that filled the
gap were sourced for a different period and are refused rather than reused. S0,
S1 and S2 report `missing_analyst_input` naming both dates; S3 keeps only the
standard adjustments, all of them reported, computes to a loss, and returns a
BREACH with no finite ratio. Three scenarios decline to answer and the one that
can, does.

## Layout

```
backend/
  agreement/   fetch, normalise to text with stable offsets, locate sections,
               definitions graph
  edgar/       EDGAR client with cache and throttle, XBRL facts with
               provenance, TTM builder, mapping records
  compiler/    draft request, closed JSON schema, span verifier, accuracy scorer
  evaluator/   formula language, cap engine, scenarios, covenant maths, verdicts
  api/         FastAPI routes, SQLite storage, the two gates
  mapping.yaml candidate concepts per formula item
frontend/      React + TypeScript, four screens
data/golden/   one agreement: the hand-written formula, verified mappings with
               rationales, the TTM inputs with accession numbers, and the
               expected result for every scenario
docs/decisions.md
scripts/       golden set builder, independent hand calculation, demo seed,
               compiler measurement
```

## What this does not claim

The figures are an analyst's estimate built from public filings, not the
borrower's official compliance numbers. The scenarios show sensitivity to the
adjustments the agreement permits, not "true" earnings. Debt capacity is under
the one covenant it is shown against; other covenants, debt baskets and
borrowing conditions may still restrict new debt. None of it is investment
advice or a credit rating.

`docs/decisions.md` records every place the implementation departs from the
spec and why, and the known limitations of the golden deal's mappings.

## Sources

- [SEC — EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [SEC — EDGAR full-text search](https://www.sec.gov/edgar/search/)
- [St. Louis Fed — EBITDA add-backs in debt contracting](https://fedinprint.org/item/fedlwp/94811/original)
- The golden agreement: Teleflex Incorporated, EX-10.1 to the 8-K filed
  30 June 2025, accession 0000096943-25-000107
