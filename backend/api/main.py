"""The HTTP API.

Typed endpoints generated from the Pydantic models, so the frontend and the
tests see the same shapes the evaluator does. Every route is thin: it resolves
the deal, calls one service function and returns it. The gates live in the
service layer so they cannot be bypassed by reaching for a different route.
"""

from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from backend.api import service
from backend.api.db import DEFAULT_URL, make_session_factory
from backend.api.service import Blocked, Context, NotFound, ServiceError
from backend.compiler.draft import CompileError, anthropic_client
from backend.edgar.client import EdgarClient, EdgarError
from backend.evaluator.covenant import DEFAULT_TIGHT_BAND
from backend.evaluator.schema import FormulaVersion, Review
from backend.evaluator.vocabulary import SCENARIO_IDS, SCENARIO_LABELS

DATABASE_URL = os.environ.get("HEADROOM_DATABASE_URL", DEFAULT_URL)

app = FastAPI(
    title="Headroom",
    version="0.1.0",
    description=(
        "Covenant sensitivity engine. An LLM drafts a typed formula from clause "
        "text; a human approves every component and every data mapping; "
        "everything after that is deterministic arithmetic with an audit trail."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_session_factory = make_session_factory(DATABASE_URL)
_context = Context(edgar=EdgarClient(), sources_cache={})


def get_session() -> Iterator[Session]:
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def get_context() -> Context:
    return _context


# -- payloads ----------------------------------------------------------------


class DealCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deal_id: str = Field(min_length=1, max_length=80)
    borrower: str = Field(min_length=1)
    cik: str = Field(min_length=1)
    exhibit_url: str = Field(min_length=1)
    notes: str | None = None


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(description="The component key, or the covenant id.")
    decision: str = Field(description="accepted, edited, rejected or excluded_unsupported.")
    note: str | None = None
    item: str | None = Field(default=None, description="A corrected vocabulary item.")
    sign: str | None = None
    category: str | None = None
    cap_pool: str | None = None


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer: str = Field(min_length=1)
    decisions: list[ReviewDecision] = Field(min_length=1)


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer: str = Field(min_length=1)


class MappingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="verified, unavailable or review_required.")
    rationale: str = Field(min_length=1)
    concept: str | None = None
    analyst_value: str | None = None
    reviewer: str | None = None

    @field_validator("rationale")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a mapping decision requires a written rationale")
        return value


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_date: dt.date
    tight_band: str | None = Field(
        default=None, description="Cushion below which a covenant is TIGHT, e.g. 0.15."
    )


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = None


# -- error handling ----------------------------------------------------------


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFound):
        return HTTPException(status_code=404, detail={"message": str(exc)})
    if isinstance(exc, Blocked):
        return HTTPException(status_code=409, detail={"message": str(exc), "blockers": exc.details})
    if isinstance(exc, ServiceError):
        return HTTPException(status_code=400, detail={"message": str(exc)})
    if isinstance(exc, CompileError):
        return HTTPException(status_code=502, detail={"message": str(exc)})
    if isinstance(exc, EdgarError):
        return HTTPException(status_code=502, detail={"message": str(exc)})
    raise exc


# -- meta --------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "database": DATABASE_URL}


@app.get("/vocabulary")
def vocabulary() -> dict[str, Any]:
    """The closed item vocabulary and the scenarios, for the review screen."""
    from backend.evaluator.vocabulary import (
        BASE_ITEMS,
        CATEGORIES,
        DEBT_ITEMS,
        DEDUCTIONS,
        DISCRETIONARY_ADJUSTMENTS,
        SENTINEL_ITEMS,
        STANDARD_ADJUSTMENTS,
    )

    return {
        "items": {
            "base": list(BASE_ITEMS),
            "standard": list(STANDARD_ADJUSTMENTS),
            "discretionary": list(DISCRETIONARY_ADJUSTMENTS),
            "deductions": list(DEDUCTIONS),
            "debt": list(DEBT_ITEMS),
            "sentinels": list(SENTINEL_ITEMS),
        },
        "categories": list(CATEGORIES),
        "scenarios": [
            {"id": sid, "label": SCENARIO_LABELS[sid]} for sid in SCENARIO_IDS
        ],
        "tight_band": str(DEFAULT_TIGHT_BAND),
    }


# -- deals -------------------------------------------------------------------


@app.get("/deals")
def list_deals(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [
        {
            "deal_id": deal.id,
            "borrower": deal.borrower,
            "entity_name": deal.entity_name,
            "cik": deal.cik,
            "created_at": deal.created_at.isoformat(),
        }
        for deal in service.list_deals(session)
    ]


@app.post("/deals", status_code=201)
def create_deal(
    payload: DealCreate,
    session: Session = Depends(get_session),
    context: Context = Depends(get_context),
) -> dict[str, Any]:
    try:
        deal = service.create_deal(
            session,
            context,
            deal_id=payload.deal_id,
            borrower=payload.borrower,
            cik=payload.cik,
            exhibit_url=payload.exhibit_url,
            notes=payload.notes,
        )
        return service.deal_status(session, context, deal)
    except Exception as exc:  # noqa: BLE001 - translated to HTTP below
        raise _handle(exc) from exc


@app.get("/deals/{deal_id}")
def read_deal(
    deal_id: str,
    session: Session = Depends(get_session),
    context: Context = Depends(get_context),
) -> dict[str, Any]:
    try:
        return service.deal_status(session, context, service.get_deal(session, deal_id))
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@app.get("/deals/{deal_id}/agreement")
def read_agreement(
    deal_id: str,
    start: int = Query(0, ge=0),
    end: int | None = Query(None, ge=1),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """A slice of the normalised agreement, for clause highlighting."""
    try:
        deal = service.get_deal(session, deal_id)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    text = deal.agreement_text
    stop = len(text) if end is None else min(end, len(text))
    if start >= len(text):
        raise HTTPException(status_code=416, detail={"message": "start is past the end of the text"})
    return {
        "deal_id": deal_id,
        "start": start,
        "end": stop,
        "total": len(text),
        "source_hash": deal.source_hash,
        "text": text[start:stop],
    }


# -- formula gate ------------------------------------------------------------


@app.post("/deals/{deal_id}/compile", status_code=201)
def compile_deal(
    deal_id: str,
    payload: CompileRequest | None = None,
    session: Session = Depends(get_session),
    context: Context = Depends(get_context),
) -> dict[str, Any]:
    """Draft a formula with the LLM and store it as a new draft version."""
    try:
        deal = service.get_deal(session, deal_id)
        client = anthropic_client()
        row = service.compile_deal(
            session, deal, client=client, model=payload.model if payload else None
        )
        version = FormulaVersion.model_validate(row.payload)
        service.sync_mappings(session, context, deal, version)
        return {
            "version": row.version,
            "status": row.status,
            "compile_log": row.compile_log,
            "formula": row.payload,
            "blockers": service.deal_status(session, context, deal)["blockers"],
        }
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@app.post("/deals/{deal_id}/formula", status_code=201)
def put_formula(
    deal_id: str,
    payload: dict[str, Any],
    session: Session = Depends(get_session),
    context: Context = Depends(get_context),
) -> dict[str, Any]:
    """Store a formula drafted elsewhere, for example a hand-written one."""
    try:
        deal = service.get_deal(session, deal_id)
        version = FormulaVersion.model_validate(payload)
        row = service.store_draft(session, deal, version)
        service.sync_mappings(session, context, deal, version)
        return {"version": row.version, "status": row.status, "formula": row.payload}
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@app.get("/deals/{deal_id}/formula")
def list_versions(
    deal_id: str, session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    try:
        deal = service.get_deal(session, deal_id)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    return [
        {
            "version": row.version,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
            "source_hash": row.source_hash,
        }
        for row in deal.versions
    ]


@app.get("/deals/{deal_id}/formula/{version}")
def read_version(
    deal_id: str, version: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        row = service.get_version_row(session, deal_id, version)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    parsed = FormulaVersion.model_validate(row.payload)
    from backend.evaluator.approval import approval_blockers

    return {
        "version": row.version,
        "status": row.status,
        "formula": row.payload,
        "compile_log": row.compile_log,
        "blockers": [blocker.as_dict() for blocker in approval_blockers(parsed)],
    }


@app.post("/deals/{deal_id}/formula/{version}/review")
def review_version(
    deal_id: str,
    version: int,
    payload: ReviewRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Record the reviewer's decision on components and covenants."""
    try:
        deal = service.get_deal(session, deal_id)
        row = service.get_version_row(session, deal_id, version)
        parsed = FormulaVersion.model_validate(row.payload)
        updated = _apply_reviews(parsed, payload)
        service.replace_draft(session, deal, updated)
        from backend.evaluator.approval import approval_blockers

        return {
            "version": version,
            "formula": updated.model_dump(mode="json", by_alias=True),
            "blockers": [blocker.as_dict() for blocker in approval_blockers(updated)],
        }
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


def _apply_reviews(version: FormulaVersion, payload: ReviewRequest) -> FormulaVersion:
    """Apply decisions to a copy of the draft, by component key or covenant id."""
    draft = version.model_copy(deep=True)
    by_key = {component.key: component for component in draft.ebitda.components}
    by_covenant = {covenant.id: covenant for covenant in draft.covenants}
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    unknown: list[str] = []

    for decision in payload.decisions:
        review = {
            "decision": decision.decision,
            "note": decision.note,
            "reviewer": payload.reviewer,
            "reviewed_at": now.isoformat(),
        }
        component = by_key.get(decision.target)
        if component is not None:
            if decision.item is not None:
                component.item = decision.item  # type: ignore[assignment]
            if decision.sign is not None:
                component.sign = decision.sign  # type: ignore[assignment]
            if decision.category is not None:
                component.category = decision.category  # type: ignore[assignment]
            if decision.cap_pool is not None:
                component.cap_pool = decision.cap_pool or None
            component.review = Review.model_validate(review)
            continue
        covenant = by_covenant.get(decision.target)
        if covenant is not None:
            covenant.review = Review.model_validate(review)
            continue
        unknown.append(decision.target)

    if unknown:
        raise ServiceError("no such component or covenant: " + ", ".join(unknown))
    # Re-validate so an edited item cannot break a rule the schema enforces.
    return FormulaVersion.model_validate(draft.model_dump(mode="json", by_alias=True))


@app.post("/deals/{deal_id}/formula/{version}/approve")
def approve(
    deal_id: str,
    version: int,
    payload: ApproveRequest,
    session: Session = Depends(get_session),
    context: Context = Depends(get_context),
) -> dict[str, Any]:
    try:
        deal = service.get_deal(session, deal_id)
        row = service.approve_version(session, deal, version, reviewer=payload.reviewer)
        parsed = FormulaVersion.model_validate(row.payload)
        records = service.sync_mappings(session, context, deal, parsed)
        return {
            "version": row.version,
            "status": row.status,
            "approved_by": payload.reviewer,
            "mappings": [record.model_dump(mode="json") for record in records.values()],
        }
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


@app.post("/deals/{deal_id}/formula/{version}/new-draft", status_code=201)
def new_draft(
    deal_id: str, version: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        deal = service.get_deal(session, deal_id)
        row = service.start_new_draft(session, deal, version)
        return {"version": row.version, "status": row.status, "formula": row.payload}
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


# -- mapping gate ------------------------------------------------------------


@app.get("/deals/{deal_id}/mappings")
def list_mappings(
    deal_id: str,
    session: Session = Depends(get_session),
    context: Context = Depends(get_context),
) -> dict[str, Any]:
    try:
        deal = service.get_deal(session, deal_id)
        row = service.approved_version_row(session, deal_id) or service.latest_version_row(
            session, deal_id
        )
        if row is None:
            raise Blocked("the deal has no formula yet")
        version = FormulaVersion.model_validate(row.payload)
        records = service.sync_mappings(session, context, deal, version)
        sources = context.sources(deal.cik)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc

    from backend.edgar.mapping import candidates_for

    return {
        "deal_id": deal_id,
        "formula_version": row.version,
        "records": [
            {
                **record.model_dump(mode="json"),
                "candidates": [
                    {"concept": concept, "reported": concept in sources.concepts}
                    for concept in candidates_for(item)
                ],
            }
            for item, record in records.items()
        ],
    }


@app.post("/deals/{deal_id}/mappings/{item}")
def decide_mapping(
    deal_id: str,
    item: str,
    payload: MappingDecision,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        deal = service.get_deal(session, deal_id)
        record = service.decide_mapping(
            session,
            deal,
            item,
            status=payload.status,
            rationale=payload.rationale,
            concept=payload.concept,
            analyst_value=payload.analyst_value,
            reviewer=payload.reviewer,
        )
        return record.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc


# -- runs --------------------------------------------------------------------


@app.get("/deals/{deal_id}/test-dates")
def test_dates(
    deal_id: str,
    session: Session = Depends(get_session),
    context: Context = Depends(get_context),
) -> dict[str, Any]:
    try:
        deal = service.get_deal(session, deal_id)
        dates = service.available_quarters(session, context, deal)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    return {"deal_id": deal_id, "test_dates": [date.isoformat() for date in dates]}


@app.post("/deals/{deal_id}/runs", status_code=201)
def create_run(
    deal_id: str,
    payload: RunRequest,
    session: Session = Depends(get_session),
    context: Context = Depends(get_context),
) -> dict[str, Any]:
    try:
        deal = service.get_deal(session, deal_id)
        band = Decimal(payload.tight_band) if payload.tight_band else DEFAULT_TIGHT_BAND
        row = service.execute_run(session, context, deal, payload.test_date, tight_band=band)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    return {"run_id": row.id, "output_hash": row.output_hash, "result": row.payload}


@app.get("/deals/{deal_id}/runs")
def list_runs(deal_id: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    try:
        service.get_deal(session, deal_id)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    return [
        {
            "run_id": row.id,
            "test_date": row.test_date,
            "formula_version": row.formula_version,
            "evaluator_version": row.evaluator_version,
            "output_hash": row.output_hash,
            "superseded": bool(row.superseded),
            "headline_verdict": row.payload.get("headline_verdict"),
            "created_at": row.created_at.isoformat(),
        }
        for row in service.list_runs(session, deal_id)
    ]


@app.get("/deals/{deal_id}/runs/{run_id}")
def read_run(
    deal_id: str, run_id: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        row = service.get_run(session, deal_id, run_id)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    return {
        "run_id": row.id,
        "test_date": row.test_date,
        "formula_version": row.formula_version,
        "output_hash": row.output_hash,
        "superseded": bool(row.superseded),
        "result": row.payload,
    }
