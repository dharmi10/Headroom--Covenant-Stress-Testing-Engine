# Generalisation: what broke on agreements other than Teleflex

Everything deterministic in Headroom - normalising the exhibit, locating the
definitions, locating the covenant section - was written against one agreement.
This file records what happened when it met others, including the cases still
unfixed.

The rule applied throughout: **a fix must be a statement about how agreements
are written, not about one document.** Where a fix could only be justified by
pointing at a single filer, it is recorded here as a limitation instead.

## Candidates screened

`python -m scripts.screen_candidates` fetches each exhibit, runs the real
locator over it and prints what it found. Found through EDGAR full-text search
on the Phase 2 criteria: an Exhibit 10.x credit agreement with a maintenance
leverage covenant and a capped add-back basket.

| Borrower | Exhibit | Chars | EBITDA definition located | Covenant section | Capped basket | Outcome |
| --- | --- | ---: | --- | --- | --- | --- |
| Teleflex | EX-10.1, 8-K 2025-06-30 | 716,914 | yes, `Consolidated EBITDA` | yes | 5% of EBITDA, $25m | **in the golden set** |
| Lantheus Holdings | EX-10.1, 8-K 2024-12-23 | 555,339 | **no → yes after two fixes** | yes | 20% of EBITDA | under consideration |
| Mercury Systems | EX-10.1, 8-K 2024-08-13 | 751,947 | yes, `Consolidated EBITDA` (18 clauses) | yes | 25% of EBITDA | under consideration |
| CACI International | EX-10.1, 8-K 2025-12-01 | 566,604 | yes, `Consolidated EBITDA` (15 clauses) | yes | 25% of EBITDA | under consideration |
| Lifetime Brands | EX-10.1, 8-K 2023-11-15 | 640,906 | yes, `EBITDA` (13 clauses) | yes | 10% and 15% of EBITDA | under consideration |
| Forward Air | EX-10.1, 8-K 2025-01-06 | 25,400 | no | no | — | **rejected: an amendment, not an agreement** |
| Superior Group | EX-10.1, 8-K 2025-03-11 | 8,776 | no | no | — | **rejected: an amendment, not an agreement** |
| American Axle | EX-10.1, 8-K 2025-02-24 | — | — | — | — | **rejected: EDGAR returns 404 for the indexed URL** |

No deal has been added to `data/golden/` from this list yet: a deal is only
admitted once the hand-written formula, the independent stdlib verifier and the
hand calculation agree exactly, which is the work in progress.

## Fixed, because the fix is general

### 1. C1 control characters where the quotation marks should be

**Found on:** Lantheus Holdings, EX-10.1 to the 8-K filed 2024-12-23.

**Symptom:** `definition_index` returned **0 definitions** for a 555,339
character credit agreement. `locate_ebitda_definition` therefore raised
`LocationError`, and the compiler could not be pointed at the definition at
all.

**Cause:** the document contains U+0093 (636 times), U+0094 (635), U+0092 (212)
and U+0096 (5) where left/right double quotes, an apostrophe and a dash belong.
Those are C1 control characters: cp1252 punctuation that was decoded as
Latin-1 somewhere upstream of EDGAR. The SEC served the file as `text/html`
with no charset, so nothing downstream had a reason to doubt it.

Every defined term in a credit agreement is announced by a quotation mark, so a
document in which the quotation marks are control characters has, as far as the
locator is concerned, no definitions.

**Fix:** `backend/agreement/normalise.py` maps U+0085 and U+0091-U+0097 to the
characters they stand for, alongside the existing typographic translations.

**Why this is general, not a special case:** the C1 block is control
characters. They never legitimately appear in prose, and in a filing they
always mean cp1252 punctuation decoded wrongly. Mapping them is the same kind
of statement as mapping a curly quote to a straight one.

**Blast radius checked:** Teleflex's agreement text contains no C1 characters,
so its source hash is unchanged and the approved formula version still
verifies. Asserted by `tests/test_golden.py::test_the_agreement_text_still_hashes_to_the_approved_source`.

**Tests:** `test_cp1252_control_characters_become_the_quotes_they_stand_for`,
`test_a_document_full_of_control_characters_still_yields_its_definitions`.

### 2. Definitions introduced by a colon rather than by "means"

**Found on:** Lantheus Holdings (same exhibit), after fix 1 took the definition
count from 0 to 2 - still wrong, out of several hundred real definitions.

**Symptom:** the two definitions found were `Benchmark` and `Information`,
which happen to use "means" in passing. The agreement's own style is:

```
"Consolidated EBITDA": with respect to any Person for any period, the
Consolidated Net Income of such Person ...
```

There is no "means" anywhere in the definitions article.

**Fix:** `DEFINITION_RE` in `backend/agreement/locate.py` now accepts a colon
as the defining verb, but only when a **lower-case word follows it**.

**Why the lower-case guard matters:** without it, every quoted heading in the
document becomes a defined term - `"Borrower": LANTHEUS MEDICAL IMAGING, INC.`
is a party list, not a definition. The guard is what keeps the colon form from
flooding the index with false positives.

**Why this is general:** "term, colon, definition" is one of the two house
styles in US credit agreements, not one firm's quirk.

**Blast radius checked:** Teleflex yields **413 definitions before and 413
after** the change. The colon branch is purely additive on documents that use
"means".

**Tests:** `test_a_definition_introduced_by_a_colon_is_found`,
`test_a_quoted_phrase_followed_by_a_colon_is_not_a_definition`.

### 3. A defined term wrapped across a line break

**Found on:** Lantheus Holdings (same exhibit), where the headword appears as
`"Consolidated\nEBITDA"`.

**Symptom:** even with fixes 1 and 2, the EBITDA definition was missed, because
the old pattern excluded newlines inside the term (`[^"\n]{1,120}`).

**Cause:** the filer's HTML breaks the line inside the headword. The normaliser
correctly turns the block-level break into a newline - it has to, or the last
word of one paragraph would join the first word of the next - so the newline
lands in the middle of a defined term.

**Fix:** the term may now contain any character except a quotation mark.
`_clean_term` already collapses whitespace, so the term is indexed under its
single-line name and a drafted quote still matches.

**Result:** Lantheus now yields **323 definitions**, and
`locate_ebitda_definition` finds `Consolidated EBITDA`, 7,645 characters long.

**Tests:** `test_a_term_wrapped_across_a_line_break_is_still_one_term`.

## Not fixed, recorded as limitations

### An amendment is not an agreement

EDGAR full-text search matches the covenant language in **amendments**, which
quote the phrase they are amending. Forward Air's EX-10.1 (25,400 characters)
and Superior Group's (8,776) are amendments: they contain the leverage covenant
sentence and the cap language, and nothing else - no definitions article, no
covenant section.

The locator fails loudly on both, which is the correct behaviour. No code
change is warranted: the candidate was wrong, not the locator. Selecting
candidates now checks the document length and the presence of a definitions
article before the exhibit is considered.

This is worth stating because it is a trap in the search, not in the code: a
full-text hit on covenant language is weak evidence that the document contains
a covenant.

### The indexed URL can 404

American Axle's EX-10.1 is listed in the full-text search index at a URL that
`www.sec.gov` returns 404 for. The client raises `EdgarError` with the status
code and the candidate is skipped. Nothing to fix in Headroom; recorded so the
gap in the candidate list is explained rather than silent.

### The screening script's maintenance-covenant detector is too strict

`scripts/screen_candidates.py` reports "maintenance test: NO" for Mercury,
CACI, Lantheus and Lifetime Brands, all of which do have maintenance
covenants - the covenant section was located and the ratios named in each
case. The regex in the screening script requires the covenant sentence and the
"four consecutive fiscal quarters" phrasing within 200 characters of each
other, and these agreements separate them.

This is a flaw in the **screening** heuristic, not in
`backend/agreement/locate.py`, whose own `COVENANT_SENTENCE_RE` found the
ratios correctly. It is recorded rather than quietly loosened, because the
screening output above was produced with the strict version and the table's
"maintenance test" column should be read as unreliable.

### Section location remains regex-based

Unchanged from `docs/decisions.md`: an unusual layout fails loudly and the
fallback is an analyst pasting the clause, never a second model call. The three
fixes above widen what the regexes accept; they do not change that a layout
nobody anticipated will still fail, and failing is preferred to guessing.
