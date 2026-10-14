"""One agreement from ingestion to traced results.

This is the end-to-end claim: a deal added from a CIK and an exhibit URL,
through both approval gates, to a stored run in which every displayed number
traces back to a clause, a filing fact, a mapping decision and a version.

The live test fetches from EDGAR and is skipped unless ``HEADROOM_LIVE=1``, so
the suite stays fast and offline by default.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from backend.api import service
from backend.api.db import make_session_factory
from backend.edgar.client import EdgarClient
from backend.evaluator.schema import FormulaVersion
from backend.pipeline import load_golden
from scripts.seed_golden import FixtureEdgar, _rewind_to_draft

GOLDEN = Path("data/golden/teleflex-2025q2")


@pytest.fixture()
def seeded(tmp_path):
    """The golden deal, driven through the real service layer."""
    deal_meta, golden_version, golden_mappings = load_golden(GOLDEN)
    context = service.Context(edgar=FixtureEdgar(), sources_cache={})
    factory = make_session_factory(
        "sqlite:///" + str(tmp_path / "integration.db").replace("\\", "/")
    )
    session = factory()

    deal = service.create_deal(
        session,
        context,
        deal_id=deal_meta["deal_id"],
        borrower=deal_meta["borrower"],
        cik=deal_meta["cik"],
        exhibit_url=deal_meta["exhibit_url"],
    )
    service.store_draft(session, deal, _rewind_to_draft(golden_version))
    row = service.approve_version(session, deal, 1, reviewer="integration test")
    approved = FormulaVersion.model_validate(row.payload)
    service.sync_mappings(session, context, deal, approved)
    for item, record in golden_mappings.items():
        service.decide_mapping(
            session,
            deal,
            item,
            status=record.status,
            rationale=record.rationale or "",
            concept=record.concept,
            analyst_value=record.analyst_value,
            analyst_value_as_of=record.analyst_value_as_of,
            reviewer="integration test",
        )
    stored = service.execute_run(
        session, context, deal, dt.date.fromisoformat(deal_meta["test_date"])
    )
    try:
        yield session, context, deal, approved, stored
    finally:
        session.close()


def test_the_deal_runs_from_ingestion_to_a_traced_result(seeded):
    _, _, deal, version, stored = seeded
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    payload = stored.payload

    assert deal.source_hash == version.source_hash
    assert version.status == "approved"
    assert payload["headline_verdict"] == "PASS"
    assert payload["aggressive_dependence"] == expected["aggressive_dependence"]

    by_id = {scenario["id"]: scenario for scenario in payload["scenarios"]}
    for name, want in expected["scenarios"].items():
        assert by_id[name]["ebitda"]["ebitda"] == want["ebitda"]
        for covenant in by_id[name]["covenants"]:
            got = want["covenants"][covenant["covenant_id"]]
            assert covenant["verdict"] == got["verdict"]
            # Compared as numbers: expected.json keeps the trailing zero the
            # hand calculation produced, which the canonical form strips.
            assert Decimal(covenant["ratio"]) == Decimal(got["ratio"])
            assert Decimal(covenant["cushion"]) == Decimal(got["cushion"])


def test_every_number_on_screen_traces_to_something(seeded):
    """The audit trail claim, checked rather than asserted in prose."""
    _, _, _, version, stored = seeded
    payload = stored.payload

    # Versions.
    assert payload["formula_version"] == version.version
    assert payload["source_hash"].startswith("sha256:")
    assert payload["evaluator_version"]
    assert payload["output_hash"].startswith("sha256:")

    # Every input used has a value, a mapping version, and provenance.
    for item, resolved in payload["inputs"]["items"].items():
        assert resolved["value"] is not None, item
        assert resolved["mapping_version"] is not None, item
        assert resolved["facts"], item
        if resolved["origin"] == "analyst":
            assert resolved["note"], item
        else:
            assert all(fact["accession"] for fact in resolved["facts"]), item

    # Every component of the contractual scenario traces to a clause.
    clauses = {
        component.clause for component in version.ebitda.components if component.clause
    }
    for line in payload["scenarios"][0]["ebitda"]["components"]:
        if line["component"].startswith("base:"):
            continue
        assert line["clause"] in clauses

    # Every cap pool shows its full working.
    for scenario in payload["scenarios"]:
        for pool in scenario["ebitda"]["pools"]:
            for field in ("e_before_pool", "a_requested", "cap", "allowed"):
                assert pool[field] is not None
            allowed = sum(float(part["allowed"]) for part in pool["attribution"])
            assert abs(allowed - float(pool["allowed"])) < 1e-9


def test_rerunning_the_same_quarter_reproduces_the_hash(seeded):
    session, context, deal, _, stored = seeded
    again = service.execute_run(
        session, context, deal, dt.date.fromisoformat(stored.test_date)
    )
    assert again.output_hash == stored.output_hash
    assert again.id != stored.id  # both runs are kept


def test_a_later_quarter_fails_closed_rather_than_guessing(seeded):
    """Teleflex's sparse impairment tagging means later quarters cannot be
    built mechanically. The run must say so per item, not fall back to zero."""
    session, context, deal, _, _ = seeded
    stored = service.execute_run(session, context, deal, dt.date(2025, 12, 31))
    payload = stored.payload
    assert payload["headline_verdict"] == "NOT_COMPUTABLE"
    reasons = {
        reason["code"]
        for scenario in payload["scenarios"]
        for reason in scenario["ebitda"]["reasons"]
    }
    # The analyst values were hand-summed from the filings covering the TTM
    # period ending 2025-06-29. Reusing them here would be the same silent
    # assumption as substituting zero, so they are refused by period.
    assert "missing_analyst_input" in reasons
    assert reasons <= {
        "missing_quarter",
        "missing_instant",
        "incompatible_facts",
        "missing_analyst_input",
        "ambiguous_mapping",
        "inconsistent_basis",
        "implausible_value",
    }
    notes = [
        reason["detail"]
        for scenario in payload["scenarios"]
        for reason in scenario["ebitda"]["reasons"]
        if reason["code"] == "missing_analyst_input"
    ]
    assert any("cannot be reused for 2025-12-31" in (note or "") for note in notes)

    # Every scenario declines, each naming the item that stopped it. The three
    # that need the analyst-valued clauses report missing_analyst_input. Under
    # the credit taxonomy even S3 needs them, because impairment is accepted
    # non-cash rather than discretionary. S3 also hits a second wall:
    # depreciation at this date can only be derived as the restated year minus
    # the originally reported nine months, which comes to a negative quarter,
    # so it is refused as implausible_value rather than summed into a
    # plausible-looking total. Both reasons are reported, not just the first.
    by_id = {scenario["id"]: scenario for scenario in payload["scenarios"]}
    for name in ("S0", "S1", "S2", "S3"):
        assert by_id[name]["ebitda"]["ebitda"] is None, name
        assert by_id[name]["ebitda"]["reasons"], name
    s3_codes = {reason["code"] for reason in by_id["S3"]["ebitda"]["reasons"]}
    assert "implausible_value" in s3_codes
    assert s3_codes <= {"implausible_value", "missing_analyst_input"}
    s3_items = {
        reason["item"]
        for reason in by_id["S3"]["ebitda"]["reasons"]
        if reason["code"] == "implausible_value"
    }
    assert s3_items == {"depreciation_amortization"}
    leverage = next(
        covenant
        for covenant in by_id["S3"]["covenants"]
        if covenant["covenant_type"] == "max_ratio"
    )
    assert leverage["verdict"] == "NOT_COMPUTABLE"
    assert leverage["ratio"] is None


@pytest.mark.skipif(
    os.environ.get("HEADROOM_LIVE") != "1",
    reason="set HEADROOM_LIVE=1 to fetch from EDGAR",
)
def test_the_live_agreement_still_matches_the_approved_version(tmp_path):
    """The approved formula is bound to the agreement text it cites. If EDGAR
    serves different bytes, the golden set is stale and should say so."""
    from backend.agreement.fetch import fetch_agreement

    deal_meta, version, _ = load_golden(GOLDEN)
    agreement = fetch_agreement(
        deal_meta["exhibit_url"], client=EdgarClient(cache_dir=tmp_path)
    )
    assert agreement.source_hash == version.source_hash
