/* The empty state: an invitation to add the first deal.
 *
 * A deal is a CIK and the URL of the credit agreement exhibit on EDGAR. The
 * backend fetches and normalises the agreement; nothing is pasted by hand
 * unless the section locator fails.
 */

import { useState } from "react";
import { api } from "../api";

const EXAMPLE = {
  deal_id: "teleflex-2025q2",
  borrower: "Teleflex Incorporated",
  cik: "0000096943",
  exhibit_url:
    "https://www.sec.gov/Archives/edgar/data/96943/000009694325000107/ex101to6-27x20258xkrecredi.htm",
};

export function NewDeal({ onCreated }: { onCreated: (dealId: string) => Promise<void> }) {
  const [form, setForm] = useState(EXAMPLE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set(field: keyof typeof form) {
    return (event: React.ChangeEvent<HTMLInputElement>) =>
      setForm((current) => ({ ...current, [field]: event.target.value }));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.createDeal(form);
      await onCreated(created.deal_id);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" style={{ maxWidth: 680 }}>
      <div className="panel-head">
        <div>
          <h2>Add a deal</h2>
          <p>
            Headroom needs the borrower's CIK, so it can read their reported financials, and the URL
            of the credit agreement exhibit, so it can read the covenant definitions. The fields are
            prefilled with the agreement used to build the golden set.
          </p>
        </div>
      </div>
      <form className="panel-body" onSubmit={submit}>
        {error ? <div className="notice bad">{error}</div> : null}
        <label className="field">
          Deal id
          <input value={form.deal_id} onChange={set("deal_id")} required />
        </label>
        <label className="field">
          Borrower
          <input value={form.borrower} onChange={set("borrower")} required />
        </label>
        <label className="field">
          CIK
          <input value={form.cik} onChange={set("cik")} required inputMode="numeric" />
        </label>
        <label className="field">
          Credit agreement exhibit URL
          <input value={form.exhibit_url} onChange={set("exhibit_url")} required />
        </label>
        <div className="actions">
          <button type="submit" className="btn" disabled={busy}>
            {busy ? "Fetching the agreement…" : "Add deal"}
          </button>
          <span className="small muted">
            Find candidates with EDGAR full-text search for a phrase such as "Consolidated Total
            Net Leverage Ratio".
          </span>
        </div>
      </form>
    </section>
  );
}
