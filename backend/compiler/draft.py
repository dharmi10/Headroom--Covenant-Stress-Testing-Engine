"""The compile loop: locate, resolve, draft, verify.

The LLM does exactly one job here - turn clause text into a typed formula. It
is called once per target, with at most one retry carrying the validation
errors, and every call records the model id, the prompt version and the attempt
number. Everything around it is deterministic: the sections are located by
regular expression, the references are resolved by a graph, the result is
validated against the schema, and every span is checked against the agreement
text before a human ever sees it.

**On temperature.** The PRD asks for temperature 0. Current Claude models
reject the sampling parameters outright, so the determinism Headroom actually
needs is not bought from the sampler: it comes from validating the output
against a closed schema, verifying every span against the source, and requiring
a human to approve each component. A drafted formula is a proposal either way.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.agreement.definitions import DefinitionGraph, build_graph
from backend.agreement.locate import (
    LocationError,
    covenant_mentions,
    find_definition,
    locate_ebitda_definition,
    locate_financial_covenants,
)
from backend.agreement.normalise import text_hash
from backend.compiler.prompt import (
    PROMPT_VERSION,
    SYSTEM,
    covenant_request,
    ebitda_request,
    retry_request,
)
from backend.compiler.schema_json import COVENANT_TOOL, EBITDA_TOOL
from backend.compiler.spans import verify_covenant, verify_formula
from backend.evaluator.schema import Covenant, EbitdaFormula, FormulaVersion

DEFAULT_MODEL = "claude-opus-5"
MAX_ATTEMPTS = 2  # the first call plus at most one retry carrying the errors
MAX_TOKENS = 16_000
EFFORT = "high"

#: How much of a long excerpt is sent. The definitions graph keeps this small
#: by design; the limit is a backstop against a pathological agreement.
MAX_EXCERPT_CHARS = 60_000


class CompileError(RuntimeError):
    """The compile could not produce a validated draft."""


class MessagesClient(Protocol):
    """The slice of the Anthropic client this module uses."""

    def create(self, **kwargs: Any) -> Any: ...  # pragma: no cover - protocol


@dataclass
class CallLog:
    """What one draft call did, for the audit trail and the metrics."""

    target: str
    model: str
    prompt_version: str
    attempts: int
    errors: list[list[str]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "attempts": self.attempts,
            "errors": self.errors,
            "usage": self.usage,
        }


# -- what the model is allowed to return ------------------------------------


STRICT = ConfigDict(extra="forbid")


class DraftSpan(BaseModel):
    model_config = STRICT

    start: int
    end: int
    quote: str


class DraftBase(BaseModel):
    model_config = STRICT

    item: str
    clause: str = ""
    span: DraftSpan
    reason: str = ""


class DraftComponent(BaseModel):
    model_config = STRICT

    clause: str
    item: str
    sign: str
    category: str
    cap_pool: str = ""
    span: DraftSpan
    reason: str = ""


class DraftCapPool(BaseModel):
    model_config = STRICT

    name: str
    kind: str
    fixed_amount: str = ""
    pct: str = ""
    basis: str = ""
    label: str = ""
    span: DraftSpan


class DraftEbitda(BaseModel):
    model_config = STRICT

    base: DraftBase
    components: list[DraftComponent] = Field(min_length=1)
    cap_pools: list[DraftCapPool] = Field(default_factory=list)
    notes: str = ""


class DraftNetOfCash(BaseModel):
    model_config = STRICT

    enabled: bool
    cap: str = ""
    span: DraftSpan


class DraftScheduleStep(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    threshold: str


class DraftCovenant(BaseModel):
    model_config = STRICT

    id: str
    name: str = ""
    type: str
    items: list[str] = Field(min_length=1)
    items_span: DraftSpan
    net_of_cash: DraftNetOfCash
    schedule: list[DraftScheduleStep] = Field(min_length=1)
    span: DraftSpan
    reason: str = ""


# -- translation into the formula language -----------------------------------


def _span(span: DraftSpan) -> dict[str, Any]:
    return {"start": span.start, "end": span.end, "quote": span.quote}


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def to_ebitda_formula(
    draft: DraftEbitda,
    *,
    deal_id: str,
    source_hash: str,
    model: str,
    attempts: int,
    version: int = 1,
) -> EbitdaFormula:
    """Translate a draft into the formula language, or raise ValidationError."""
    pools: dict[str, Any] = {}
    for pool in draft.cap_pools:
        body: dict[str, Any] = {"kind": pool.kind, "span": _span(pool.span)}
        if _blank(pool.fixed_amount):
            body["fixed_amount"] = pool.fixed_amount.strip()
        if _blank(pool.pct):
            body["pct"] = pool.pct.strip()
        if _blank(pool.basis):
            body["basis"] = pool.basis.strip()
        if _blank(pool.label):
            body["label"] = pool.label.strip()
        pools[pool.name] = body

    components = [
        {
            "item": component.item,
            "sign": component.sign,
            "category": component.category,
            "cap_pool": _blank(component.cap_pool),
            "clause": _blank(component.clause),
            "reason": _blank(component.reason),
            "span": _span(component.span),
        }
        for component in draft.components
    ]

    return EbitdaFormula.model_validate(
        {
            "formula_id": deal_id,
            "version": version,
            "status": "draft",
            "source_hash": source_hash,
            "drafted_with": {
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "attempts": attempts,
            },
            "metric": "consolidated_ebitda",
            "base": {
                "item": draft.base.item,
                "clause": _blank(draft.base.clause),
                "reason": _blank(draft.base.reason),
                "span": _span(draft.base.span),
            },
            "components": components,
            "cap_pools": pools,
        }
    )


def to_covenant(draft: DraftCovenant) -> Covenant:
    side: dict[str, Any] = {"items": draft.items, "span": _span(draft.items_span)}
    if draft.net_of_cash.enabled:
        netting: dict[str, Any] = {"enabled": True, "span": _span(draft.net_of_cash.span)}
        if _blank(draft.net_of_cash.cap):
            netting["cap"] = draft.net_of_cash.cap.strip()
        side["net_of_cash"] = netting

    if draft.type == "max_ratio":
        numerator: Any = side
        denominator: Any = "consolidated_ebitda"
    else:
        numerator = "consolidated_ebitda"
        denominator = side

    return Covenant.model_validate(
        {
            "id": draft.id,
            "name": _blank(draft.name),
            "type": draft.type,
            "numerator": numerator,
            "denominator": denominator,
            "schedule": [
                {"from": step.from_, "threshold": step.threshold} for step in draft.schedule
            ],
            "test": {"frequency": "quarterly", "period": "ttm"},
            "span": _span(draft.span),
            "reason": _blank(draft.reason),
        }
    )


# -- the call ----------------------------------------------------------------


def _tool_input(response: Any, tool_name: str) -> dict[str, Any]:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            raw = block.input
            if isinstance(raw, str):
                return json.loads(raw)
            return dict(raw)
    stop = getattr(response, "stop_reason", None)
    if stop == "refusal":
        raise CompileError("the model declined to draft this target")
    raise CompileError("the model did not call " + tool_name)


def _errors_of(exc: ValidationError) -> list[str]:
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        messages.append((location or "(root)") + ": " + error["msg"])
    return messages


def _draft_with_validation(
    client: Any,
    *,
    tool: dict[str, Any],
    request: str,
    model: str,
    target: str,
    build,
    verify,
):
    """Call, validate, verify spans; retry once with whatever failed."""
    log = CallLog(target=target, model=model, prompt_version=PROMPT_VERSION, attempts=0)
    messages: list[dict[str, Any]] = [{"role": "user", "content": request}]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        log.attempts = attempt
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=messages,
            tools=[tool],
            output_config={"effort": EFFORT},
        )
        usage = getattr(response, "usage", None)
        if usage is not None:
            log.usage = {
                "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            }

        errors: list[str] = []
        built = None
        try:
            payload = _tool_input(response, tool["name"])
        except CompileError as exc:
            errors = [str(exc)]
        else:
            try:
                built = build(payload, log.attempts)
            except ValidationError as exc:
                errors = _errors_of(exc)
            except (ValueError, KeyError, TypeError) as exc:
                errors = [str(exc)]

        if built is not None:
            failures = verify(built)
            if not failures:
                return built, log
            errors = [failure.target + ": " + failure.reason for failure in failures]

        log.errors.append(errors)
        if attempt == MAX_ATTEMPTS:
            raise CompileError(target + " draft rejected: " + "; ".join(errors[:5]))
        messages = [
            {"role": "user", "content": request},
            {"role": "user", "content": retry_request(errors)},
        ]

    raise CompileError(target + " draft failed")  # pragma: no cover - loop always returns


# -- public entry points -----------------------------------------------------


@dataclass
class CompileResult:
    """A drafted, span-verified formula version, awaiting human review."""

    version: FormulaVersion
    graph: DefinitionGraph
    logs: list[CallLog]
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version.model_dump(mode="json", by_alias=True),
            "unresolved_references": self.graph.unresolved,
            "calls": [log.as_dict() for log in self.logs],
            "notes": self.notes,
        }


def compile_agreement(
    text: str,
    *,
    deal_id: str,
    client: Any,
    model: str | None = None,
    ebitda_term: str | None = None,
) -> CompileResult:
    """Draft the EBITDA formula and every financial covenant in ``text``."""
    model = model or os.environ.get("HEADROOM_MODEL", DEFAULT_MODEL)
    source_hash = text_hash(text)

    definition = (
        find_definition(text, ebitda_term) if ebitda_term else locate_ebitda_definition(text)
    )
    graph = build_graph(text, definition.label)
    references = graph.prompt_text()

    logs: list[CallLog] = []

    formula, log = _draft_with_validation(
        client,
        tool=EBITDA_TOOL,
        request=ebitda_request(
            definition.text[:MAX_EXCERPT_CHARS], definition.start, references
        ),
        model=model,
        target="consolidated_ebitda",
        build=lambda payload, attempts: to_ebitda_formula(
            DraftEbitda.model_validate(payload),
            deal_id=deal_id,
            source_hash=source_hash,
            model=model,
            attempts=attempts,
        ),
        verify=lambda built: verify_formula(built, text),
    )
    logs.append(log)

    covenants = _draft_covenants(text, client, model, graph, logs)
    if not covenants:
        raise CompileError("no financial covenant could be drafted")

    version = FormulaVersion.model_validate(
        {
            "deal_id": deal_id,
            "version": 1,
            "status": "draft",
            "source_hash": source_hash,
            "ebitda": formula.model_dump(mode="json"),
            "covenants": [covenant.model_dump(mode="json", by_alias=True) for covenant in covenants],
            "definitions": {
                term: node.model_dump(mode="json") for term, node in graph.nodes.items()
            },
            "created_at": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(),
        }
    )
    return CompileResult(version=version, graph=graph, logs=logs)


def _draft_covenants(
    text: str,
    client: Any,
    model: str,
    graph: DefinitionGraph,
    logs: list[CallLog],
) -> list[Covenant]:
    section = locate_financial_covenants(text)
    seen: set[str] = set()
    covenants: list[Covenant] = []
    for ratio, _ in covenant_mentions(section.text):
        if ratio in seen:
            continue
        seen.add(ratio)
        try:
            ratio_definition = find_definition(text, ratio)
            ratio_text, ratio_offset = ratio_definition.text, ratio_definition.start
            ratio_graph = build_graph(text, ratio, max_depth=1)
            references = ratio_graph.prompt_text()
        except LocationError:
            ratio_text, ratio_offset, references = "", 0, graph.prompt_text()

        request = covenant_request(
            ratio=ratio,
            section=section.text[:MAX_EXCERPT_CHARS],
            offset=section.start,
            ratio_definition=ratio_text[:MAX_EXCERPT_CHARS],
            ratio_offset=ratio_offset,
            references=references,
        )
        covenant, log = _draft_with_validation(
            client,
            tool=COVENANT_TOOL,
            request=request,
            model=model,
            target=ratio,
            build=lambda payload, _attempts: to_covenant(DraftCovenant.model_validate(payload)),
            verify=lambda built: verify_covenant(built, text),
        )
        logs.append(log)
        covenants.append(covenant)
    return covenants


def anthropic_client() -> Any:
    """The Anthropic client, or a clear error about credentials."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise CompileError("the anthropic package is not installed") from exc
    try:
        return anthropic.Anthropic()
    except Exception as exc:  # noqa: BLE001 - the SDK raises its own types
        raise CompileError(
            "no Anthropic credentials found: set ANTHROPIC_API_KEY or run 'ant auth login'"
        ) from exc


def save_transcript(path: str | Path, result: CompileResult) -> None:
    """Record a compile so it can be reviewed and replayed offline."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(result.as_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_transcript(path: str | Path) -> FormulaVersion:
    """Replay a recorded compile, so a demo needs no API call."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return FormulaVersion.model_validate(payload["version"])
