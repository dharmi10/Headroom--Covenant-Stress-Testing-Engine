"""The API, driven through both approval gates with the golden deal.

EDGAR is replaced by a client that only reads the committed golden fixtures, so
these tests touch no network and still exercise the real service rules.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.api import main, service
from backend.api.db import make_session_factory
from backend.edgar.client import CachedResponse, EdgarClient, OfflineError
from backend.pipeline import load_golden

GOLDEN = Path("data/golden/teleflex-2025q2")
DEAL_ID = "teleflex-2025q2"


class FixtureEdgar(EdgarClient):
    """An EDGAR client that serves the committed golden fixtures only."""

    def __init__(self) -> None:
        super().__init__(cache_dir="data/cache", allow_network=False)
        self.agreement = (GOLDEN / "agreement.txt").read_text(encoding="utf-8")
        snapshot = json.loads((GOLDEN / "companyfacts.json").read_text(encoding="utf-8"))
        self.facts_payload = snapshot

    def get(self, url: str, *, refresh: bool = False) -> CachedResponse:
        if url.endswith(".htm"):
            return CachedResponse(
                url=url,
                body=self.agreement.encode("utf-8"),
                content_type="text/plain; charset=utf-8",
                from_cache=True,
            )
        raise OfflineError("the fixture client does not serve " + url)

    def company_facts(self, cik, *, refresh: bool = False) -> dict:  # noqa: ANN001
        return self.facts_payload


@pytest.fixture()
def client(tmp_path, monkeypatch):
    factory = make_session_factory("sqlite:///" + str(tmp_path / "test.db").replace("\\", "/"))
    context = service.Context(edgar=FixtureEdgar(), sources_cache={})

    monkeypatch.setattr(main, "_session_factory", factory)
    monkeypatch.setattr(main, "_context", context)
    main.app.dependency_overrides[main.get_context] = lambda: context

    def session_override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    main.app.dependency_overrides[main.get_session] = session_override
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


@pytest.fixture()
def golden_formula() -> dict:
    _, version, _ = load_golden(GOLDEN)
    return version.model_dump(mode="json", by_alias=True)


def _create_deal(client) -> dict:
    response = client.post(
        "/deals",
        json={
            "deal_id": DEAL_ID,
            "borrower": "Teleflex Incorporated",
            "cik": "0000096943",
            "exhibit_url": "https://www.sec.gov/Archives/edgar/data/96943/x/ex101.htm",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _as_draft(payload: dict) -> dict:
    """The golden formula, rewound to the draft it was before approval."""
    draft = json.loads(json.dumps(payload))
    draft["status"] = "draft"
    draft["approved_by"] = None
    draft["approved_at"] = None
    draft["ebitda"]["status"] = "draft"
    return draft


def test_health_and_vocabulary(client):
    assert client.get("/health").json()["status"] == "ok"
    vocabulary = client.get("/vocabulary").json()
    assert "net_income" in vocabulary["items"]["base"]
    assert [row["id"] for row in vocabulary["scenarios"]] == ["S0", "S1", "S2", "S3"]
    assert vocabulary["tight_band"] == "0.15"


def test_creating_a_deal_normalises_and_hashes_the_agreement(client, golden_formula):
    status = _create_deal(client)
    assert status["deal_id"] == DEAL_ID
    assert status["source_hash"] == golden_formula["source_hash"]
    assert status["entity_name"] == "TELEFLEX INCORPORATED"
    assert status["approved_version"] is None


def test_a_duplicate_deal_is_refused(client):
    _create_deal(client)
    assert client.post(
        "/deals",
        json={
            "deal_id": DEAL_ID,
            "borrower": "x",
            "cik": "0000096943",
            "exhibit_url": "https://www.sec.gov/Archives/edgar/data/96943/x/ex101.htm",
        },
    ).status_code == 400


def test_an_unknown_deal_is_a_404(client):
    assert client.get("/deals/nope").status_code == 404


def test_the_agreement_slice_backs_clause_highlighting(client, golden_formula):
    _create_deal(client)
    span = golden_formula["ebitda"]["components"][0]["span"]
    response = client.get(
        "/deals/" + DEAL_ID + "/agreement",
        params={"start": span["start"], "end": span["end"]},
    )
    assert response.status_code == 200
    assert response.json()["text"] == span["quote"]


def test_a_formula_with_fabricated_spans_is_refused(client, golden_formula):
    _create_deal(client)
    tampered = _as_draft(golden_formula)
    tampered["ebitda"]["components"][0]["span"] = {
        "start": 100,
        "end": 140,
        "quote": "a clause that is not in this agreement",
    }
    response = client.post("/deals/" + DEAL_ID + "/formula", json=tampered)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "spans that do not match" in detail["message"]
    assert detail["blockers"][0]["target"].startswith("income_tax_expense")


def test_a_formula_for_different_agreement_text_is_refused(client, golden_formula):
    _create_deal(client)
    wrong = _as_draft(golden_formula)
    wrong["source_hash"] = "sha256:0"
    wrong["ebitda"]["source_hash"] = "sha256:0"
    response = client.post("/deals/" + DEAL_ID + "/formula", json=wrong)
    assert response.status_code == 409
    assert "different agreement text" in response.json()["detail"]["message"]


def test_storing_a_draft_proposes_a_mapping_for_every_required_item(client, golden_formula):
    _create_deal(client)
    assert (
        client.post("/deals/" + DEAL_ID + "/formula", json=_as_draft(golden_formula)).status_code
        == 201
    )
    mappings = client.get("/deals/" + DEAL_ID + "/mappings").json()
    assert len(mappings["records"]) == 12
    assert {record["status"] for record in mappings["records"]} == {"review_required"}
    # A candidate is flagged by whether the company actually reports it.
    interest = next(r for r in mappings["records"] if r["formula_item"] == "interest_expense")
    assert any(candidate["reported"] for candidate in interest["candidates"])


def test_approval_is_blocked_while_a_component_is_unreviewed(client, golden_formula):
    _create_deal(client)
    draft = _as_draft(golden_formula)
    for component in draft["ebitda"]["components"]:
        component["review"] = None
    client.post("/deals/" + DEAL_ID + "/formula", json=draft)

    response = client.post(
        "/deals/" + DEAL_ID + "/formula/1/approve", json={"reviewer": "analyst"}
    )
    assert response.status_code == 409
    codes = {blocker["code"] for blocker in response.json()["detail"]["blockers"]}
    assert "unreviewed_component" in codes
    # Stripping the reviews also strips the exclusions, so the clauses the
    # language cannot express show up as blockers again.
    assert codes == {"unreviewed_component", "unmapped", "unsupported"}


def test_a_reviewer_can_record_decisions_and_then_approve(client, golden_formula):
    _create_deal(client)
    draft = _as_draft(golden_formula)
    reviews = {
        component["clause"]: component["review"] for component in draft["ebitda"]["components"]
    }
    keys = []
    for component in draft["ebitda"]["components"]:
        keys.append(component["item"] + "@" + component["clause"])
        component["review"] = None
    client.post("/deals/" + DEAL_ID + "/formula", json=draft)

    blocked = client.post(
        "/deals/" + DEAL_ID + "/formula/1/approve", json={"reviewer": "analyst"}
    )
    assert blocked.status_code == 409

    decisions = []
    for component, key in zip(draft["ebitda"]["components"], keys):
        review = reviews[component["clause"]]
        decisions.append(
            {"target": key, "decision": review["decision"], "note": review.get("note")}
        )
    response = client.post(
        "/deals/" + DEAL_ID + "/formula/1/review",
        json={"reviewer": "analyst", "decisions": decisions},
    )
    assert response.status_code == 200, response.text
    assert response.json()["blockers"] == []

    approved = client.post(
        "/deals/" + DEAL_ID + "/formula/1/approve", json={"reviewer": "analyst"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_reviewing_an_unknown_component_is_rejected(client, golden_formula):
    _create_deal(client)
    client.post("/deals/" + DEAL_ID + "/formula", json=_as_draft(golden_formula))
    response = client.post(
        "/deals/" + DEAL_ID + "/formula/1/review",
        json={"reviewer": "a", "decisions": [{"target": "nope@x", "decision": "accepted"}]},
    )
    assert response.status_code == 400


def test_an_approved_version_cannot_be_edited(client, golden_formula):
    _create_deal(client)
    client.post("/deals/" + DEAL_ID + "/formula", json=_as_draft(golden_formula))
    client.post("/deals/" + DEAL_ID + "/formula/1/approve", json={"reviewer": "analyst"})

    response = client.post(
        "/deals/" + DEAL_ID + "/formula/1/review",
        json={
            "reviewer": "analyst",
            "decisions": [{"target": "income_tax_expense@(b)(i)", "decision": "accepted"}],
        },
    )
    assert response.status_code == 409
    assert "not a draft" in response.json()["detail"]["message"]


def test_editing_an_approved_version_starts_a_new_draft(client, golden_formula):
    _create_deal(client)
    client.post("/deals/" + DEAL_ID + "/formula", json=_as_draft(golden_formula))
    client.post("/deals/" + DEAL_ID + "/formula/1/approve", json={"reviewer": "analyst"})

    created = client.post("/deals/" + DEAL_ID + "/formula/1/new-draft")
    assert created.status_code == 201
    assert created.json()["version"] == 2
    assert created.json()["status"] == "draft"
    # Version 1 is untouched and still approved.
    assert client.get("/deals/" + DEAL_ID + "/formula/1").json()["status"] == "approved"


def test_a_run_needs_an_approved_formula(client, golden_formula):
    _create_deal(client)
    client.post("/deals/" + DEAL_ID + "/formula", json=_as_draft(golden_formula))
    response = client.post(
        "/deals/" + DEAL_ID + "/runs", json={"test_date": "2025-06-29"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["blockers"][0]["code"] == "unapproved_formula"


def test_a_run_on_unverified_mappings_fails_closed(client, golden_formula):
    _create_deal(client)
    client.post("/deals/" + DEAL_ID + "/formula", json=_as_draft(golden_formula))
    client.post("/deals/" + DEAL_ID + "/formula/1/approve", json={"reviewer": "analyst"})

    response = client.post("/deals/" + DEAL_ID + "/runs", json={"test_date": "2025-06-29"})
    assert response.status_code == 201
    result = response.json()["result"]
    assert result["headline_verdict"] == "NOT_COMPUTABLE"
    codes = {
        reason["code"]
        for scenario in result["scenarios"]
        for reason in scenario["ebitda"]["reasons"]
    }
    assert codes == {"ambiguous_mapping"}


def _verify_all_mappings(client, golden_mappings: dict) -> None:
    for record in golden_mappings["records"]:
        response = client.post(
            "/deals/" + DEAL_ID + "/mappings/" + record["formula_item"],
            json={
                "status": "verified",
                "rationale": record["rationale"],
                "concept": record["concept"],
                "analyst_value": record.get("analyst_value"),
                "reviewer": "analyst",
            },
        )
        assert response.status_code == 200, response.text


def test_the_full_flow_reproduces_the_golden_result(client, golden_formula):
    _create_deal(client)
    client.post("/deals/" + DEAL_ID + "/formula", json=_as_draft(golden_formula))
    client.post("/deals/" + DEAL_ID + "/formula/1/approve", json={"reviewer": "analyst"})

    golden_mappings = json.loads((GOLDEN / "mappings.json").read_text(encoding="utf-8"))
    _verify_all_mappings(client, golden_mappings)

    status = client.get("/deals/" + DEAL_ID).json()
    assert status["mapping_coverage"] == {"verified": 12, "required": 12}

    dates = client.get("/deals/" + DEAL_ID + "/test-dates").json()["test_dates"]
    assert "2025-06-29" in dates

    response = client.post("/deals/" + DEAL_ID + "/runs", json={"test_date": "2025-06-29"})
    assert response.status_code == 201
    result = response.json()["result"]

    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    by_id = {scenario["id"]: scenario for scenario in result["scenarios"]}
    for name in ("S0", "S1", "S2", "S3"):
        assert by_id[name]["ebitda"]["ebitda"] == expected["scenarios"][name]["ebitda"]
    assert result["headline_verdict"] == "PASS"
    assert result["adjustment_dependence"] == expected["adjustment_dependence"]

    leverage = next(
        covenant
        for covenant in by_id["S3"]["covenants"]
        if covenant["covenant_id"] == "max_total_net_leverage"
    )
    assert leverage["verdict"] == "TIGHT"


def test_a_run_is_stored_with_its_versions_and_can_be_read_back(client, golden_formula):
    _create_deal(client)
    client.post("/deals/" + DEAL_ID + "/formula", json=_as_draft(golden_formula))
    client.post("/deals/" + DEAL_ID + "/formula/1/approve", json={"reviewer": "analyst"})
    golden_mappings = json.loads((GOLDEN / "mappings.json").read_text(encoding="utf-8"))
    _verify_all_mappings(client, golden_mappings)

    created = client.post("/deals/" + DEAL_ID + "/runs", json={"test_date": "2025-06-29"}).json()
    listed = client.get("/deals/" + DEAL_ID + "/runs").json()
    assert len(listed) == 1
    assert listed[0]["output_hash"] == created["output_hash"]
    assert listed[0]["superseded"] is False

    read_back = client.get("/deals/" + DEAL_ID + "/runs/" + str(created["run_id"])).json()
    assert read_back["result"]["output_hash"] == created["output_hash"]
    assert read_back["formula_version"] == 1


def test_approving_a_new_version_supersedes_the_earlier_runs(client, golden_formula):
    _create_deal(client)
    client.post("/deals/" + DEAL_ID + "/formula", json=_as_draft(golden_formula))
    client.post("/deals/" + DEAL_ID + "/formula/1/approve", json={"reviewer": "analyst"})
    golden_mappings = json.loads((GOLDEN / "mappings.json").read_text(encoding="utf-8"))
    _verify_all_mappings(client, golden_mappings)
    client.post("/deals/" + DEAL_ID + "/runs", json={"test_date": "2025-06-29"})

    client.post("/deals/" + DEAL_ID + "/formula/1/new-draft")
    approved = client.post(
        "/deals/" + DEAL_ID + "/formula/2/approve", json={"reviewer": "analyst"}
    )
    assert approved.status_code == 200

    runs = client.get("/deals/" + DEAL_ID + "/runs").json()
    assert runs[0]["superseded"] is True
    assert client.get("/deals/" + DEAL_ID + "/formula/1").json()["status"] == "superseded"


def test_a_verified_mapping_needs_a_rationale(client, golden_formula):
    _create_deal(client)
    client.post("/deals/" + DEAL_ID + "/formula", json=_as_draft(golden_formula))
    response = client.post(
        "/deals/" + DEAL_ID + "/mappings/net_income",
        json={"status": "verified", "rationale": "   ", "concept": "NetIncomeLoss"},
    )
    assert response.status_code == 422


def test_a_mapping_decision_bumps_its_version(client, golden_formula):
    _create_deal(client)
    client.post("/deals/" + DEAL_ID + "/formula", json=_as_draft(golden_formula))
    first = client.post(
        "/deals/" + DEAL_ID + "/mappings/net_income",
        json={
            "status": "verified",
            "rationale": "NetIncomeLoss is the consolidated figure",
            "concept": "NetIncomeLoss",
        },
    ).json()
    assert first["mapping_version"] == 2
    second = client.post(
        "/deals/" + DEAL_ID + "/mappings/net_income",
        json={
            "status": "verified",
            "rationale": "switched to ProfitLoss to include minority interest",
            "concept": "ProfitLoss",
        },
    ).json()
    assert second["mapping_version"] == 3
    assert second["concept"] == "ProfitLoss"
