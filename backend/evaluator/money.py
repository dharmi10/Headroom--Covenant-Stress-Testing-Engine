"""Exact arithmetic helpers.

Every amount in Headroom is a :class:`~decimal.Decimal` parsed from a string.
Floats never appear: a threshold of ``4.75`` has to compare exactly, and
``0.1 + 0.2 != 0.3`` is not an acceptable property for a covenant test.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, localcontext
from typing import Iterator

#: Working precision for divisions. Verdicts never depend on it (they are
#: decided by exact cross-multiplication); it only bounds the precision of
#: ratios and cushions that get displayed.
PRECISION = 40

ZERO = Decimal(0)
ONE = Decimal(1)

#: Quantums used when a number is rendered, never when it is compared.
RATIO_Q = Decimal("0.01")
PERCENT_Q = Decimal("0.0001")
MONEY_Q = Decimal("0.01")


@contextmanager
def exact() -> Iterator[None]:
    """Run a block at :data:`PRECISION` significant digits."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        yield


def to_decimal(value: str | int | Decimal, *, field: str = "amount") -> Decimal:
    """Parse ``value`` into a ``Decimal``, rejecting floats and junk.

    Floats are rejected rather than converted because accepting them would
    silently import the imprecision this module exists to avoid.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"{field} must be a string or integer, not {type(value).__name__}")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} is not a decimal number: {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite: {value!r}")
    return parsed


def dec_str(value: Decimal) -> str:
    """Canonical string form of a decimal, for hashing and JSON."""
    normalised = value.normalize()
    if normalised == 0:
        return "0"
    sign, digits, exponent = normalised.as_tuple()
    if isinstance(exponent, int) and exponent > 0:
        normalised = normalised.quantize(Decimal(1))
    return format(normalised, "f")


def div(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Divide at working precision, or ``None`` if the denominator is zero."""
    if denominator == 0:
        return None
    with exact():
        return numerator / denominator


def quantize_ratio(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(RATIO_Q)


def quantize_percent(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(PERCENT_Q)


def quantize_money(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(MONEY_Q)
