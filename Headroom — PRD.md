# Headroom — PRD

Covenant sensitivity engine for private credit · Oct 13, 2026 · @dharmi

## Overview

Headroom shows how sensitive a loan's covenant compliance is to the add-backs its credit agreement allows, by recalculating each covenant under alternative EBITDA assumptions.

**The problem.** Private credit loans carry financial covenants such as "Consolidated Total Debt must not exceed 5.00x Consolidated EBITDA." Every agreement defines its own Consolidated EBITDA: GAAP earnings plus a list of add-backs (restructuring costs, stock compensation, projected cost savings). Loose add-backs inflate EBITDA, so a leverage test can look comfortable while the cushion depends almost entirely on adjustments.

**What exists today.** Commercial tools (Hebbia, V7, Lumonic, Ontra) extract covenant terms from agreements. They stop at extraction. Headroom turns the definition into an executable, versioned formula and measures how much of the covenant cushion depends on each class of adjustment.

**Design principle.** The LLM only drafts a typed formula from clause text. A human reviews every component and approves an immutable version, and also approves every financial data mapping. Everything after that is deterministic arithmetic with a full audit trail.

**What Headroom does not claim.** Its figures are an analyst's estimate from public filings, not the borrower's official compliance numbers. Its scenarios show sensitivity to adjustments, not "true" earnings.

**One-line pitch:** a covenant sensitivity engine that uses an LLM only to draft formulas from contract text, behind human approval and an auditable deterministic calculation.

## Finance primer

These seven terms are all the finance you need to build and defend Headroom.

| Term | Meaning | Example |
| --- | --- | --- |
| EBITDA | Earnings before interest, taxes, depreciation and amortization: a proxy for the cash a business generates | Net income 40 + interest 25 + tax 10 + D&A 25 = EBITDA 100 |
| Add-back | An item the agreement lets the borrower add to EBITDA, usually "one-time" or "non-cash" | Restructuring costs 15, stock comp 8 |
| Maintenance covenant | A ratio the borrower must satisfy every quarter, or it is in default | Total leverage ≤ 5.00x, tested quarterly |
| Leverage ratio | Debt ÷ EBITDA. Higher means riskier | Debt 450 ÷ EBITDA 100 = 4.50x |
| Interest coverage | EBITDA ÷ interest expense. Lower means riskier | 100 ÷ 25 = 4.0x |
| Headroom (cushion) | How far EBITDA can fall before the covenant breaks | Debt 450 at max 5.00x needs EBITDA ≥ 90, so cushion = (100 − 90) ÷ 100 = 10% |
| TTM | Trailing twelve months: covenants are tested on the last four quarters combined | Q4 2025 + Q1, Q2, Q3 2026 |

The whole project rests on one observation: in the example, adding back 15 of restructuring lifts EBITDA from 100 to 115 and the cushion from 10% to about 22%. The covenant looks twice as safe without the business changing at all.

## Goals and non-goals

The mandatory milestone is one real credit agreement running end to end with every number hand-verified; two more agreements are a stretch goal, added only if they can be supported as rigorously.

**Goals**

1. Locate the EBITDA definition and the financial covenant section of a real credit agreement without an LLM.
2. Draft a typed formula from those clauses with an LLM, verify every cited span, and flag anything the formula language can't represent.
3. Let a human review each formula component against its clause and approve an immutable formula version.
4. Let a human approve each financial data mapping before it can feed a computable result.
5. Recalculate covenant EBITDA, leverage, interest coverage and cushion independently under four EBITDA scenarios, with exact decimal arithmetic.
6. Trace every displayed number to its clauses, filing facts, mappings, cap calculations and versions.
7. Report missing or unsuitable inputs with a structured reason, never as zero and never silently.

**Non-goals**

- No chat interface and no free-form Q&A over the agreement.
- No negative covenants, debt baskets, MFN or other non-financial terms.
- No compliance certificates or private-company data (public filings only).
- No agents, vector databases or RAG frameworks: none of them make the calculation more correct.
- No investment advice, credit rating or claim of official compliance status.
- No multi-user accounts, auth or production deployment.

## User and core flow

The user is a credit analyst on a private credit portfolio-monitoring team, and the flow has two approval gates: the formula, then the data mappings.

1. **Add a deal.** The analyst enters the company's CIK and the URL of its credit agreement exhibit on EDGAR.
2. **Locate.** Headroom fetches the agreement, finds the definitions article and the financial covenant section, and builds the definitions graph.
3. **Draft.** The LLM drafts the formula for Consolidated EBITDA and each financial covenant. Every component cites its exact span; anything it can't represent is marked `unsupported`.
4. **Approve the formula.** The analyst sees each component beside its highlighted clause, with its sign, category and cap rule, and approves, edits or rejects it. Approval is blocked while any reference, `unmapped` item or `unsupported` construct is unresolved. Approval creates an immutable formula version.
5. **Approve the mappings.** Headroom proposes an XBRL concept for each formula item with status `review_required`. The analyst marks each one `verified` (with a rationale) or `unavailable`.
6. **Run.** For a chosen test quarter, Headroom builds TTM financials and recalculates every covenant under all four scenarios independently.
7. **Read.** The analyst reads the deal overview, then the stress view, and opens the audit trail for any number.

Next quarter, the analyst reruns steps 6 and 7 only. Editing an approved formula or mapping creates a new version, and runs built on the old version are marked *superseded*.

## Architecture

Headroom runs as two loops: a one-time compile per agreement, and a fully deterministic evaluation every test quarter.

&#91;embedded content: Headroom pipeline · two loops, one LLM step\]

The approved formula version is the only thing that crosses from the left loop to the right one. The right loop also needs the analyst's approved data mappings, set once per deal. After both gates, quarterly runs need only fresh XBRL data, so they are cheap, repeatable and auditable.

If locating sections fails on an unusual layout, the analyst pastes the clause by hand. The fallback is a human, never a second LLM call.

## Formula language

The formula language is a closed, typed JSON format validated by Pydantic; it supports a deliberately small set of constructs and rejects everything else instead of approximating it.

**Closed item vocabulary**

- Base: `net_income`
- Standard adjustments: `interest_expense`, `income_tax_expense`, `depreciation_amortization`
- Discretionary adjustments: `stock_based_compensation`, `restructuring_charges`, `impairment_charges`, `transaction_costs`, `run_rate_cost_savings`, `other_non_cash_charges`
- Deductions: `gain_on_asset_sales`, `other_non_cash_gains`
- Debt: `long_term_debt`, `current_portion_long_term_debt`, `short_term_borrowings`, `finance_lease_liabilities`, `cash_and_equivalents`
- `unmapped`: a clause item outside the vocabulary
- `unsupported`: a construct the language can't express, stored with its span and a reason

Every component also carries a `category` (`standard`, `non_cash`, `one_time`, `pro_forma`) that the scenarios use. Any `unmapped` or `unsupported` component blocks approval until the reviewer maps it or excludes it with a note.

**Supported constructs**

| Construct | MVP | Example clause |
| --- | --- | --- |
| Base plus signed components | Supported | "plus, to the extent deducted… interest expense" |
| Fixed cap | Supported | "not to exceed $25,000,000" |
| Percentage cap measured before the pool | Supported | "15% of Consolidated EBITDA, calculated before such add-backs" |
| Percentage cap measured after the pool | Supported for one pool per formula | "calculated after giving effect to such add-backs" |
| `greater_of` a fixed amount and a percentage | Supported | "the greater of $50,000,000 and 15%…" |
| Shared pool across several items | Supported when the clause defines the pool explicitly | "the aggregate amount added back under clauses (f) and (g)" |
| Net debt with a cash cap | Supported | "less unrestricted cash not exceeding $75,000,000" |
| Step-down threshold schedule | Supported | "5.00x through 2025, 4.75x thereafter" |
| Nested caps, caps that reference other caps, `lesser_of` chains | Rejected as `unsupported` | — |
| Time-limited savings ("realised within 24 months") or ratio-conditional items | Rejected as `unsupported` | — |

**Cross-references.** A deterministic definitions graph resolves each term used inside the EBITDA definition (for example "Consolidated Net Income") to depth 2. The resolved definitions are sent with the draft request, and the graph is stored with the formula. A term that can't be found becomes `unresolved_reference` and blocks approval.

**Example: drafted EBITDA formula** (offsets illustrative)

```json
{
  "formula_id": "acme-2025-ca",
  "version": 1,
  "status": "approved",
  "source_hash": "sha256:…",
  "drafted_with": {"model": "<model id>", "prompt_version": "compile-v3", "attempts": 1},
  "metric": "consolidated_ebitda",
  "base": {"item": "net_income", "span": {"start": 48210, "end": 48249, "quote": "Consolidated Net Income for such period"}},
  "components": [
    {"item": "interest_expense", "sign": "+", "category": "standard", "span": {"…": "…"}, "review": {"decision": "accepted"}},
    {"item": "restructuring_charges", "sign": "+", "category": "one_time", "cap_pool": "A", "span": {"…": "…"}, "review": {"decision": "edited", "note": "category was non_cash"}},
    {"item": "run_rate_cost_savings", "sign": "+", "category": "pro_forma", "cap_pool": "A", "span": {"…": "…"}, "review": {"decision": "accepted"}}
  ],
  "cap_pools": {"A": {"kind": "greater_of", "fixed_amount": "50000000", "pct": "0.15", "basis": "before_pool"}}
}
```

**Cap engine.** Each pool is evaluated inside each scenario, never carried over from another scenario. For a pool, let E be EBITDA from every other component included in that scenario, A the sum of the pool's items included in that scenario, F the fixed amount and p the percentage:

| Cap kind | Cap C |
| --- | --- |
| Fixed | F |
| Percentage, before pool | p × E |
| Percentage, after pool | p × E ÷ (1 − p), from solving x ≤ p(E + x) |
| `greater_of` | max(F, the percentage cap) |

The allowed amount is min(A, max(C, 0)), and EBITDA = E + allowed amount. A negative E therefore gives a percentage cap of zero. When A exceeds C, the allowed amount is attributed to the pool's items pro rata by amount; this changes only the trace, never the EBITDA total. Two pools that both use the after-pool basis depend on each other, so the MVP rejects that as `unsupported`.

**Validation rules (all deterministic)**

1. The JSON parses against the strict schema; unknown fields are rejected.
2. Every `span.quote` equals the source text at `[start:end]` after whitespace normalisation, or the draft is rejected. This proves the text exists, not that it was interpreted correctly; interpretation is what human approval is for.
3. `unmapped`, `unsupported` and `unresolved_reference` components block approval, unless the reviewer excludes an unsupported component with a note.
4. Every referenced pool is defined and every defined pool is used.
5. Amounts and thresholds are strings parsed into `Decimal`; schedules are ordered by date.

**Versions.** A draft is editable. Approval freezes it as an immutable version with the reviewer's decision on every component (accepted, edited or rejected, plus a note). Any later change starts a new draft from that version.

## Data sources and mapping

All data is public and free; every financial fact keeps its provenance, and no fact enters a computable result until the analyst has approved its mapping.

**Credit agreements.** Public borrowers file credit agreements as Exhibit 10.x to an 8-K, 10-Q or 10-K. Find candidates with [EDGAR full-text search](https://www.sec.gov/edgar/search/) for phrases such as "Consolidated Total Leverage Ratio". For the mandatory milestone, pick one agreement with a maintenance leverage covenant, a capped add-back pool and no unsupported constructs, and verify its terms by hand.

**Financials.** One call per company to `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` returns every reported us-gaap fact, and the API needs no key ([SEC](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)). data.sec.gov doesn't support CORS, so all fetches run in the backend, with a descriptive `User-Agent`, throttling and a disk cache to respect the SEC's fair-access policy.

**Fact provenance.** Every stored fact keeps:

- concept, value and unit
- period type, plus start and end dates (duration) or the instant date
- form, accession number, filing date, fiscal year and fiscal period
- origin: `reported` or `derived`, with the transformation applied (for example "Q4 = FY − 9M YTD")

**Mapping records.** `mapping.yaml` lists candidate concepts per formula item, but a candidate is only a suggestion: an available concept is not necessarily the contractual item. Each deal gets its own mapping record per item, and only `verified` mappings can feed a computable result.

```json
{
  "formula_item": "interest_expense",
  "concept": "InterestExpenseNonoperating",
  "status": "review_required",
  "period_type": "duration",
  "rationale": null,
  "mapping_version": 1
}
```

Statuses: `review_required` (proposed, not yet usable), `verified` (approved with a written rationale), `unavailable` (no suitable concept; needs analyst input or stays not computable).

| Item | Candidate us-gaap concepts | Period type |
| --- | --- | --- |
| `net_income` | NetIncomeLoss, ProfitLoss | duration |
| `interest_expense` | InterestExpense, InterestExpenseNonoperating, InterestExpenseDebt | duration |
| `income_tax_expense` | IncomeTaxExpenseBenefit | duration |
| `depreciation_amortization` | DepreciationDepletionAndAmortization, DepreciationAndAmortization | duration |
| `stock_based_compensation` | ShareBasedCompensation, AllocatedShareBasedCompensationExpense | duration |
| `restructuring_charges` | RestructuringCharges | duration |
| `impairment_charges` | GoodwillImpairmentLoss, AssetImpairmentCharges | duration |
| `transaction_costs` | BusinessCombinationAcquisitionRelatedCosts | duration |
| `long_term_debt` | LongTermDebtNoncurrent | instant |
| `current_portion_long_term_debt` | LongTermDebtCurrent | instant |
| `cash_and_equivalents` | CashAndCashEquivalentsAtCarryingValue | instant |
| `run_rate_cost_savings` | none in XBRL: analyst input with a source note | duration |

**TTM construction**

1. Keep only facts in USD, of the right period type, from 10-Q, 10-K and their amendments.
2. Identify each quarter from its fiscal year, fiscal period and actual start and end dates together, never from period length alone.
3. When a period is reported more than once (an amendment or restatement), use the most recently filed value and record which filing it came from.
4. Derive fiscal Q4 as full year minus nine-month year-to-date only when both facts share the concept, unit, fiscal year and start date. Otherwise the result is `incompatible_facts`.
5. TTM is the sum of the four quarters ending on the test date. Debt and cash are instant facts dated exactly at the test date.
6. Anything missing returns a structured reason (see the next section), never zero.

## Scenario engine and evaluation

Every scenario runs the whole formula from scratch (components, deductions, exclusions and caps), so removing one item can correctly free cap room for another.

**Why from scratch.** Say pool A has a fixed cap of 20, with restructuring of 15 and projected savings of 15. In S0 the pool totals 30, so only 20 counts. In S1, savings are removed and restructuring's 15 now fits under the cap, so 15 counts. Subtracting the savings from S0 would wrongly give 5.

**Scenarios**

| Scenario | Components included | Question it answers |
| --- | --- | --- |
| S0 Contractual | Every permitted component, under the agreement's caps | Does it pass on the agreement's own terms? |
| S1 No pro forma | S0's components except `pro_forma`, recalculated | Does it pass without projected savings? |
| S2 No one-time | S1's components except `one_time`, recalculated | Does it pass without "one-time" charges too? |
| S3 Standard adjustments only | Base plus `standard` components | Does it pass on plain EBITDA? |

The stress view reports **adjustment dependence**, (S0 − S3) ÷ S0, the share of covenant EBITDA that comes from discretionary adjustments. It also attributes the gap between each pair of neighbouring scenarios to the components that caused it.

**Covenant formula**

```json
{
  "id": "max_total_leverage",
  "type": "max_ratio",
  "numerator": {"items": ["long_term_debt", "current_portion_long_term_debt"], "net_of_cash": {"enabled": true, "cap": "75000000"}},
  "denominator": "consolidated_ebitda",
  "schedule": [{"from": "2025-03-31", "threshold": "5.00"}, {"from": "2026-03-31", "threshold": "4.75"}],
  "test": {"frequency": "quarterly", "period": "ttm"},
  "span": {"start": 151004, "end": 151058, "quote": "shall not permit the Consolidated Total Leverage Ratio"}
}
```

**Metrics.** For a maximum leverage covenant with threshold T, debt D and EBITDA E:

```latex
\text{leverage} = \frac{D}{E}, \qquad \text{cushion} = 1 - \frac{D}{T \cdot E}, \qquad \text{additional debt capacity} = T \cdot E - D
```

For a minimum interest coverage covenant with threshold T and interest I, cushion = 1 − (T × I) ÷ E. The UI labels debt capacity as "under this covenant only": other covenants, debt baskets and borrowing conditions may still restrict new debt.

**Verdicts**

- **PASS**: cushion at or above the tight band (default 15%, configurable).
- **TIGHT**: cushion between 0 and the tight band.
- **BREACH**: cushion below 0, or EBITDA ≤ 0 for a leverage test.
- **NOT\_COMPUTABLE**: at least one required input has a reason code below.

**Missing-input reasons**

| Code | Meaning |
| --- | --- |
| `unapproved_formula` | No approved formula version exists for the deal |
| `ambiguous_mapping` | A required item's mapping is still `review_required` |
| `missing_quarter` | One of the four TTM quarters is neither reported nor derivable |
| `missing_instant` | No debt or cash fact is dated at the test date |
| `incompatible_facts` | Facts exist but can't be combined (for example, a Q4 derivation across different start dates) |
| `missing_analyst_input` | An item marked `unavailable` needs an analyst value and has none |
| `unsupported_adjustment` | The scenario includes a component the reviewer excluded as unsupported |

Reasons are returned per component and per scenario, so the analyst sees which facts are missing and which scenarios they affect. A missing value is never replaced by zero.

**Audit trail.** Every run stores the formula version and source hash, the mapping version, the evaluator version (git commit), the accession number and identity of every fact used, the scenario parameters, each pool's E, A, C, allowed amount and attribution per scenario, and a canonical output hash (sorted-key JSON with decimals as strings). The same inputs and versions must always produce the same hash.

## Product UI

The UI is four screens, each answering one question an analyst asks, in the order they ask it.

| Screen | Question it answers | What it shows |
| --- | --- | --- |
| 1. Deal overview | How much protection does the lender actually have? | Borrower, test period, contractual verdict, leverage, cushion, additional debt capacity, and a compact comparison of the four scenarios |
| 2. Formula review | Does the formula correctly represent the contract? | Agreement text beside the structured formula; each clause highlighted with its component, sign, category and cap rule; approve, edit or reject per component; a mapping review table for the data gate |
| 3. Stress testing | How dependent is compliance on discretionary adjustments? | Leverage and cushion across S0–S3, adjustment dependence, and which components explain each step down |
| 4. Audit trail | Can I independently verify this number? | Source clauses, XBRL facts with accession numbers, mapping decisions, cap calculations, formula and evaluator versions, output hash |

**Calculation trace.** Clicking any number opens its working. For an illustrative leverage of 4.50x: debt 450 (verified facts) ÷ covenant EBITDA 100 = 4.50x; cushion = 1 − 450 ÷ (5.00 × 100) = 10%; additional debt capacity under this covenant = 5.00 × 100 − 450 = 50. Each input links to its filing fact or clause.

**Styling.** Restrained institutional look: navy, white, muted green for PASS, amber for TIGHT and NOT\_COMPUTABLE, red only for BREACH. No decorative AI animations; evidence and clear labels come first.

## Tech stack and design decisions

The stack is Python 3.11 + FastAPI on the backend and React + TypeScript on the frontend; each choice below has a reason you should be able to say in one sentence.

| Decision | Choice | Why | Rejected |
| --- | --- | --- | --- |
| Backend language | Python 3.11 | Best libraries for HTML parsing, `Decimal`, Pydantic and the LLM SDK | Go: fast, but its parsing and LLM tooling would slow a 4-day build |
| API | FastAPI | Typed endpoints generated straight from the Pydantic models | Flask: no built-in validation |
| Formula schema | Pydantic v2, `extra="forbid"`, strict types | Rejects any field or type the LLM invents | Free-form JSON checked by hand |
| Arithmetic | `decimal.Decimal` | Exact money maths; thresholds like 4.75x compare exactly | `float`: 0.1 + 0.2 ≠ 0.3 |
| Locating sections | BeautifulSoup + lxml, regex on `"Term" means` | Deterministic, free, every position is a character offset | LLM segmentation: costs tokens, can't be traced |
| Cross-references | Definitions graph, resolved to depth 2 | The LLM sees only the definitions it needs, which cuts tokens and confusion | Sending the whole 150-page agreement |
| LLM call | Anthropic SDK, tool use with a JSON schema, temperature 0 | A compile makes one call per target: the EBITDA definition with its resolved references, then each financial covenant. Each call gets at most one retry carrying the validation error, and every call logs model id, prompt version and attempt | LangChain: unnecessary abstraction for one structured call |
| Storage | SQLite via SQLAlchemy | Deals, versioned formulas (draft / approved) and runs in one file | Postgres: no need for one user |
| EDGAR cache | On-disk, keyed by URL | Respects fair access and makes runs reproducible offline | Fetching live on every run |
| Frontend | React + Vite + TypeScript, Recharts | The review screen needs clause highlighting beside each formula component | Streamlit: weak for span-level review |
| Tests | pytest + Hypothesis | Property tests prove evaluator invariants, not just examples | Example tests only |

**Repo layout**

```
headroom/
  backend/
    edgar/        # EDGAR client, cache, XBRL facts, TTM builder
    agreement/    # fetch, normalise text, locate sections, definitions graph
    compiler/     # LLM prompt, schema, span verifier
    evaluator/    # covenant maths, caps, scenarios, verdicts
    api/          # FastAPI routes
    mapping.yaml
  frontend/       # React review + results screens
  data/golden/    # 3 agreements, hand-checked formulas and expected outputs
  docs/decisions.md
```

## Build plan for Claude Code

Build the financial engine first against one hand-verified agreement, then the data pipeline, then the LLM; if time runs out, ship one fully validated agreement rather than three weak ones.

1. **Day 1 — Engine and golden data.** Pick one suitable agreement and verify its covenant terms by hand. Implement the strict formula schema, `Decimal` arithmetic, the cap engine and the four independently recalculated scenarios. Write the expected results independently (in a spreadsheet) before running the code.
   - Done when: the golden outputs match exactly, the shared-pool reallocation case passes, and the Hypothesis property tests pass.
2. **Day 2 — SEC data pipeline.** Fetch and cache the agreement and companyfacts. Store full provenance. Build TTM with the compatibility checks, and create mapping records with statuses.
   - Done when: the golden deal's TTM inputs match the figures printed in its 10-K and 10-Qs, and every missing or incompatible case returns the right reason code.
3. **Day 3 — Compiler and review UI.** Locate sections, build the definitions graph, draft with the LLM, verify spans and flag unsupported constructs. Build the clause-highlighting review screen, immutable formula approval and the mapping review table.
   - Done when: the drafted formula is compared component by component with the hand-written one and the result is recorded, a corrupted span is rejected, and approval stays blocked while anything is unresolved.
4. **Day 4 — End to end.** Deal overview, stress view, audit trail and calculation trace. Integration test from ingestion to traced results. README, `docs/decisions.md` with known limitations, and a reproducible `make demo`.
   - Done when: a fresh clone runs the golden deal from CIK to traced results.

**Stretch.** Add two more agreements only if days 1–3 are solid, and only with the same hand-verified golden data.

## Testing and success metrics

Deterministic guarantees are tested to 100%; the compiler's accuracy is measured and reported with its dataset size and failure cases, never assumed.

**Test matrix**

| Category | Required tests |
| --- | --- |
| Arithmetic | Exact threshold boundaries, zero and negative EBITDA, negative cushion |
| Cap engine | Fixed, percentage (before and after pool), `greater_of`, shared pools, scenario-specific reallocation |
| XBRL | Missing quarters, duplicate facts, incompatible units, restatements, derived Q4 with and without compatible facts |
| Compiler | Invalid schemas, fabricated spans, real spans with wrong interpretations, unresolved terms, unsupported constructs |
| Reproducibility | Identical inputs and versions produce identical canonical output hashes |
| Fail-closed | Every missing required fact produces the correct reason code and NOT\_COMPUTABLE |
| Integration | One real agreement runs from ingestion to approved formula to traced results |

**Property tests (Hypothesis).** Removing a positive add-back never raises the cushion; a pool's allowed amount never exceeds its cap; scenario results are independent of the order components are listed in.

**Metrics**

| Metric | Target | Measured as |
| --- | --- | --- |
| Scenario consistency | 100% | Scenario outputs matching independently hand-calculated golden results |
| Determinism | 100% | One output hash across 10 identical runs |
| Span fidelity | 0 fabricated spans accepted | Corrupted-span tests rejected |
| Fail-closed | 100% | Removed facts that produce the correct reason code |
| Mapping coverage | Reported | Required items with `verified` mappings ÷ required items |
| Compiler semantic accuracy | Reported, with failures listed | Components with correct item, sign, category, cap rule and threshold ÷ golden components |

**Golden set.** `data/golden/` holds, per agreement: the exhibit URL, the hand-written formula, the verified mappings with rationales, the TTM inputs with accession numbers, and the expected result for every scenario. One agreement is mandatory; any others meet the same standard.

## Risks and interview talking points

The biggest risk is that public XBRL facts don't match the agreement's own definitions, which is why every mapping needs analyst approval and every result is labelled an estimate from public filings.

**Risks and limitations**

| Risk | Mitigation |
| --- | --- |
| A reported concept differs from the contractual item (e.g. interest expense scope) | Mapping status and written rationale; only `verified` mappings compute |
| Projected savings aren't in any filing | Item marked `unavailable`; S0 returns `missing_analyst_input` unless a sourced value is entered |
| Real agreements use constructs the language can't express | Flagged `unsupported`, never approximated; the golden agreement is chosen to avoid them |
| Agreement layouts vary, so section location can fail | The analyst pastes the clause; the fallback is a human, never another LLM call |
| Amendments change definitions | One agreement version in the MVP; amendment tracking is future work |
| A correct span with a wrong interpretation | Component-level human review, and semantic accuracy measured against golden formulas |
| Four days is tight | One agreement end to end is mandatory; more are stretch |

**Interview talking points**

1. *Why not let the LLM compute the covenant?* Finance needs reproducible, auditable numbers. I used the LLM only to draft a typed formula from legal text, behind human approval.
2. *What does span verification prove?* Only that the cited text exists. Whether it was interpreted correctly is what the component-level review and the semantic accuracy metric are for.
3. *Why recalculate every scenario from scratch?* Shared caps: removing one item can free room for another, so subtracting from the contractual result gives wrong numbers.
4. *How do you know a financial mapping is right?* I don't assume it. An available XBRL concept is a suggestion; the analyst verifies it with a rationale before it can compute.
5. *What happens when data is missing?* It fails closed with a reason code per component and scenario, never zero.
6. *How is this different from existing tools?* Commercial tools like [Hebbia](https://www.hebbia.com/resources/credit-agreement-software), [V7](https://www.v7labs.com/agents/ai-agent-for-leveraged-finance-bankers) and [Lumonic](https://www.lumonic.com/for-ai/best-covenant-compliance-software-private-credit-private-equity-2026) extract terms. Headroom turns them into versioned formulas and measures how dependent compliance is on adjustments, which matters because research from the St. Louis Fed links add-backs to higher default risk ([source](https://fedinprint.org/item/fedlwp/94811/original)).
7. *What would you build next?* Amendment tracking, compliance-certificate ingestion and portfolio alerts when a borrower moves from PASS to TIGHT.

## Sources

- [SEC – EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [SEC – EDGAR full-text search](https://www.sec.gov/edgar/search/)
- [St. Louis Fed – EBITDA Add-backs in Debt Contracting](https://fedinprint.org/item/fedlwp/94811/original)
- [Covenant Lite – The erosion of covenants in private credit](https://covenantlite.substack.com/p/covenant-lite-22-guardrails-gone)
- [Hebbia – Credit agreement software](https://www.hebbia.com/resources/credit-agreement-software)
- [V7 – AI agent for leveraged finance](https://www.v7labs.com/agents/ai-agent-for-leveraged-finance-bankers)
- [Lumonic – Covenant compliance software 2026](https://www.lumonic.com/for-ai/best-covenant-compliance-software-private-credit-private-equity-2026)
