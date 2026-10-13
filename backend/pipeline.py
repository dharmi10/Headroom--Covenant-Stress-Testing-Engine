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
    mapping_coverage,
    propose,
    required_items,
)
from backend.edgar.ttm import available_test_dates, build_period_inputs
from backend.evaluator.approval import approval_blockers
from backend.evaluator.covenant import DEFAULT_TIGHT_BAND
from backend.evaluator.run import RunResult, evaluate_run
from backend.evaluator.schema import FormulaVersion


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


def run_quarter(
    version: FormulaVersion,
    sources: DealSources,
    records: dict[str, MappingRecord],
    test_date: dt.date,
    *,
    tight_band: Decimal = DEFAULT_TIGHT_BAND,
    evaluator_version: str | None = None,
    require_approved: bool = True,
) -> RunResult:
    """Build the inputs for one quarter and evaluate every covenant."""
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
    kwargs = {}
    if evaluator_version is not None:
        kwargs["evaluator_version"] = evaluator_version
    return evaluate_run(
        version,
        inputs,
        tight_band=tight_band,
        require_approved=require_approved,
        mapping_versions=mapping_versions,
        **kwargs,
    )


def coverage(version: FormulaVersion, records: dict[str, MappingRecord]) -> tuple[int, int]:
    """Verified mappings over required mappings, reported not assumed."""
    return mapping_coverage(records, required_items(version))


def blockers(version: FormulaVersion) -> list[dict[str, str]]:
    return [blocker.as_dict() for blocker in approval_blockers(version)]


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
    """Record the resolved inputs of a run, with provenance, for the golden set."""
    payload = {
        "deal_id": run.deal_id,
        "test_date": run.test_date.isoformat(),
        "quarters": run.inputs.quarters,
        "items": {
            item: resolved.model_dump(mode="json")
            for item, resolved in sorted(run.inputs.items.items())
        },
    }
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def concept_summary(sources: DealSources, concepts: Sequence[str]) -> dict[str, int]:
    return {concept: len(sources.facts_by_concept.get(concept, [])) for concept in concepts}
