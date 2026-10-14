"""An independent hand calculation of the golden deal's expected results.

This file deliberately does not import the evaluator. It writes the covenant
arithmetic out longhand from the TTM figures, the way a spreadsheet would, so
that ``expected.json`` is produced by a second implementation rather than by
the code under test. If the two ever disagree, one of them is wrong and the
test says so.

Run with::

    python -m scripts.hand_calc
"""

from __future__ import annotations

import json
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 40

OUT = Path("data/golden/teleflex-2025q2/expected.json")

D = Decimal

# TTM figures for the four quarters ending 2025-06-29, each hand-checked
# against the filing it came from (see ttm_inputs.json for accessions and
# docs/verification/teleflex.md for the quarter-by-quarter workings).
#
# All six reported items are taken on ONE reporting basis: the figures as
# Teleflex originally published them. Teleflex restated 2024 and 2025 when it
# separated its business, and the restating 10-K did not reissue the nine
# months to September 2024, so the restated figures cannot produce a complete
# window - the fourth quarter of 2024 would have to be the restated year minus
# the original nine months, a subtraction across two bases that produced a
# quarter with negative depreciation. See docs/decisions.md.
BASIS = "as_originally_reported"

NET_INCOME = D("191930000")       # unaffected: the annual total did not change
INCOME_TAX = D("56036000")
INTEREST = D("79945000")
DEP_AMORT = D("273471000")
STOCK_COMP = D("30376000")
IMPAIRMENT = D("253841000")       # basis-neutral: identical in both filings
RESTRUCTURING = D("8446000")
TRANSACTION_COSTS = D("0")
NON_CASH_GAINS = D("0")

LT_DEBT = D("1801645000")
CURRENT_DEBT = D("100000000")
CASH = D("253697000")

LEVERAGE_CAP = D("4.50")
COVERAGE_FLOOR = D("3.50")
TIGHT_BAND = D("0.15")
RESTRUCTURING_CAP_PCT = D("0.05")

# The add-back taxonomy, applied to this agreement's clauses by hand.
#
#   standard          (b)(i) income tax, (b)(ii) interest, (b)(iii) D&A
#   accepted_non_cash (b)(v) impairment, (b)(vii) stock compensation,
#                     (c)(ii) non-cash gains (a deduction)
#   one_time          (b)(iv) transaction costs - the filings quantify none,
#                     and there is no concept to test for recurrence
#   aggressive_recurring
#                     (b)(x) cash restructuring charges, capped at 5%.
#                     Teleflex reported RestructuringCharges in all four of
#                     the last four fiscal years - FY2021 14,999,000,
#                     FY2022 18,802,000, FY2023 4,224,000, FY2024 14,157,000 -
#                     so on a 3-of-4 threshold this "one-time" add-back is a
#                     recurring cost of doing business. Verified by hand from
#                     companyfacts; see docs/evaluation/recurrence.md.
#   aggressive_pro_forma
#                     none: this agreement permits no projected cost savings
STANDARD = INCOME_TAX + INTEREST + DEP_AMORT
ACCEPTED_NON_CASH = STOCK_COMP + IMPAIRMENT - NON_CASH_GAINS
ONE_TIME_UNCAPPED = TRANSACTION_COSTS
#: The capped pool holds only clause (b)(x), which recurrence makes aggressive.
POOL_IS_AGGRESSIVE_RECURRING = True

#: Which categories each scenario keeps.
SCENARIOS = {
    "S0": ("standard", "accepted_non_cash", "one_time", "aggressive_recurring",
           "aggressive_pro_forma"),
    "S1": ("standard", "accepted_non_cash", "one_time", "aggressive_recurring"),
    "S2": ("standard", "accepted_non_cash", "one_time"),
    "S3": ("standard", "accepted_non_cash"),
}


def scenario(keeps: tuple[str, ...]) -> dict[str, object]:
    """Recalculate from scratch, exactly as the agreement reads."""
    outside_pool = NET_INCOME + STANDARD
    if "accepted_non_cash" in keeps:
        outside_pool += ACCEPTED_NON_CASH
    if "one_time" in keeps:
        outside_pool += ONE_TIME_UNCAPPED

    # Clause (b)(x): 5% of Consolidated EBITDA calculated without giving
    # effect to the add-back of any item pursuant to that clause. The cap is
    # computed in every scenario; what changes is whether the pool has an item
    # in it at all.
    pool_category = "aggressive_recurring" if POOL_IS_AGGRESSIVE_RECURRING else "one_time"
    pool_in_scope = pool_category in keeps
    cap = RESTRUCTURING_CAP_PCT * outside_pool
    effective_cap = max(cap, D(0))
    requested = RESTRUCTURING if pool_in_scope else D(0)
    allowed = min(requested, effective_cap) if pool_in_scope else D(0)

    ebitda = outside_pool + allowed
    return {
        "e_outside_pools": str(outside_pool),
        "pool_cap": str(cap),
        "pool_requested": str(requested),
        "pool_allowed": str(allowed),
        "pool_binding": bool(pool_in_scope and requested > effective_cap),
        "ebitda": str(ebitda),
        "_ebitda": ebitda,
    }


def max_ratio(debt: Decimal, ebitda: Decimal) -> dict[str, object]:
    ratio = debt / ebitda
    cushion = D(1) - debt / (LEVERAGE_CAP * ebitda)
    capacity = LEVERAGE_CAP * ebitda - debt
    headroom = ebitda - debt / LEVERAGE_CAP
    if debt > LEVERAGE_CAP * ebitda:
        verdict = "BREACH"
    elif debt > (D(1) - TIGHT_BAND) * LEVERAGE_CAP * ebitda:
        verdict = "TIGHT"
    else:
        verdict = "PASS"
    return {
        "threshold": str(LEVERAGE_CAP),
        "net_debt": str(debt),
        "ratio": str(ratio),
        "ratio_display": str(ratio.quantize(D("0.01"))),
        "cushion": str(cushion),
        "cushion_display": str(cushion.quantize(D("0.0001"))),
        "debt_capacity": str(capacity),
        "headroom_ebitda": str(headroom),
        "verdict": verdict,
    }


def min_ratio(ebitda: Decimal, interest: Decimal) -> dict[str, object]:
    ratio = ebitda / interest
    cushion = D(1) - COVERAGE_FLOOR * interest / ebitda
    headroom = ebitda - COVERAGE_FLOOR * interest
    if COVERAGE_FLOOR * interest > ebitda:
        verdict = "BREACH"
    elif COVERAGE_FLOOR * interest > (D(1) - TIGHT_BAND) * ebitda:
        verdict = "TIGHT"
    else:
        verdict = "PASS"
    return {
        "threshold": str(COVERAGE_FLOOR),
        "interest": str(interest),
        "ratio": str(ratio),
        "ratio_display": str(ratio.quantize(D("0.01"))),
        "cushion": str(cushion),
        "cushion_display": str(cushion.quantize(D("0.0001"))),
        "headroom_ebitda": str(headroom),
        "verdict": verdict,
    }


def main() -> None:
    net_debt = LT_DEBT + CURRENT_DEBT - CASH

    scenarios = {name: scenario(keeps) for name, keeps in SCENARIOS.items()}

    payload: dict[str, object] = {
        "deal_id": "teleflex-2025q2",
        "test_date": "2025-06-29",
        "tight_band": str(TIGHT_BAND),
        "net_debt": str(net_debt),
        "basis": BASIS,
        "taxonomy": "standard / accepted_non_cash / one_time / aggressive_recurring / aggressive_pro_forma",
        "note": (
            "Computed longhand from the TTM figures, independently of the "
            "evaluator. Every reported item is taken on one reporting basis, "
            "the figures as originally published, because a restatement falls "
            "inside the window and the restated figures cannot produce a "
            "complete one. S0 and S1 are identical because the agreement "
            "permits no pro forma add-back: there are no projected cost "
            "savings to remove, so S1 equals S0. S2 removes clause (b)(x) "
            "restructuring, which the filings show recurring in four of the "
            "last four fiscal years; S3 additionally removes clause (b)(iv) "
            "transaction costs, recorded nil, so S3 equals S2."
        ),
        "scenarios": {},
    }

    for name, result in scenarios.items():
        ebitda = result.pop("_ebitda")
        payload["scenarios"][name] = {  # type: ignore[index]
            **result,
            "covenants": {
                "max_total_net_leverage": max_ratio(net_debt, ebitda),
                "min_interest_coverage": min_ratio(ebitda, INTEREST),
            },
        }

    s0 = D(payload["scenarios"]["S0"]["ebitda"])  # type: ignore[index]
    s2 = D(payload["scenarios"]["S2"]["ebitda"])  # type: ignore[index]
    # Aggressive adjustment dependence is measured against S2, not S3: the
    # question is how much rests on add-backs a lender would argue with, and a
    # lender does not argue with impairment or amortisation.
    aggressive = (s0 - s2) / s0
    payload["aggressive_dependence"] = str(aggressive)
    payload["aggressive_dependence_display"] = str(aggressive.quantize(D("0.0001")))
    accepted = ACCEPTED_NON_CASH / s0
    payload["accepted_non_cash_share"] = str(accepted)
    payload["accepted_non_cash_share_display"] = str(accepted.quantize(D("0.0001")))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print("net debt      ", net_debt)
    for name in ("S0", "S1", "S2", "S3"):
        row = payload["scenarios"][name]  # type: ignore[index]
        lev = row["covenants"]["max_total_net_leverage"]
        cov = row["covenants"]["min_interest_coverage"]
        print(
            name,
            "ebitda", row["ebitda"].rjust(12),
            "leverage", lev["ratio_display"].rjust(5) + "x",
            "cushion", lev["cushion_display"].rjust(8),
            lev["verdict"].ljust(6),
            "coverage", cov["ratio_display"].rjust(6) + "x", cov["verdict"],
        )
    print("aggressive adjustment dependence", payload["aggressive_dependence_display"])
    print("accepted non-cash share        ", payload["accepted_non_cash_share_display"])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
