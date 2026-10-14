"""The quarterly loop: approved formula plus approved mappings, run on facts.

This is the only place the two halves of Headroom meet. The compile loop runs
once per agreement and ends at an approved formula version; this loop runs
every test quarter and needs nothing from the LLM, which is why a rerun is
cheap, repeatable and checkable.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from backend.edgar.client import EdgarClient
from backend.edgar.facts import Fact, parse_company_facts
from backend.edgar.mapping import (
    MappingRecord,
    duplicate_concept_blockers,
    mapping_coverage,
    propose,
    required_items,
)
from backend.edgar.recurrence import (
    DEFAULT_MIN_YEARS,
    DEFAULT_WINDOW_YEARS,
    examine_items,
)
from backend.edgar.ttm import available_test_dates, build_period_inputs
from backend.evaluator.approval import Blocker, approval_blockers
from backend.evaluator.covenant import DEFAULT_TIGHT_BAND
from backend.evaluator.run import RunResult, evaluate_run
from backend.evaluator.schema import FormulaVersion
from backend.evaluator.vocabulary import PROMOTABLE_CATEGORY


@dataclass
class DealSources:
    """Everything fetched for one deal, cached in memory for a request."""

    cik: str
    facts_by_concept: dict[str, list[Fact]]
    entity_name: str | None = None

    @property
    def concepts(self) -> set[str]:
        return set(self.facts_by_concept)


def load_sources(cik: str, *, client: EdgarClient | None = None) -> DealSources:
    """One companyfacts call, parsed into facts with provenance."""
    client = client or EdgarClient()
    payload = client.company_facts(cik)
    return DealSources(
        cik=cik,
        facts_by_concept=parse_company_facts(payload),
        entity_name=payload.get("entityName"),
    )


def propose_mappings(
    version: FormulaVersion,
    sources: DealSources,
    existing: dict[str, MappingRecord] | None = None,
) -> dict[str, MappingRecord]:
    """A ``review_required`` record for every item the formula needs.

    Records the analyst has already decided are kept as they are; a new item
    introduced by a formula edit gets a fresh proposal, so an edit never
    silently inherits an approval it was not given.
    """
    kept = dict(existing or {})
    records: dict[str, MappingRecord] = {}
    for item in required_items(version):
        if item in kept:
            records[item] = kept[item]
        else:
            records[item] = propose(item, available=sources.concepts)
    return records


def test_dates_for(version: FormulaVersion, sources: DealSources) -> list[dt.date]:
    """Quarter ends a run could actually be built for."""
    del version
    return available_test_dates(sources.facts_by_concept)


def promotable_items(version: FormulaVersion) -> list[str]:
    """Items on a component the filings could promote to aggressive_recurring.

    Only the promotable category is tested. Asking whether depreciation recurs
    would be a waste of a question, and asking whether an excluded clause
    recurs would report evidence about a charge that never enters a result.
    """
    found: list[str] = []
    for component in version.ebitda.components:
        if component.excluded or component.category != PROMOTABLE_CATEGORY:
            continue
        if component.item in ("unmapped", "unsupported"):
            continue
        if component.item not in found:
            found.append(component.item)
    return found


def recurrence_findings(
    version: FormulaVersion,
    sources: DealSources,
    records: dict[str, MappingRecord],
    test_date: dt.date,
    *,
    basis: str | None = None,
    min_years: int = DEFAULT_MIN_YEARS,
    window_years: int = DEFAULT_WINDOW_YEARS,
) -> dict[str, dict]:
    """Test every promotable item for recurrence, on the run's own basis."""
    items = {
        item: (records[item].concept if item in records else None)
        for item in promotable_items(version)
    }
    findings = examine_items(
        items=items,
        facts_by_concept=sources.facts_by_concept,
        test_date=test_date,
        min_years=min_years,
        window_years=window_years,
        basis=basis,  # type: ignore[arg-type]
    )
    return {item: finding.as_dict() for item, finding in findings.items()}


def run_quarter(
    version: FormulaVersion,
    sources: DealSources,
    records: dict[str, MappingRecord],
    test_date: dt.date,
    *,
    tight_band: Decimal = DEFAULT_TIGHT_BAND,
    evaluator_version: str | None = None,
    require_approved: bool = True,
    min_years: int = DEFAULT_MIN_YEARS,
    window_years: int = DEFAULT_WINDOW_YEARS,
) -> RunResult:
    """Build the inputs for one quarter and evaluate every covenant.

    Recurrence is tested after the basis is chosen and on that basis, so the
    years behind a promotion are the same vintage of the filer's figures as the
    TTM window it is applied to.
    """
    items = required_items(version)
    inputs = build_period_inputs(
        deal_id=version.deal_id,
        test_date=test_date,
        records=records,
        facts_by_concept=sources.facts_by_concept,
        items=items,
    )
    mapping_versions = {
        item: records[item].mapping_version for item in items if item in records
    }
    findings = recurrence_findings(
        version,
        sources,
        records,
        test_date,
        basis=inputs.basis,
        min_years=min_years,
        window_years=window_years,
    )
    kwargs = {}
    if evaluator_version is not None:
        kwargs["evaluator_version"] = evaluator_version
    return evaluate_run(
        version,
        inputs,
        tight_band=tight_band,
        require_approved=require_approved,
        mapping_versions=mapping_versions,
        recurrence=findings,  # type: ignore[arg-type]
        **kwargs,
    )


def coverage(version: FormulaVersion, records: dict[str, MappingRecord]) -> tuple[int, int]:
    """Verified mappings over required mappings, reported not assumed."""
    return mapping_coverage(records, required_items(version))


def all_blockers(
    version: FormulaVersion, records: dict[str, MappingRecord] | None = None
) -> list[Blocker]:
    """Everything standing between ``version`` and an approved formula.

    Both gates report into one list, because a reviewer wants one answer to
    "can this be approved yet". The formula gate checks the components; the
    mapping gate adds the conflicts only the records can show, such as two
    items pointing at one reported concept.
    """
    found = approval_blockers(version)
    if records:
        found = found + duplicate_concept_blockers(records, required_items(version))
    return found


def blockers(
    version: FormulaVersion, records: dict[str, MappingRecord] | None = None
) -> list[dict[str, str]]:
    return [blocker.as_dict() for blocker in all_blockers(version, records)]


# -- golden set loading ------------------------------------------------------


def load_formula(path: str | Path) -> FormulaVersion:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return FormulaVersion.model_validate(payload)


def load_mappings(path: str | Path) -> dict[str, MappingRecord]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    records: dict[str, MappingRecord] = {}
    for row in payload.get("records", []):
        record = MappingRecord.model_validate(row)
        records[record.formula_item] = record
    return records


def load_golden(folder: str | Path) -> tuple[dict, FormulaVersion, dict[str, MappingRecord]]:
    """A golden deal: its metadata, its hand-written formula, its mappings."""
    base = Path(folder)
    deal = json.loads((base / "deal.json").read_text(encoding="utf-8"))
    version = load_formula(base / "formula.json")
    records = load_mappings(base / "mappings.json")
    return deal, version, records


def write_inputs_snapshot(path: str | Path, run: RunResult) -> None:
    """Record the resolved inputs of a run, with provenance, for the golden set.

    The reporting basis is part of the snapshot's identity, not a note about
    it: the same four quarter ends resolve to different figures on the two
    bases, so a snapshot that did not name its basis could not be replayed
    and checked against the filings it came from.
    """
    payload = {
        "deal_id": run.deal_id,
        "test_date": run.test_date.isoformat(),
        "quarters": run.inputs.quarters,
        "basis": run.inputs.basis,
        "basis_note": run.inputs.basis_note,
        # Recurrence is derived from the filings exactly as the TTM window is,
        # so it belongs in the snapshot: replaying the snapshot has to
        # reproduce the promotion as well as the amounts, or the replayed
        # scenarios are not the scenarios that were run.
        "recurrence": {row["item"]: row for row in run.recurrence},
        "items": {
            item: resolved.model_dump(mode="json")
            for item, resolved in sorted(run.inputs.items.items())
        },
    }
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def concept_summary(sources: DealSources, concepts: Sequence[str]) -> dict[str, int]:
    return {concept: len(sources.facts_by_concept.get(concept, [])) for concept in concepts}
