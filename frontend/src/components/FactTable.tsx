/* Filing facts with their accession numbers.
 *
 * The accession number is the point: it is what turns a figure on this screen
 * into something an analyst can look up on EDGAR themselves.
 */

import type { FactRef } from "../api";
import { exact } from "../format";

export function FactTable({ facts }: { facts: FactRef[] }) {
  if (facts.length === 0) {
    return <p className="small muted" style={{ margin: 0 }}>No facts recorded.</p>;
  }
  return (
    <details className="facts">
      <summary>
        {facts.length === 1 ? "1 fact" : facts.length + " facts"} with provenance
      </summary>
      <table>
        <thead>
          <tr>
            <th>Period</th>
            <th className="num">Value</th>
            <th>Origin</th>
            <th>Filing</th>
          </tr>
        </thead>
        <tbody>
          {facts.map((fact, index) => (
            <tr key={index}>
              <td>
                {fact.period_type === "instant"
                  ? "at " + fact.instant
                  : fact.start + " to " + fact.end}
              </td>
              <td className="num">{exact(fact.value)}</td>
              <td>
                {fact.origin}
                {fact.transformation ? (
                  <span className="state" style={{ display: "block" }}>
                    {fact.transformation}
                  </span>
                ) : null}
              </td>
              <td>
                {fact.accession ? (
                  <a
                    href={
                      "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum=" +
                      fact.accession
                    }
                    target="_blank"
                    rel="noreferrer"
                  >
                    {fact.accession}
                  </a>
                ) : (
                  "—"
                )}
                {fact.form ? <span className="state" style={{ display: "block" }}>{fact.form}</span> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
