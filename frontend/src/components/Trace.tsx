/* The calculation trace.
 *
 * Clicking any figure opens its working: the inputs, the arithmetic, and the
 * filing or clause each input came from. The drawer is the answer to "can I
 * verify this myself", so it shows the exact values the backend computed with,
 * not the rounded ones on the screen.
 */

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import type { CovenantResult, ItemInput, RunResult, ScenarioResult } from "../api";
import { asOf, exact, itemLabel, percent, ratio, reasonLabel, stateLabel } from "../format";
import { FactTable } from "./FactTable";

export interface TraceTarget {
  title: string;
  subtitle?: string;
  working: ReactNode;
  inputs?: string[];
  reasons?: { code: string; item: string | null; detail: string | null }[];
}

export function TraceValue({
  children,
  onOpen,
  title,
}: {
  children: ReactNode;
  onOpen: () => void;
  title?: string;
}) {
  return (
    <button type="button" className="trace-value" onClick={onOpen} title={title ?? "Show the working"}>
      {children}
    </button>
  );
}

export function TraceDrawer({
  target,
  run,
  onClose,
}: {
  target: TraceTarget | null;
  run: RunResult;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!target) return;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, onClose]);

  if (!target) return null;

  const inputs = (target.inputs ?? [])
    .map((item) => run.inputs.items[item])
    .filter((value): value is ItemInput => Boolean(value));

  return (
    <div
      className="drawer-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={target.title}>
        <div className="drawer-head">
          <div>
            <h2>{target.title}</h2>
            {target.subtitle ? <p className="small muted" style={{ margin: "2px 0 0" }}>{target.subtitle}</p> : null}
          </div>
          <button type="button" className="close" onClick={onClose} ref={closeRef}>
            Close
          </button>
        </div>
        <div className="drawer-body">
          <div className="working">{target.working}</div>

          {target.reasons && target.reasons.length > 0 ? (
            <div className="notice bad">
              <strong>Not computable.</strong>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                {target.reasons.map((reason, index) => (
                  <li key={index}>
                    {reasonLabel(reason.code)}
                    {reason.item ? " — " + itemLabel(reason.item) : ""}
                    {reason.detail ? ". " + reason.detail : ""}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {inputs.length > 0 ? (
            <>
              <h3 style={{ marginBottom: 8 }}>Where each input came from</h3>
              {inputs.map((input) => (
                <div key={input.item} style={{ marginBottom: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <strong>{itemLabel(input.item)}</strong>
                    <span>{input.value === null ? "—" : exact(input.value)}</span>
                  </div>
                  <p className="small muted" style={{ margin: "2px 0 4px" }}>
                    {input.concept
                      ? input.concept + " · " + (input.origin ?? "reported")
                      : "Analyst value"}
                    {input.mapping_version ? " · mapping v" + input.mapping_version : ""}
                  </p>
                  {input.note ? <p className="small" style={{ margin: "0 0 4px" }}>{input.note}</p> : null}
                  <FactTable facts={input.facts} />
                </div>
              ))}
            </>
          ) : null}

          <h3 style={{ margin: "18px 0 8px" }}>Versions this figure depends on</h3>
          <dl className="kv">
            <div>
              <dt>Test date</dt>
              <dd>{asOf(run.test_date)}</dd>
            </div>
            <div>
              <dt>Formula</dt>
              <dd>version {run.formula_version}</dd>
            </div>
            <div>
              <dt>Agreement</dt>
              <dd className="hash">{run.source_hash}</dd>
            </div>
            <div>
              <dt>Evaluator</dt>
              <dd>{run.evaluator_version}</dd>
            </div>
            <div>
              <dt>Output hash</dt>
              <dd className="hash">{run.output_hash}</dd>
            </div>
          </dl>
        </div>
      </aside>
    </div>
  );
}

/* -- trace builders -------------------------------------------------------- */

export function ebitdaTrace(scenario: ScenarioResult): TraceTarget {
  const lines = scenario.ebitda.components.filter((line) => line.state === "included");
  return {
    title: "Covenant EBITDA — " + scenario.id + " " + scenario.label,
    subtitle: "Recalculated from scratch under this scenario, not adjusted from another one.",
    working: (
      <>
        {lines.map((line) => (
          <div key={line.component} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
            <span>
              {line.clause ? line.clause + " " : ""}
              {itemLabel(line.item)}
              {line.cap_pool && line.requested !== line.contribution ? " (capped)" : ""}
            </span>
            <span>
              {line.sign === "-" ? "" : "+"}
              {exact(line.contribution)}
            </span>
          </div>
        ))}
        {scenario.ebitda.pools.map((pool) => (
          <div key={pool.pool}>
            Pool {pool.pool}: requested {exact(pool.a_requested)}, cap {exact(pool.cap)}
            {pool.basis === "before_pool" || pool.basis === "after_pool"
              ? " (measured on " + exact(pool.e_before_pool) + ")"
              : ""}
            , allowed {exact(pool.allowed)}
          </div>
        ))}
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontWeight: 600 }}>
          <span>Covenant EBITDA</span>
          <span>{exact(scenario.ebitda.ebitda)}</span>
        </div>
      </>
    ),
    inputs: lines.map((line) => line.item),
    reasons: scenario.ebitda.reasons,
  };
}

export function covenantTrace(
  covenant: CovenantResult,
  scenario: ScenarioResult,
  tightBand: string,
): TraceTarget {
  const isLeverage = covenant.covenant_type === "max_ratio";
  const sideItems = covenant.side.parts.map((part) => part.item);
  const items = [
    ...sideItems,
    ...(covenant.side.cash_netted ? ["cash_and_equivalents"] : []),
    ...scenario.ebitda.components.filter((l) => l.state === "included").map((l) => l.item),
  ];

  return {
    title: (covenant.covenant_name ?? covenant.covenant_id) + " — " + scenario.id,
    subtitle: isLeverage
      ? "Debt capacity is under this covenant only; other covenants and baskets may still restrict new debt."
      : "Measured against the interest the covenant names.",
    working: (
      <>
        {covenant.side.parts.map((part) => (
          <div key={part.item} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
            <span>{itemLabel(part.item)}</span>
            <span>+{exact(part.value)}</span>
          </div>
        ))}
        {covenant.side.cash_netted ? (
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
            <span>
              Less cash ({exact(covenant.side.cash_available)} available
              {covenant.side.cash_cap ? ", capped at " + exact(covenant.side.cash_cap) : ", uncapped"})
            </span>
            <span>−{exact(covenant.side.cash_netted)}</span>
          </div>
        ) : null}
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
          <span>{isLeverage ? "Net debt" : "Interest"}</span>
          <span>{exact(covenant.side.value)}</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
          <span>Covenant EBITDA</span>
          <span>{exact(covenant.ebitda)}</span>
        </div>
        <div>
          {isLeverage ? (
            <>
              Ratio = {exact(covenant.side.value)} ÷ {exact(covenant.ebitda)} ={" "}
              <strong>{ratio(covenant.ratio)}</strong> against a {ratio(covenant.threshold)} cap
            </>
          ) : (
            <>
              Ratio = {exact(covenant.ebitda)} ÷ {exact(covenant.side.value)} ={" "}
              <strong>{ratio(covenant.ratio)}</strong> against a {ratio(covenant.threshold)} floor
            </>
          )}
        </div>
        <div>
          {isLeverage ? (
            <>
              Cushion = 1 − {exact(covenant.side.value)} ÷ ({covenant.threshold} ×{" "}
              {exact(covenant.ebitda)}) = <strong>{percent(covenant.cushion)}</strong>
            </>
          ) : (
            <>
              Cushion = 1 − ({covenant.threshold} × {exact(covenant.side.value)}) ÷{" "}
              {exact(covenant.ebitda)} = <strong>{percent(covenant.cushion)}</strong>
            </>
          )}
        </div>
        <div>
          Covenant EBITDA could fall by {exact(covenant.headroom_ebitda)} before the test fails.
        </div>
        {isLeverage && covenant.debt_capacity ? (
          <div>
            Additional debt capacity under this covenant only = {covenant.threshold} ×{" "}
            {exact(covenant.ebitda)} − {exact(covenant.side.value)} ={" "}
            <strong>{exact(covenant.debt_capacity)}</strong>
          </div>
        ) : null}
        <div>
          Verdict <strong>{covenant.verdict}</strong>, with the tight band at{" "}
          {percent(tightBand, 0)}.
        </div>
      </>
    ),
    inputs: Array.from(new Set(items)),
    reasons: covenant.reasons,
  };
}

export function inputTrace(item: string, input: ItemInput): TraceTarget {
  return {
    title: itemLabel(item),
    subtitle: input.concept ? input.concept : "Analyst value with a source note",
    working: (
      <>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
          <span>{input.value === null ? "No usable value" : "Value used"}</span>
          <span>{input.value === null ? stateLabel("not_computable") : exact(input.value)}</span>
        </div>
        {input.note ? <div>{input.note}</div> : null}
      </>
    ),
    inputs: [item],
    reasons: input.reason ? [{ code: input.reason, item, detail: input.note }] : [],
  };
}
