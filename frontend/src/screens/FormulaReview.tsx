/* Screen 2. Does the formula correctly represent the contract?
 *
 * Agreement text on the left, the structured formula on the right. Selecting a
 * component fetches the clause around its span and highlights the cited words,
 * so a reviewer reads the contract and the formula entry side by side rather
 * than trusting a citation they cannot see.
 *
 * Approval is refused while anything is unresolved, and the blockers say what.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { Blocker, Component, FormulaVersion, MappingRecord, Span } from "../api";
import {
  blockerLabel,
  capRule,
  categoryLabel,
  itemLabel,
  shortHash,
} from "../format";

const CONTEXT = 900; // characters of agreement either side of the cited span

type Selection = { key: string; span: Span; label: string } | null;

export function FormulaReview({
  dealId,
  version,
  blockers,
  mappings,
  onChanged,
}: {
  dealId: string;
  version: FormulaVersion;
  blockers: Blocker[];
  mappings: MappingRecord[];
  onChanged: () => void;
}) {
  const [selection, setSelection] = useState<Selection>(null);
  const [clause, setClause] = useState<{ text: string; start: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const markRef = useRef<HTMLElement>(null);
  const paneRef = useRef<HTMLDivElement>(null);

  const select = useCallback(
    (key: string, span: Span, label: string) => {
      setSelection({ key, span, label });
    },
    [],
  );

  useEffect(() => {
    if (!selection) {
      setClause(null);
      return;
    }
    const start = Math.max(0, selection.span.start - CONTEXT);
    const end = selection.span.end + CONTEXT;
    let cancelled = false;
    api
      .agreement(dealId, start, end)
      .then((slice) => {
        if (!cancelled) setClause({ text: slice.text, start: slice.start });
      })
      .catch((exc: Error) => {
        if (!cancelled) setError(exc.message);
      });
    return () => {
      cancelled = true;
    };
  }, [dealId, selection]);

  // The clause pane shows context either side of the citation, so the cited
  // words start out below the fold. Bringing them to the middle is the whole
  // point of the pane - but only the pane scrolls: scrollIntoView would also
  // scroll the page and push the formula table out from under the cursor.
  useEffect(() => {
    const pane = paneRef.current;
    const mark = markRef.current;
    if (!clause || !pane || !mark) return;
    pane.scrollTop = Math.max(0, mark.offsetTop - pane.clientHeight / 2);
  }, [clause]);

  const isDraft = version.status === "draft";

  async function decide(component: Component, decision: string, note?: string) {
    setBusy(true);
    setError(null);
    try {
      await api.review(dealId, version.version, {
        reviewer: "analyst",
        decisions: [{ target: componentKey(component), decision, note: note ?? null }],
      });
      onChanged();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.approve(dealId, version.version, "analyst");
      setMessage("Version " + version.version + " approved. It is now immutable.");
      onChanged();
    } catch (exc) {
      if (exc instanceof ApiError) {
        setError(
          exc.message +
            (exc.blockers.length
              ? ": " + exc.blockers.map((b) => blockerLabel(b.code) + " (" + b.target + ")").join("; ")
              : ""),
        );
      } else {
        setError(String(exc));
      }
    } finally {
      setBusy(false);
    }
  }

  async function startNewDraft() {
    setBusy(true);
    try {
      await api.newDraft(dealId, version.version);
      setMessage("Started a new draft from version " + version.version + ".");
      onChanged();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {error ? <div className="notice bad">{error}</div> : null}
      {message ? <div className="notice good">{message}</div> : null}

      {blockers.length > 0 ? (
        <div className="blockers">
          <h2>Approval is blocked while {blockers.length} thing{blockers.length === 1 ? "" : "s"} {blockers.length === 1 ? "is" : "are"} unresolved</h2>
          <ul>
            {blockers.map((blocker, index) => (
              <li key={index}>
                <strong>{blockerLabel(blocker.code)}</strong> — {blocker.target}. {blocker.detail}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="review-grid">
        <section className="panel clause-pane">
          <div className="panel-head">
            <div>
              <h2>Agreement text</h2>
              <p>
                {selection
                  ? "Showing the clause cited by " + selection.label + "."
                  : "Select a component to read the clause it cites."}
              </p>
            </div>
            <span className="small muted">{shortHash(version.source_hash)}</span>
          </div>
          {clause && selection ? (
            <div className="clause-text" ref={paneRef}>
              {renderHighlighted(clause.text, clause.start, selection.span, markRef)}
            </div>
          ) : (
            <p className="clause-empty">
              Every component carries a character range into this agreement, and the quote has
              already been checked against the text at that range. Select one to see it.
            </p>
          )}
        </section>

        <div>
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Consolidated EBITDA, clause by clause</h2>
                <p>
                  {version.ebitda.drafted_with
                    ? "Drafted by " +
                      version.ebitda.drafted_with.model +
                      " with prompt " +
                      version.ebitda.drafted_with.prompt_version +
                      " in " +
                      version.ebitda.drafted_with.attempts +
                      (version.ebitda.drafted_with.attempts === 1 ? " attempt" : " attempts") +
                      ", then reviewed by hand."
                    : "Written by hand from the clause text."}
                </p>
              </div>
              <span className={"pill " + (isDraft ? "" : "ok")}>
                Version {version.version} · {version.status}
              </span>
            </div>
            <div className="panel-body flush">
              <table>
                <thead>
                  <tr>
                    <th>Clause</th>
                    <th>Item</th>
                    <th>Sign</th>
                    <th>Category</th>
                    <th>Cap</th>
                    <th>Review</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    className="component-row"
                    aria-selected={selection?.key === "base"}
                    onClick={() =>
                      select("base", version.ebitda.base.span, "the base term")
                    }
                  >
                    <td className="clause-ref">{version.ebitda.base.clause ?? "base"}</td>
                    <td>{itemLabel(version.ebitda.base.item)}</td>
                    <td>+</td>
                    <td className="muted">base</td>
                    <td className="muted">—</td>
                    <td className="muted">—</td>
                  </tr>
                  {version.ebitda.components.map((component) => {
                    const key = componentKey(component);
                    const pool = component.cap_pool
                      ? version.ebitda.cap_pools[component.cap_pool]
                      : null;
                    const excluded =
                      component.review?.decision === "rejected" ||
                      component.review?.decision === "excluded_unsupported";
                    return (
                      <tr
                        key={key}
                        className={"component-row" + (excluded ? " excluded" : "")}
                        aria-selected={selection?.key === key}
                        onClick={() =>
                          select(key, component.span, "clause " + (component.clause ?? key))
                        }
                      >
                        <td className="clause-ref">{component.clause ?? "—"}</td>
                        <td>
                          {itemLabel(component.item)}
                          {component.reason ? (
                            <span className="state" style={{ display: "block" }}>
                              {component.reason}
                            </span>
                          ) : null}
                        </td>
                        <td>{component.sign}</td>
                        <td>{categoryLabel(component.category)}</td>
                        <td className="small">
                          {pool ? capRule(pool) : <span className="muted">uncapped</span>}
                        </td>
                        <td className="small">
                          {component.review ? (
                            <>
                              <span
                                className={
                                  "pill " +
                                  (component.review.decision === "accepted"
                                    ? "ok"
                                    : component.review.decision === "edited"
                                      ? ""
                                      : "flag")
                                }
                              >
                                {component.review.decision.replace(/_/g, " ")}
                              </span>
                              {component.review.note ? (
                                <span className="state" style={{ display: "block" }}>
                                  {component.review.note}
                                </span>
                              ) : null}
                            </>
                          ) : isDraft ? (
                            <div className="actions">
                              <button
                                type="button"
                                className="btn small secondary"
                                disabled={busy}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void decide(component, "accepted");
                                }}
                              >
                                Accept
                              </button>
                              <button
                                type="button"
                                className="btn small secondary"
                                disabled={busy}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  const note = window.prompt(
                                    "Why is this clause excluded? The note is kept with the version.",
                                  );
                                  if (note) void decide(component, "excluded_unsupported", note);
                                }}
                              >
                                Exclude
                              </button>
                            </div>
                          ) : (
                            <span className="pill flag">not reviewed</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Financial covenants</h2>
                <p>Each covenant's threshold schedule, as the agreement states it.</p>
              </div>
            </div>
            <div className="panel-body flush">
              <table>
                <thead>
                  <tr>
                    <th>Covenant</th>
                    <th>Test</th>
                    <th>Thresholds</th>
                    <th>Review</th>
                  </tr>
                </thead>
                <tbody>
                  {version.covenants.map((covenant) => (
                    <tr
                      key={covenant.id}
                      className="component-row"
                      aria-selected={selection?.key === covenant.id}
                      onClick={() => select(covenant.id, covenant.span, covenant.id)}
                    >
                      <td>
                        {covenant.name ?? covenant.id}
                        {covenant.reason ? (
                          <span className="state" style={{ display: "block" }}>
                            {covenant.reason}
                          </span>
                        ) : null}
                      </td>
                      <td className="small">
                        {covenant.type === "max_ratio" ? "Maximum" : "Minimum"}, quarterly on TTM
                      </td>
                      <td className="small">
                        {covenant.schedule.map((step) => (
                          <div key={step.from}>
                            {step.threshold}x from {step.from}
                          </div>
                        ))}
                      </td>
                      <td className="small">
                        {covenant.review ? (
                          <>
                            <span className="pill ok">{covenant.review.decision.replace(/_/g, " ")}</span>
                            {covenant.review.note ? (
                              <span className="state" style={{ display: "block" }}>
                                {covenant.review.note}
                              </span>
                            ) : null}
                          </>
                        ) : (
                          <span className="pill flag">not reviewed</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div className="actions" style={{ marginBottom: 24 }}>
            {isDraft ? (
              <button
                type="button"
                className="btn"
                disabled={busy || blockers.length > 0}
                onClick={() => void approve()}
                title={
                  blockers.length > 0
                    ? "Resolve the blockers above first"
                    : "Freeze this draft as an immutable version"
                }
              >
                Approve version {version.version}
              </button>
            ) : (
              <button
                type="button"
                className="btn secondary"
                disabled={busy}
                onClick={() => void startNewDraft()}
              >
                Start a new draft from version {version.version}
              </button>
            )}
            <span className="small muted">
              Approval freezes every component decision and cannot be undone.
            </span>
          </div>

          <MappingReview dealId={dealId} mappings={mappings} onChanged={onChanged} />
        </div>
      </div>
    </>
  );
}

function componentKey(component: Component): string {
  return component.item + "@" + (component.clause ?? String(component.span.start));
}

function renderHighlighted(
  text: string,
  offset: number,
  span: Span,
  markRef: React.RefObject<HTMLElement>,
) {
  const from = Math.max(0, span.start - offset);
  const to = Math.max(from, span.end - offset);
  return (
    <>
      {text.slice(0, from)}
      <mark ref={markRef as React.RefObject<HTMLElement>}>{text.slice(from, to)}</mark>
      {text.slice(to)}
    </>
  );
}

/* -- the data gate --------------------------------------------------------- */

function MappingReview({
  dealId,
  mappings,
  onChanged,
}: {
  dealId: string;
  mappings: MappingRecord[];
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const verified = mappings.filter((record) => record.status === "verified").length;

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Data mappings</h2>
          <p>
            A candidate concept is a suggestion, not a match: an available concept is not
            necessarily the contractual item. Only a verified mapping with a written rationale can
            feed a computable result.
          </p>
        </div>
        <span className={"pill " + (verified === mappings.length && mappings.length > 0 ? "ok" : "flag")}>
          {verified} of {mappings.length} verified
        </span>
      </div>
      <div className="panel-body flush">
        <table>
          <thead>
            <tr>
              <th>Formula item</th>
              <th>Source</th>
              <th>Status</th>
              <th>Rationale</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {mappings.map((record) => (
              <tr key={record.formula_item}>
                <td>
                  {itemLabel(record.formula_item)}
                  <span className="state" style={{ display: "block" }}>
                    {record.period_type === "instant" ? "balance at the test date" : "TTM flow"}
                  </span>
                </td>
                <td className="small">
                  {record.analyst_value !== null ? (
                    <>Analyst value {record.analyst_value}</>
                  ) : record.concept ? (
                    record.concept
                  ) : (
                    <span className="muted">no concept proposed</span>
                  )}
                  {record.candidates.length > 0 ? (
                    <span className="state" style={{ display: "block" }}>
                      candidates:{" "}
                      {record.candidates
                        .map((c) => c.concept + (c.reported ? "" : " (not reported)"))
                        .join(", ")}
                    </span>
                  ) : null}
                </td>
                <td className="small">
                  <span
                    className={
                      "pill " +
                      (record.status === "verified" ? "ok" : record.status === "unavailable" ? "flag" : "flag")
                    }
                  >
                    {record.status.replace(/_/g, " ")}
                  </span>
                  <span className="state" style={{ display: "block" }}>
                    v{record.mapping_version}
                  </span>
                </td>
                <td className="small">{record.rationale ?? <span className="muted">—</span>}</td>
                <td>
                  <button
                    type="button"
                    className="btn small secondary"
                    onClick={() =>
                      setEditing(editing === record.formula_item ? null : record.formula_item)
                    }
                  >
                    {editing === record.formula_item ? "Cancel" : "Decide"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {editing ? (
          <MappingForm
            dealId={dealId}
            record={mappings.find((row) => row.formula_item === editing)!}
            onDone={() => {
              setEditing(null);
              onChanged();
            }}
          />
        ) : null}
      </div>
    </section>
  );
}

function MappingForm({
  dealId,
  record,
  onDone,
}: {
  dealId: string;
  record: MappingRecord;
  onDone: () => void;
}) {
  const [status, setStatus] = useState(record.status === "review_required" ? "verified" : record.status);
  const [concept, setConcept] = useState(record.concept ?? "");
  const [analystValue, setAnalystValue] = useState(record.analyst_value ?? "");
  const [rationale, setRationale] = useState(record.rationale ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.decideMapping(dealId, record.formula_item, {
        status,
        rationale,
        concept: analystValue.trim() ? null : concept.trim() || null,
        analyst_value: analystValue.trim() || null,
        reviewer: "analyst",
      });
      onDone();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel-body" style={{ borderTop: "1px solid var(--rule)" }}>
      <h3 style={{ marginBottom: 10 }}>{itemLabel(record.formula_item)}</h3>
      {error ? <div className="notice bad">{error}</div> : null}
      <label className="field">
        Decision
        <select value={status} onChange={(event) => setStatus(event.target.value as typeof status)}>
          <option value="verified">Verified — this source is the contractual item</option>
          <option value="unavailable">Unavailable — no suitable source exists</option>
          <option value="review_required">Back to review</option>
        </select>
      </label>
      <label className="field">
        Reported concept
        <select
          value={concept}
          onChange={(event) => setConcept(event.target.value)}
          disabled={Boolean(analystValue.trim())}
        >
          <option value="">(none)</option>
          {record.candidates.map((candidate) => (
            <option key={candidate.concept} value={candidate.concept}>
              {candidate.concept}
              {candidate.reported ? "" : " — not reported by this filer"}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        Or an analyst value, in full units
        <input
          value={analystValue}
          onChange={(event) => setAnalystValue(event.target.value)}
          placeholder="e.g. 253841000"
          inputMode="decimal"
        />
      </label>
      <label className="field">
        Rationale, kept with the decision
        <textarea
          value={rationale}
          onChange={(event) => setRationale(event.target.value)}
          placeholder="Why this source is, or is not, the item the clause names. Name the filings you checked."
        />
      </label>
      <div className="actions">
        <button type="button" className="btn" disabled={busy || !rationale.trim()} onClick={() => void submit()}>
          Record decision
        </button>
        <span className="small muted">A decision creates mapping version {record.mapping_version + 1}.</span>
      </div>
    </div>
  );
}
