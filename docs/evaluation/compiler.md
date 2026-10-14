# Compiler accuracy

**Status: not yet measured. No accuracy figure exists for this build.**

The LLM does exactly one job in Headroom: turn clause text into a typed
formula. Span verification proves the citation exists; it says nothing about
whether the clause was *read* correctly. This file is where the answer to that
second question goes, measured rather than asserted — and it is deliberately
empty of numbers until a real compile has run.

| | |
| --- | --- |
| Model under test | `claude-opus-5` (`backend/compiler/draft.py`, `DEFAULT_MODEL`) |
| Prompt version | `compile-v1` (`backend/compiler/prompt.py`, `PROMPT_VERSION`) |
| Dataset | 1 agreement, 17 components, 2 covenants (`data/golden/teleflex-2025q2`) |
| Runs completed | **0** |
| Blocker | No Anthropic credentials in the environment this was built in |

## Why there is no number here

Running the measurement needs `ANTHROPIC_API_KEY` (or `ant auth login`). The
environment this was last worked in has neither, so the harness exits 2 and
writes nothing:

```
$ make measure RUNS=5
no Anthropic credentials found: set ANTHROPIC_API_KEY or run 'ant auth login'

Nothing was measured. Options:
  - set ANTHROPIC_API_KEY and run again, or
  - run with --replay to score compiles recorded earlier.

No figure is written to docs/evaluation/compiler.md without a real compile:
an unmeasured accuracy is worse than an absent one.
```

An invented figure would be worse than this blank. Nothing in the repository
claims a compiler accuracy, and `README.md` reports the metric as "not yet
measured" rather than quoting one.

## What the measurement does when it runs

`make measure RUNS=5` compiles every golden agreement five times and writes
this file plus `compiler.json` from the results. Per run it records:

| Scored as | Fields |
| --- | --- |
| Component (one per clause) | `item`, `sign`, `category`, `cap_rule` |
| Covenant | `type`, `items`, `thresholds`, `net_of_cash` |
| Whole-clause | every field on the component correct |
| Coverage | clauses the draft failed to account for, clauses it invented |
| Retries | attempts per call, and the exact validation error each retry carried |

Clauses are matched on their label, which is what a human reviewer uses too. A
draft that renames a clause is counted as having missed it, because a reviewer
could not line it up against the contract either
(`backend/compiler/score.py`, `_clause_key`).

A clause the draft never accounted for counts as a **wrong component**, not as
an absent one: it is added to the denominator in
`backend/compiler/aggregate.py`, `aggregate`. Otherwise a model could score
100% by drafting one clause and ignoring sixteen.

### Run-to-run stability

The PRD asks for temperature 0. Current Claude models reject the sampling
parameters outright, so determinism cannot be bought from the sampler — see
`docs/decisions.md`. Stability is therefore *measured*: the same agreement is
compiled `RUNS` times and every clause's answers are compared.

The report separates two failure modes, because they need different fixes:

- a clause wrong **the same way every run** is a prompt or vocabulary problem;
- a clause right **four runs out of five** is a sampling problem.

`ClauseStability` in `backend/compiler/aggregate.py` records the distinct
answers per clause with their counts, so the distinction is visible rather than
averaged away.

## How to produce the figure

```bash
export ANTHROPIC_API_KEY=...      # or: ant auth login
make measure RUNS=5               # overwrites this file with real results
make measure-replay RUNS=5        # re-score saved compiles, no API calls
```

Every compile is saved to `data/transcripts/<deal>.run<N>.json`, so a scorecard
can be re-derived later without calling the model again, and a reviewer can
read exactly what the model returned.

## What this measurement will not establish

Even once it runs, the sample is one agreement and seventeen clauses. That is
an anecdote with error bars wide enough to drive a truck through: enough to
catch a compiler that is badly wrong, nowhere near enough to publish a rate.
The report says so in its own header, and adding agreements to
`data/golden/` is the only thing that changes it.

It also measures the compiler against **one reviewer's reading** of the clause
text. Where the hand-written golden formula is itself wrong, the compiler is
scored as wrong for agreeing with the contract. That is the right bias for a
tool whose output a human must approve, and it is a reason to read the listed
failures rather than only the percentage.
