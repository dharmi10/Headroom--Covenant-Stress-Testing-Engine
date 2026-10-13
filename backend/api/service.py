"""Deal operations behind the API: the two approval gates, and runs.

The rules that matter live here rather than in the routes, so they hold however
the operation is reached:

* a draft can be edited; an approved version can never be
* approval is refused while anything is unresolved
* approving a new version supersedes the runs built on the old one
* a mapping decision creates a new mapping version
* a run is stored with every version it was built from
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agreement.fetch import fetch_agreement
from backend.api.db import Deal, FormulaRow, MappingRow, RunRow, utcnow
from backend.compiler.draft import CompileResult, compile_agreement
from backend.compiler.spans import verify_version
from backend.edgar.client import EdgarClient
from backend.edgar.mapping import MappingRecord, propose, required_items
from backend.evaluator.approval import approval_blockers
from backend.evaluator.covenant import DEFAULT_TIGHT_BAND
from backend.evaluator.schema import FormulaVersion
from backend.pipeline import DealSources, coverage, load_sources, run_quarter, test_dates_for


class ServiceError(RuntimeError):
    """An operation the caller asked for is not allowed."""


class NotFound(ServiceError):
    pass


def _first_message(exc: PydanticValidationError) -> str:
    errors = exc.errors()
    return errors[0]["msg"] if errors else str(exc)


class Blocked(ServiceError):
    """Refused by a gate, with the reasons attached."""

    def __init__(self, message: str, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.details = details or []


@dataclass
class Context:
    """What an operation needs besides the database."""

    edgar: EdgarClient
    sources_cache: dict[str, DealSources]

    def sources(self, cik: str) -> DealSources:
        if cik not in self.sources_cache:
            self.sources_cache[cik] = load_sources(cik, client=self.edgar)
        return self.sources_cache[cik]


# -- deals -------------------------------------------------------------------


def create_deal(
    session: Session,
    context: Context,
    *,
    deal_id: str,
    borrower: str,
    cik: str,
    exhibit_url: str,
    notes: str | None = None,
) -> Deal:
    """Fetch and normalise the agreement, then record the deal."""
    if session.get(Deal, deal_id) is not None:
        raise ServiceError("a deal with id " + deal_id + " already exists")
    agreement = fetch_agreement(exhibit_url, client=context.edgar)
    sources = context.sources(cik)
    deal = Deal(
        id=deal_id,
        borrower=borrower,
        cik=cik,
        exhibit_url=exhibit_url,
        source_hash=agreement.source_hash,
        entity_name=sources.entity_name,
        agreement_text=agreement.text,
        notes=notes,
    )
    session.add(deal)
    session.commit()
    return deal


def get_deal(session: Session, deal_id: str) -> Deal:
    deal = session.get(Deal, deal_id)
    if deal is None:
        raise NotFound("no deal " + deal_id)
    return deal


def list_deals(session: Session) -> list[Deal]:
    return list(session.scalars(select(Deal).order_by(Deal.created_at)))


# -- formula versions --------------------------------------------------------


def _row_to_version(row: FormulaRow) -> FormulaVersion:
    return FormulaVersion.model_validate(row.payload)


def latest_version_row(session: Session, deal_id: str) -> FormulaRow | None:
    return session.scalars(
        select(FormulaRow)
        .where(FormulaRow.deal_id == deal_id)
        .order_by(FormulaRow.version.desc())
    ).first()


def approved_version_row(session: Session, deal_id: str) -> FormulaRow | None:
    return session.scalars(
        select(FormulaRow)
        .where(FormulaRow.deal_id == deal_id, FormulaRow.status == "approved")
        .order_by(FormulaRow.version.desc())
    ).first()


def get_version_row(session: Session, deal_id: str, version: int) -> FormulaRow:
    row = session.scalars(
        select(FormulaRow).where(
            FormulaRow.deal_id == deal_id, FormulaRow.version == version
        )
    ).first()
    if row is None:
        raise NotFound("no version " + str(version) + " for deal " + deal_id)
    return row


def store_draft(
    session: Session,
    deal: Deal,
    version: FormulaVersion,
    *,
    compile_log: dict[str, Any] | None = None,
) -> FormulaRow:
    """Store a draft, after checking its spans against this deal's agreement."""
    if version.source_hash != deal.source_hash:
        raise Blocked(
            "the draft was written against different agreement text than this deal holds"
        )
    failures = verify_version(version, deal.agreement_text)
    if failures:
        raise Blocked(
            "the draft has spans that do not match the agreement",
            [failure.as_dict() for failure in failures],
        )
    row = FormulaRow(
        deal_id=deal.id,
        version=version.version,
        status=version.status,
        source_hash=version.source_hash,
        payload=version.model_dump(mode="json", by_alias=True),
        compile_log=compile_log,
    )
    session.add(row)
    session.commit()
    return row


def next_version_number(session: Session, deal_id: str) -> int:
    row = latest_version_row(session, deal_id)
    return 1 if row is None else row.version + 1


def compile_deal(
    session: Session,
    deal: Deal,
    *,
    client: Any,
    model: str | None = None,
) -> FormulaRow:
    """Draft a formula for ``deal`` and store it as a new draft version."""
    result: CompileResult = compile_agreement(
        deal.agreement_text, deal_id=deal.id, client=client, model=model
    )
    version = result.version.model_copy(
        update={"version": next_version_number(session, deal.id)}
    )
    version.ebitda.version = version.version
    return store_draft(
        session,
        deal,
        version,
        compile_log={"calls": [log.as_dict() for log in result.logs]},
    )


def replace_draft(session: Session, deal: Deal, version: FormulaVersion) -> FormulaRow:
    """Overwrite an existing draft after a reviewer edit.

    Only a draft can be replaced. Editing an approved version means starting a
    new draft from it, which is what ``start_new_draft`` is for.
    """
    row = get_version_row(session, deal.id, version.version)
    if row.status != "draft":
        raise Blocked("version " + str(version.version) + " is " + row.status + ", not a draft")
    if version.status != "draft":
        raise Blocked("a replacement for a draft must itself be a draft")
    failures = verify_version(version, deal.agreement_text)
    if failures:
        raise Blocked(
            "the edited formula has spans that do not match the agreement",
            [failure.as_dict() for failure in failures],
        )
    row.payload = version.model_dump(mode="json", by_alias=True)
    row.source_hash = version.source_hash
    session.commit()
    return row


def start_new_draft(session: Session, deal: Deal, from_version: int) -> FormulaRow:
    """Begin a new draft from an existing version, leaving it untouched."""
    source = _row_to_version(get_version_row(session, deal.id, from_version))
    payload = source.model_dump(mode="json", by_alias=True)
    payload["version"] = next_version_number(session, deal.id)
    payload["status"] = "draft"
    payload["approved_by"] = None
    payload["approved_at"] = None
    payload["ebitda"]["version"] = payload["version"]
    payload["ebitda"]["status"] = "draft"
    draft = FormulaVersion.model_validate(payload)
    return store_draft(session, deal, draft)


def approve_version(
    session: Session, deal: Deal, version_number: int, *, reviewer: str
) -> FormulaRow:
    """Freeze a draft as an immutable approved version."""
    row = get_version_row(session, deal.id, version_number)
    if row.status == "approved":
        raise Blocked("version " + str(version_number) + " is already approved")
    version = _row_to_version(row)

    failures = verify_version(version, deal.agreement_text)
    if failures:
        raise Blocked(
            "approval is blocked: spans do not match the agreement",
            [failure.as_dict() for failure in failures],
        )
    blockers = approval_blockers(version)
    if blockers:
        raise Blocked(
            "approval is blocked while anything is unresolved",
            [blocker.as_dict() for blocker in blockers],
        )

    approved = version.model_copy(
        update={
            "status": "approved",
            "approved_by": reviewer,
            "approved_at": utcnow(),
        }
    )
    approved.ebitda.status = "approved"
    row.payload = approved.model_dump(mode="json", by_alias=True)
    row.status = "approved"

    # Any earlier approved version is retired, and the runs built on it are
    # marked superseded rather than deleted: the old numbers stay auditable.
    for other in session.scalars(
        select(FormulaRow).where(
            FormulaRow.deal_id == deal.id,
            FormulaRow.version != version_number,
            FormulaRow.status == "approved",
        )
    ):
        other.status = "superseded"
        payload = dict(other.payload)
        payload["status"] = "superseded"
        other.payload = payload
    for run in session.scalars(
        select(RunRow).where(
            RunRow.deal_id == deal.id, RunRow.formula_version != version_number
        )
    ):
        run.superseded = 1
    session.commit()
    return row


# -- mappings ----------------------------------------------------------------


def _mapping_rows(session: Session, deal_id: str) -> dict[str, MappingRow]:
    rows = session.scalars(select(MappingRow).where(MappingRow.deal_id == deal_id))
    return {row.formula_item: row for row in rows}


def mapping_records(session: Session, deal_id: str) -> dict[str, MappingRecord]:
    return {
        item: MappingRecord.model_validate(row.payload)
        for item, row in _mapping_rows(session, deal_id).items()
    }


def sync_mappings(
    session: Session, context: Context, deal: Deal, version: FormulaVersion
) -> dict[str, MappingRecord]:
    """Propose a record for every item the formula needs, keeping decisions.

    A new item introduced by a formula edit gets a fresh ``review_required``
    record. An item no longer required keeps its row, so an edit that puts it
    back does not lose the analyst's rationale.
    """
    sources = context.sources(deal.cik)
    existing = _mapping_rows(session, deal.id)
    records: dict[str, MappingRecord] = {}
    for item in required_items(version):
        row = existing.get(item)
        if row is not None:
            records[item] = MappingRecord.model_validate(row.payload)
            continue
        record = propose(item, available=sources.concepts)
        session.add(
            MappingRow(
                deal_id=deal.id,
                formula_item=item,
                payload=record.model_dump(mode="json"),
            )
        )
        records[item] = record
    session.commit()
    return records


def decide_mapping(
    session: Session,
    deal: Deal,
    item: str,
    *,
    status: str,
    rationale: str,
    concept: str | None = None,
    analyst_value: str | None = None,
    reviewer: str | None = None,
) -> MappingRecord:
    """Record an analyst decision on one mapping, bumping its version."""
    rows = _mapping_rows(session, deal.id)
    row = rows.get(item)
    if row is None:
        raise NotFound("no mapping record for " + item + " on deal " + deal.id)
    current = MappingRecord.model_validate(row.payload)
    if status not in ("verified", "unavailable", "review_required"):
        raise ServiceError("unknown mapping status: " + status)

    # The decision is authoritative about where the number comes from. An
    # analyst value replaces the concept outright, so a verified record never
    # holds both and which one computes is never implicit.
    if analyst_value is not None and analyst_value.strip():
        chosen_concept: str | None = None
        chosen_value: str | None = analyst_value.strip()
    elif concept is not None and concept.strip():
        chosen_concept = concept.strip()
        chosen_value = None
    else:
        chosen_concept = current.concept
        chosen_value = None

    updated = current.model_copy(
        update={
            "status": status,
            "rationale": rationale,
            "concept": chosen_concept,
            "analyst_value": chosen_value,
            "mapping_version": current.mapping_version + 1,
            "decided_by": reviewer,
            "decided_at": utcnow(),
        }
    )
    # Re-validate through the model so the gate's rules apply to the update.
    try:
        updated = MappingRecord.model_validate(updated.model_dump(mode="json"))
    except PydanticValidationError as exc:
        raise ServiceError(_first_message(exc)) from exc
    row.payload = updated.model_dump(mode="json")
    session.commit()
    return updated


# -- runs --------------------------------------------------------------------


def available_quarters(session: Session, context: Context, deal: Deal) -> list[dt.date]:
    row = approved_version_row(session, deal.id) or latest_version_row(session, deal.id)
    if row is None:
        raise Blocked("the deal has no formula yet")
    return test_dates_for(_row_to_version(row), context.sources(deal.cik))


def execute_run(
    session: Session,
    context: Context,
    deal: Deal,
    test_date: dt.date,
    *,
    tight_band: Decimal = DEFAULT_TIGHT_BAND,
) -> RunRow:
    """Run the approved formula for one quarter and store the result."""
    row = approved_version_row(session, deal.id)
    if row is None:
        raise Blocked(
            "no approved formula version exists for this deal",
            [{"code": "unapproved_formula", "target": deal.id, "detail": "approve a version first"}],
        )
    version = _row_to_version(row)
    records = sync_mappings(session, context, deal, version)
    run = run_quarter(
        version,
        context.sources(deal.cik),
        records,
        test_date,
        tight_band=tight_band,
    )
    stored = RunRow(
        deal_id=deal.id,
        test_date=test_date.isoformat(),
        formula_version=version.version,
        evaluator_version=run.evaluator_version,
        output_hash=run.output_hash,
        superseded=0,
        payload=run.as_dict(),
    )
    session.add(stored)
    session.commit()
    return stored


def list_runs(session: Session, deal_id: str) -> list[RunRow]:
    return list(
        session.scalars(
            select(RunRow).where(RunRow.deal_id == deal_id).order_by(RunRow.created_at.desc())
        )
    )


def get_run(session: Session, deal_id: str, run_id: int) -> RunRow:
    row = session.get(RunRow, run_id)
    if row is None or row.deal_id != deal_id:
        raise NotFound("no run " + str(run_id) + " for deal " + deal_id)
    return row


def deal_status(session: Session, context: Context, deal: Deal) -> dict[str, Any]:
    """What the two gates currently say about this deal."""
    row = latest_version_row(session, deal.id)
    approved = approved_version_row(session, deal.id)
    payload: dict[str, Any] = {
        "deal_id": deal.id,
        "borrower": deal.borrower,
        "entity_name": deal.entity_name,
        "cik": deal.cik,
        "exhibit_url": deal.exhibit_url,
        "source_hash": deal.source_hash,
        "agreement_chars": len(deal.agreement_text),
        "latest_version": row.version if row else None,
        "latest_status": row.status if row else None,
        "approved_version": approved.version if approved else None,
        "blockers": [],
        "mapping_coverage": None,
    }
    if row is not None:
        version = _row_to_version(row)
        payload["blockers"] = [blocker.as_dict() for blocker in approval_blockers(version)]
        records = mapping_records(session, deal.id)
        if records:
            verified, required = coverage(version, records)
            payload["mapping_coverage"] = {"verified": verified, "required": required}
    return payload
