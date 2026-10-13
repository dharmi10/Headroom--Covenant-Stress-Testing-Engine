"""The cap engine.

A cap pool is evaluated inside each scenario and never carried over from
another one, because removing an item from a shared pool frees room for the
items that remain. For a pool, let ``E`` be the EBITDA contributed by every
other component included in that scenario, ``A`` the sum of the pool's items
included in that scenario, ``F`` a fixed amount and ``p`` a percentage:

================================  ===========================
cap kind                          cap ``C``
================================  ===========================
fixed                             ``F``
percentage, measured before pool  ``p x E``
percentage, measured after pool    ``p x E / (1 - p)``
greater_of                        ``max(F, percentage cap)``
================================  ===========================

The after-pool form solves ``x <= p(E + x)`` for ``x``. The allowed amount is
``min(A, max(C, 0))``, so a negative ``E`` gives a percentage cap of zero
rather than a negative allowance.

**What ``E`` means when there are several pools.** A ``before_pool`` percentage
is measured "prior to giving effect to all such add-backs", so ``E`` excludes
every pooled allowance, not just this pool's. An ``after_pool`` percentage is
measured on EBITDA including its own pool, so its ``E`` includes the allowances
of the other pools. Two after-pool pools would depend on each other, which the
schema rejects as unsupported; with at most one, the order of evaluation is
fixed and the result is independent of how components happen to be listed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, NamedTuple

from backend.evaluator.money import ONE, ZERO, exact
from backend.evaluator.schema import CapPool, Component


class PoolAttribution(NamedTuple):
    """How much of a capped pool's allowance one component accounts for."""

    key: str
    item: str
    requested: Decimal
    allowed: Decimal


class PoolResult(NamedTuple):
    """The full working of one cap pool inside one scenario."""

    name: str
    kind: str
    basis: str | None
    e: Decimal
    a: Decimal
    cap: Decimal
    allowed: Decimal
    binding: bool
    attribution: tuple[PoolAttribution, ...]

    def as_dict(self) -> dict[str, object]:
        from backend.evaluator.money import dec_str

        return {
            "pool": self.name,
            "kind": self.kind,
            "basis": self.basis,
            "e_before_pool": dec_str(self.e),
            "a_requested": dec_str(self.a),
            "cap": dec_str(self.cap),
            "allowed": dec_str(self.allowed),
            "binding": self.binding,
            "attribution": [
                {
                    "component": part.key,
                    "item": part.item,
                    "requested": dec_str(part.requested),
                    "allowed": dec_str(part.allowed),
                }
                for part in self.attribution
            ],
        }


def cap_amount(pool: CapPool, e: Decimal) -> Decimal:
    """The cap ``C`` for ``pool`` given the EBITDA base ``E``."""
    with exact():
        if pool.kind == "fixed":
            assert pool.fixed_amount is not None
            return pool.fixed_amount
        pct_cap = _percentage_cap(pool, e)
        if pool.kind == "percentage":
            return pct_cap
        assert pool.fixed_amount is not None
        return max(pool.fixed_amount, pct_cap)


def _percentage_cap(pool: CapPool, e: Decimal) -> Decimal:
    assert pool.pct is not None
    pct = pool.pct
    if pool.basis == "after_pool":
        # x <= p(E + x)  =>  x <= pE / (1 - p)
        return pct * e / (ONE - pct)
    return pct * e


def attribute_pro_rata(
    parts: Iterable[tuple[str, str, Decimal]],
    allowed: Decimal,
    requested_total: Decimal,
) -> tuple[PoolAttribution, ...]:
    """Split ``allowed`` across the pool's items pro rata by amount.

    This changes only the trace, never the EBITDA total, so the split has to
    sum exactly to ``allowed``. A third of an allowance has no exact decimal
    form, so each share is rounded to the allowance's own quantum (cents, or
    finer if the allowance is finer) and the residual lands on the largest
    requested item, with ties broken by component key so the result does not
    depend on the order the components were listed in.
    """
    items = list(parts)
    if not items:
        return ()
    if requested_total <= 0 or allowed >= requested_total:
        return tuple(
            PoolAttribution(key=key, item=item, requested=amount, allowed=amount)
            for key, item, amount in items
        )
    quantum = _quantum_of(allowed)
    shares: list[PoolAttribution] = []
    with exact():
        for key, item, amount in items:
            share = (allowed * amount / requested_total).quantize(quantum)
            shares.append(PoolAttribution(key=key, item=item, requested=amount, allowed=share))
        residual = allowed - sum((s.allowed for s in shares), ZERO)
    if residual != 0:
        target = max(range(len(shares)), key=lambda i: (shares[i].requested, shares[i].key))
        chosen = shares[target]
        shares[target] = chosen._replace(allowed=chosen.allowed + residual)
    return tuple(shares)


def _quantum_of(allowed: Decimal) -> Decimal:
    """Cents, or the allowance's own finer quantum if it has one."""
    exponent = allowed.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        return Decimal(1).scaleb(exponent)
    return Decimal("0.01")


def evaluate_pools(
    pools: dict[str, CapPool],
    included_by_pool: dict[str, list[tuple[Component, Decimal]]],
    e_base: Decimal,
) -> tuple[Decimal, dict[str, PoolResult]]:
    """Evaluate every pool for one scenario.

    ``e_base`` is EBITDA from the base term and every component outside a pool.
    Returns the total allowed across all pools and each pool's working.
    """
    results: dict[str, PoolResult] = {}
    before_names = sorted(n for n in pools if not pools[n].uses_after_pool)
    after_names = sorted(n for n in pools if pools[n].uses_after_pool)

    for name in before_names:
        results[name] = _evaluate_one(name, pools[name], included_by_pool.get(name, []), e_base)

    with exact():
        allowed_before = sum((results[n].allowed for n in before_names), ZERO)
    for name in after_names:
        e_for_after = e_base + allowed_before
        results[name] = _evaluate_one(
            name, pools[name], included_by_pool.get(name, []), e_for_after
        )

    with exact():
        total = sum((result.allowed for result in results.values()), ZERO)
    return total, results


def _evaluate_one(
    name: str,
    pool: CapPool,
    included: list[tuple[Component, Decimal]],
    e: Decimal,
) -> PoolResult:
    with exact():
        requested = sum((amount for _, amount in included), ZERO)
        cap = cap_amount(pool, e)
        effective_cap = max(cap, ZERO)
        allowed = min(requested, effective_cap) if requested > 0 else requested
    parts = [(component.key, component.item, amount) for component, amount in included]
    attribution = attribute_pro_rata(parts, allowed, requested)
    return PoolResult(
        name=name,
        kind=pool.kind,
        basis=pool.basis,
        e=e,
        a=requested,
        cap=cap,
        allowed=allowed,
        binding=requested > effective_cap,
        attribution=attribution,
    )
