"""The golden deal, end to end, against hand-computed expected results.

The expected numbers in ``expected.json`` come from ``scripts/hand_calc.py``,
which writes the covenant arithmetic out longhand and never imports the
evaluator. This test is therefore a comparison between two implementations,
not a snapshot of the code against itself.

The run replays the committed input snapshot, so it needs no network and the
golden set stays reproducible from a fresh clone.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from backend.agreement.normalise import text_hash
from backend.compiler.spans import verify_version
from backend.evaluator.approval import approval_blockers
from backend.evaluator.inputs import PeriodInputs
from backend.evaluator.run import evaluate_run
from backend.edgar.facts import parse_company_facts
from backend.edgar.mapping import required_items
from backend.evaluator.vocabulary import NON_NEGATIVE_FLOW_ITEMS
from backend.pipeline import DealSources, coverage, load_golden, run_quarter
from scripts.seed_golden import FixtureEdgar

GOLDEN = Path("data/golden/teleflex-2025q2")


@pytest.fixture(scope="module")
def golden():
    deal, version, records = load_golden(GOLDEN)
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    snapshot = json.loads((GOLDEN / "ttm_inputs.json").read_text(encoding="utf-8"))
    inputs = PeriodInputs.model_validate(
        {
            "deal_id": snapshot["deal_id"],
            "test_date": snapshot["test_date"],
            "quarters": snapshot["quarters"],
            "basis": snapshot["basis"],
            "basis_note": snapshot["basis_note"],
            "items": snapshot["items"],
        }
    )
    recurrence = snapshot.get("recurrence", {})
    return deal, version, records, expected, inputs, recurrence


@pytest.fixture(scope="module")
def run(golden):
    _, version, records, _, inputs, recurrence = golden
    mapping_versions = {
        item: records[item].mapping_version
        for item in required_items(version)
        if item in records
    }
    return evaluate_run(
        version, inputs, mapping_versions=mapping_versions, recurrence=recurrence
    )


def test_the_agreement_text_still_hashes_to_the_approved_source(golden):
    """An approved formula is bound to the text it was approved against."""
    _, version, _, _, _, _ = golden
    text = (GOLDEN / "agreement.txt").read_text(encoding="utf-8")
    assert text_hash(text) == version.source_hash


def test_every_span_in_the_golden_formula_verifies(golden):
    _, version, _, _, _, _ = golden
    text = (GOLDEN / "agreement.txt").read_text(encoding="utf-8")
    failures = verify_version(version, text)
    assert failures == [], [failure.as_dict() for failure in failures]


def test_the_golden_formula_is_approvable(golden):
    _, version, _, _, _, _ = golden
    assert approval_blockers(version) == []
    assert version.status == "approved"
    assert version.approved_by is not None


def test_every_required_mapping_is_verified(golden):
    _, version, records, _, _, _ = golden
    verified, required = coverage(version, records)
    assert (verified, required) == (12, 12)


def test_the_agreement_permits_no_pro_forma_add_back(golden):
    """Teleflex's definition has no projected cost savings clause, so S0 and
    S1 have to be identical. The scenario ladder still works; the first step
    is simply empty."""
    _, version, _, expected, _, _ = golden
    categories = {component.category for component in version.ebitda.components}
    assert "aggressive_pro_forma" not in categories
    assert expected["scenarios"]["S0"]["ebitda"] == expected["scenarios"]["S1"]["ebitda"]


@pytest.mark.parametrize("scenario", ["S0", "S1", "S2", "S3"])
def test_scenario_ebitda_matches_the_hand_calculation(run, golden, scenario):
    _, _, _, expected, _, _ = golden
    result = run.ebitda[scenario]
    assert result.reasons == [], [reason.as_dict() for reason in result.reasons]
    assert result.value == Decimal(expected["scenarios"][scenario]["ebitda"])
    assert result.e_base == Decimal(expected["scenarios"][scenario]["e_outside_pools"])


@pytest.mark.parametrize("scenario", ["S0", "S1", "S2", "S3"])
@pytest.mark.parametrize("covenant_id", ["max_total_net_leverage", "min_interest_coverage"])
def test_covenant_results_match_the_hand_calculation(run, golden, scenario, covenant_id):
    _, _, _, expected, _, _ = golden
    want = expected["scenarios"][scenario]["covenants"][covenant_id]
    got = run.covenants[scenario][covenant_id]
    assert got.verdict == want["verdict"]
    assert got.ratio == Decimal(want["ratio"])
    assert got.cushion == Decimal(want["cushion"])
    assert got.headroom_amount == Decimal(want["headroom_ebitda"])
    if covenant_id == "max_total_net_leverage":
        assert got.side.value == Decimal(expected["net_debt"])
        assert got.debt_capacity == Decimal(want["debt_capacity"])


def test_the_restructuring_cap_is_measured_before_its_own_pool(run, golden):
    """Clause (b)(x) is capped at 5% of EBITDA calculated without giving
    effect to that clause, so the cap is 5% of the pre-pool total."""
    _, _, _, expected, _, _ = golden
    pool = run.ebitda["S0"].pools["clause_x"]
    assert pool.basis == "before_pool"
    assert pool.e == Decimal(expected["scenarios"]["S0"]["e_outside_pools"])
    assert pool.cap == Decimal(expected["scenarios"]["S0"]["pool_cap"])
    assert pool.allowed == Decimal(expected["scenarios"]["S0"]["pool_allowed"])
    assert pool.binding is False  # 8.4m of restructuring against a 44.3m cap


def test_the_excluded_pension_pool_contributes_nothing(run):
    """Clause (b)(xi) was excluded as unsupported, so its fixed cap pool has
    no items in any scenario and adds nothing."""
    assert "clause_xi" not in run.ebitda["S0"].pools


def test_aggressive_dependence_matches_the_hand_calculation(run, golden):
    _, _, _, expected, _, _ = golden
    assert run.aggressive_dependence == Decimal(expected["aggressive_dependence"])


def test_teleflexs_ebitda_is_not_aggressive_under_the_credit_taxonomy(run, golden):
    """The finding, stated as it falls out rather than as it was hoped.

    Teleflex's covenant EBITDA is large but it is not *aggressive*: almost all
    of the add-back comes from impairment and stock compensation, which a
    lender normally accepts. Only the restructuring clause is aggressive, and
    it is under 1% of the total. The dramatic version of this deal - a borrower
    a hair from breach on stripped-down EBITDA - was an artefact of a
    mixed-basis quarter and of a taxonomy that treated impairment as
    discretionary. Both are fixed, and what is left is a borrower that passes
    comfortably on every scenario.
    """
    _, _, _, expected, _, _ = golden
    assert run.headline_verdict == "PASS"
    assert run.aggressive_dependence == Decimal(expected["aggressive_dependence"])
    assert run.aggressive_dependence < Decimal("0.01")
    assert run.accepted_non_cash_share == Decimal(expected["accepted_non_cash_share"])
    assert run.accepted_non_cash_share > Decimal("0.30")


def test_the_restructuring_add_back_is_judged_recurring_on_the_filings(run):
    """Clause (b)(x) adds back "cash restructuring and restructuring related
    charges". The contract calls that one-time; Teleflex has reported
    RestructuringCharges in all four of the last four fiscal years, so the run
    judges it aggressive_recurring and S2 removes it. The years and amounts
    travel with the result."""
    finding = next(
        row for row in run.recurrence if row["item"] == "restructuring_charges"
    )
    assert finding["recurs"] is True
    assert finding["years_reported"] == 4
    assert finding["years_examined"] == 4
    assert "4 of the last 4 fiscal years" in finding["evidence"]
    assert all(year["accession"] for year in finding["years"])

    line = next(
        row
        for row in run.ebitda["S0"].lines
        if row.item == "restructuring_charges"
    )
    assert line.category == "one_time"
    assert line.judged_as == "aggressive_recurring"

    excluded = next(
        row
        for row in run.ebitda["S2"].lines
        if row.item == "restructuring_charges"
    )
    assert excluded.state == "excluded_by_scenario"


def test_stripping_the_aggressive_add_back_still_moves_the_ratio(run):
    """Small is not nothing: the leverage ratio has to move the right way."""
    contractual = run.covenants["S0"]["max_total_net_leverage"]
    without_aggressive = run.covenants["S2"]["max_total_net_leverage"]
    assert without_aggressive.ratio > contractual.ratio
    assert without_aggressive.cushion < contractual.cushion
    assert without_aggressive.verdict == "PASS"


def test_exclusions_are_disclosed_on_every_scenario_that_would_include_them(run):
    disclosures = run.ebitda["S0"].disclosures
    assert disclosures, "the reviewer excluded unsupported clauses; S0 must say so"
    assert {reason.code for reason in disclosures} == {"unsupported_adjustment"}


def test_the_run_is_reproducible(golden):
    _, version, records, _, inputs, recurrence = golden
    hashes = {
        evaluate_run(version, inputs, recurrence=recurrence).output_hash
        for _ in range(10)
    }
    assert len(hashes) == 1


def test_the_input_snapshot_keeps_provenance_for_every_reported_fact(golden):
    _, _, _, _, inputs, _ = golden
    for item, resolved in inputs.items.items():
        assert resolved.usable, item
        assert resolved.facts, item
        if resolved.origin == "analyst":
            assert resolved.note
            continue
        for ref in resolved.facts:
            assert ref.accession, item
            assert ref.form in ("10-Q", "10-K", "10-Q/A", "10-K/A"), item


def test_the_test_date_is_a_real_quarter_end(golden):
    deal, _, _, _, inputs, _ = golden
    assert inputs.test_date == dt.date.fromisoformat(deal["test_date"])
    assert len(inputs.quarters) == 4


# -- the reporting basis -----------------------------------------------------
#
# The regression these three guard is the one that changed the golden figures.
# Taking the most recently filed value for each period independently mixed two
# presentations of Teleflex's 2024 inside one window, and the fourth quarter
# came out as the restated year minus the originally reported nine months:
# -41,275,000 of depreciation, which summed into a TTM total that looked
# entirely ordinary. The synthetic shape is pinned in tests/test_basis.py;
# these run against the committed filing data.


def test_the_golden_window_is_built_on_one_reporting_basis(golden):
    """Every fact in the run carries the same basis, named on the inputs."""
    _, _, _, _, inputs, _ = golden
    assert inputs.basis == "as_originally_reported"
    assert inputs.basis_note
    for item, resolved in inputs.items.items():
        for ref in resolved.facts:
            if resolved.origin == "analyst":
                continue
            assert ref.basis == inputs.basis, (item, ref.label)


def test_no_derived_quarter_in_the_golden_window_is_negative(golden):
    """Depreciation does not run backwards and a lender does not pay the
    borrower interest. A negative derived quarter here is the signature of two
    cumulative figures that were never on the same basis."""
    _, _, _, _, inputs, _ = golden
    for item in NON_NEGATIVE_FLOW_ITEMS:
        resolved = inputs.items.get(item)
        if resolved is None:
            continue
        for ref in resolved.facts:
            assert ref.value >= 0, (item, ref.label, ref.transformation)
        assert resolved.value is not None and resolved.value > 0, item


def test_the_golden_snapshot_rebuilds_from_the_committed_companyfacts(golden):
    """The snapshot is a record of what the pipeline resolves, not a figure
    kept by hand: rebuilding it from the committed fixture has to reproduce
    every item, the basis it was built on, and nothing else."""
    deal, version, records, _, inputs, _ = golden
    payload = FixtureEdgar().company_facts(deal["cik"])
    sources = DealSources(
        cik=deal["cik"],
        facts_by_concept=parse_company_facts(payload),
        entity_name=payload.get("entityName"),
    )
    rebuilt = run_quarter(
        version, sources, records, dt.date.fromisoformat(deal["test_date"])
    )
    assert rebuilt.inputs.basis == inputs.basis
    assert rebuilt.inputs.quarters == inputs.quarters
    assert set(rebuilt.inputs.items) == set(inputs.items)
    for item, resolved in sorted(rebuilt.inputs.items.items()):
        assert resolved.value == inputs.items[item].value, item
        assert resolved.origin == inputs.items[item].origin, item
