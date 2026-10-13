"""The JSON schema the model must fill in.

Written out by hand rather than generated from the Pydantic models. A
hand-written schema has no ``$ref`` indirection, states every enum inline where
the model reads it, and lets the field descriptions carry the drafting rules
that matter most - which is where they are most likely to be followed. The
Pydantic models remain the authority: whatever comes back is validated against
them, and a draft that disagrees with them is rejected.
"""

from __future__ import annotations

from typing import Any

from backend.evaluator.vocabulary import ALL_ITEMS, CATEGORIES

ITEM_ENUM = list(ALL_ITEMS)
CATEGORY_ENUM = list(CATEGORIES)

_SPAN: dict[str, Any] = {
    "type": "object",
    "description": (
        "Where this came from in the agreement text. start and end are "
        "character offsets into the text exactly as supplied, and quote must be "
        "the text between them, copied verbatim."
    ),
    "properties": {
        "start": {"type": "integer", "description": "Character offset of the first character."},
        "end": {"type": "integer", "description": "Character offset just past the last character."},
        "quote": {
            "type": "string",
            "description": (
                "The exact text at [start:end]. Keep it short: the clause phrase "
                "that justifies this entry, not the whole paragraph."
            ),
        },
    },
    "required": ["start", "end", "quote"],
    "additionalProperties": False,
}

EBITDA_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "base": {
            "type": "object",
            "description": "The term the definition starts from, before any adjustment.",
            "properties": {
                "item": {"type": "string", "enum": ITEM_ENUM},
                "clause": {"type": "string", "description": "Clause label, e.g. (a)."},
                "span": _SPAN,
                "reason": {
                    "type": "string",
                    "description": "Required only when item is unmapped or unsupported.",
                },
            },
            "required": ["item", "clause", "span", "reason"],
            "additionalProperties": False,
        },
        "components": {
            "type": "array",
            "description": (
                "One entry per enumerated clause of the definition, in the order "
                "they appear, including the deductions. Do not merge two clauses "
                "into one entry and do not skip a clause: a clause with no "
                "vocabulary item is recorded as unmapped, and a clause the format "
                "cannot express is recorded as unsupported."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "clause": {
                        "type": "string",
                        "description": "The clause label as the agreement writes it, e.g. (b)(iv).",
                    },
                    "item": {
                        "type": "string",
                        "enum": ITEM_ENUM,
                        "description": (
                            "The vocabulary item this clause adds or deducts. Use "
                            "unmapped when the clause names something no item "
                            "covers. Use unsupported when the clause is a construct "
                            "this format cannot express, such as a cap that depends "
                            "on another cap, a time limit on when savings must be "
                            "realised, or an add-back conditional on a ratio test."
                        ),
                    },
                    "sign": {
                        "type": "string",
                        "enum": ["+", "-"],
                        "description": "+ for an add-back, - for a deduction.",
                    },
                    "category": {
                        "type": "string",
                        "enum": CATEGORY_ENUM,
                        "description": (
                            "standard for interest, tax and depreciation and "
                            "amortisation; non_cash for charges with no cash cost "
                            "such as stock compensation or impairment; one_time for "
                            "charges the clause calls unusual, non-recurring, "
                            "restructuring or transaction related; pro_forma for "
                            "projected or run-rate amounts that have not happened yet."
                        ),
                    },
                    "cap_pool": {
                        "type": "string",
                        "description": (
                            "Name of the entry in cap_pools that limits this clause, "
                            "or an empty string when the clause is uncapped. Clauses "
                            "that share one aggregate cap must name the same pool."
                        ),
                    },
                    "span": _SPAN,
                    "reason": {
                        "type": "string",
                        "description": (
                            "Required when item is unmapped or unsupported: say what "
                            "the clause covers and why no item fits. Empty otherwise."
                        ),
                    },
                },
                "required": ["clause", "item", "sign", "category", "cap_pool", "span", "reason"],
                "additionalProperties": False,
            },
        },
        "cap_pools": {
            "type": "array",
            "description": (
                "One entry per aggregate cap the definition imposes. A cap that "
                "applies to several clauses is one pool named by all of them."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short identifier used by the components, e.g. clause_x.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["fixed", "percentage", "greater_of"],
                        "description": (
                            "fixed for a stated money amount, percentage for a share "
                            "of EBITDA, greater_of when the clause allows the greater "
                            "of a money amount and a percentage."
                        ),
                    },
                    "fixed_amount": {
                        "type": "string",
                        "description": (
                            "The money cap in full units as digits only, no currency "
                            "symbol or separators, e.g. 25000000. Empty for a pure "
                            "percentage cap."
                        ),
                    },
                    "pct": {
                        "type": "string",
                        "description": (
                            "The percentage as a decimal fraction, so 15% is 0.15. "
                            "Empty for a pure fixed cap."
                        ),
                    },
                    "basis": {
                        "type": "string",
                        "enum": ["before_pool", "after_pool", ""],
                        "description": (
                            "before_pool when the percentage is measured on EBITDA "
                            "calculated before or without giving effect to these "
                            "add-backs; after_pool when it is measured after giving "
                            "effect to them. Empty for a fixed cap."
                        ),
                    },
                    "label": {"type": "string", "description": "Human label for the cap."},
                    "span": _SPAN,
                },
                "required": ["name", "kind", "fixed_amount", "pct", "basis", "label", "span"],
                "additionalProperties": False,
            },
        },
        "notes": {
            "type": "string",
            "description": "Anything about the definition a reviewer should know.",
        },
    },
    "required": ["base", "components", "cap_pools", "notes"],
    "additionalProperties": False,
}

COVENANT_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {
            "type": "string",
            "description": "Short snake_case identifier, e.g. max_total_net_leverage.",
        },
        "name": {"type": "string", "description": "The name the agreement gives the ratio."},
        "type": {
            "type": "string",
            "enum": ["max_ratio", "min_ratio"],
            "description": (
                "max_ratio for a leverage test the borrower must stay below, "
                "min_ratio for a coverage test it must stay above."
            ),
        },
        "items": {
            "type": "array",
            "description": (
                "The vocabulary items that make up the side of the ratio that is "
                "not covenant EBITDA: the debt items for a leverage test, the "
                "interest item for a coverage test."
            ),
            "items": {"type": "string", "enum": ITEM_ENUM},
        },
        "items_span": _SPAN,
        "net_of_cash": {
            "type": "object",
            "description": "Whether cash is netted against the debt, and any cap on it.",
            "properties": {
                "enabled": {"type": "boolean"},
                "cap": {
                    "type": "string",
                    "description": (
                        "The maximum cash that may be netted, digits only, or empty "
                        "when the netting is uncapped."
                    ),
                },
                "span": _SPAN,
            },
            "required": ["enabled", "cap", "span"],
            "additionalProperties": False,
        },
        "schedule": {
            "type": "array",
            "description": (
                "The threshold and the date it takes effect, one entry per step. A "
                "flat threshold is a single entry dated from when the covenant "
                "first applies."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "from": {
                        "type": "string",
                        "description": "Effective date as YYYY-MM-DD.",
                    },
                    "threshold": {
                        "type": "string",
                        "description": "The ratio as a decimal, e.g. 4.50.",
                    },
                },
                "required": ["from", "threshold"],
                "additionalProperties": False,
            },
        },
        "span": _SPAN,
        "reason": {
            "type": "string",
            "description": (
                "Anything in the covenant this format cannot express, such as a "
                "threshold that moves on a condition rather than a date."
            ),
        },
    },
    "required": [
        "id",
        "name",
        "type",
        "items",
        "items_span",
        "net_of_cash",
        "schedule",
        "span",
        "reason",
    ],
    "additionalProperties": False,
}

EBITDA_TOOL = {
    "name": "record_ebitda_formula",
    "description": (
        "Record the covenant EBITDA definition as a structured formula. Call this "
        "exactly once, with one component per enumerated clause."
    ),
    "strict": True,
    "input_schema": EBITDA_TOOL_SCHEMA,
}

COVENANT_TOOL = {
    "name": "record_covenant",
    "description": (
        "Record one financial maintenance covenant as a structured test. Call this "
        "exactly once for the covenant named in the request."
    ),
    "strict": True,
    "input_schema": COVENANT_TOOL_SCHEMA,
}
