"""The draft request.

One call per target: the EBITDA definition with its resolved references, then
each financial covenant. The model is given the clause text with its real
character offsets and is asked for a typed formula and nothing else. It is
never asked to compute anything, and never asked what a number should be.

``PROMPT_VERSION`` is recorded on every draft, so a formula approved last
quarter still says which instructions produced it.
"""

from __future__ import annotations

PROMPT_VERSION = "compile-v1"

SYSTEM = """\
You convert clauses from a credit agreement into a typed formula. You are a \
transcriber of contract text into a fixed format, not an analyst and not a \
calculator.

Rules, in order of importance:

1. Never invent a span. Every span's start and end are character offsets into \
the text you were given, and the quote must be the text at those offsets, \
copied character for character. The offsets you are given are absolute offsets \
into the full agreement; the excerpt tells you the offset its first character \
sits at, so add that number to any position you count within the excerpt. A \
span that does not match the agreement text is rejected outright.
2. Never approximate. If a clause is a construct the format cannot express, \
record it as unsupported with a reason. If a clause names something no \
vocabulary item covers, record it as unmapped with a reason. Both are correct \
answers. Forcing the clause into the nearest item is not.
3. Account for every enumerated clause. One component per clause, in document \
order, including deductions. A reviewer compares your list against the clause \
list, so a missing clause is worse than an unmapped one.
4. Record caps as the clause states them, in particular whether a percentage \
is measured before or after the add-backs it limits, and whether several \
clauses share one aggregate cap.
5. Never compute. You are not given any financial data and must not estimate \
any amount. Amounts you record are the amounts the contract states.

A human reviews every component against its clause before anything you produce \
can be used.\
"""

EBITDA_REQUEST = """\
Below is the covenant EBITDA definition from a credit agreement, followed by \
the definitions of the terms it refers to.

The definition begins at character offset {offset} of the agreement text. Every \
span you record must use absolute offsets, so add {offset} to any position you \
count from the start of the excerpt.

Record the definition with the record_ebitda_formula tool. Call it exactly once.

=== DEFINITION (begins at offset {offset}) ===
{definition}
=== END DEFINITION ===

=== REFERENCED DEFINITIONS (context only; do not take spans from here) ===
{references}
=== END REFERENCED DEFINITIONS ===\
"""

COVENANT_REQUEST = """\
Below is the financial covenant section of a credit agreement, followed by the \
definition of the ratio this request is about.

The section begins at character offset {offset} of the agreement text. Every \
span you record must use absolute offsets, so add {offset} to any position you \
count from the start of the excerpt. The ratio definition is quoted from \
elsewhere in the agreement and begins at offset {ratio_offset}.

Record the covenant named "{ratio}" with the record_covenant tool. Call it \
exactly once, for that covenant only.

=== FINANCIAL COVENANT SECTION (begins at offset {offset}) ===
{section}
=== END SECTION ===

=== RATIO DEFINITION (begins at offset {ratio_offset}) ===
{ratio_definition}
=== END RATIO DEFINITION ===

=== SUPPORTING DEFINITIONS (context only; do not take spans from here) ===
{references}
=== END SUPPORTING DEFINITIONS ===\
"""

RETRY_PREFIX = """\
Your previous call was rejected. Fix exactly what the errors below say and call \
the tool again. Do not change anything the errors do not mention.

{errors}\
"""


def ebitda_request(definition: str, offset: int, references: str) -> str:
    return EBITDA_REQUEST.format(
        definition=definition,
        offset=offset,
        references=references or "(none resolved)",
    )


def covenant_request(
    *,
    ratio: str,
    section: str,
    offset: int,
    ratio_definition: str,
    ratio_offset: int,
    references: str,
) -> str:
    return COVENANT_REQUEST.format(
        ratio=ratio,
        section=section,
        offset=offset,
        ratio_definition=ratio_definition or "(not found)",
        ratio_offset=ratio_offset,
        references=references or "(none resolved)",
    )


def retry_request(errors: list[str]) -> str:
    bullets = "\n".join("- " + error for error in errors)
    return RETRY_PREFIX.format(errors=bullets)
