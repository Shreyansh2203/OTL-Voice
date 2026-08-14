import { useState } from "react";
import * as api from "../api/client";
import type { SubmitResponse, TimecardEntry } from "../types";

export default function ReviewPanel({
  entries,
  onSessionExpired,
}: {
  entries: TimecardEntry[];
  onSessionExpired: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SubmitResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const totalHours = entries.reduce((sum, e) => sum + (Number(e.hours) || 0), 0);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.submitTimecard(entries));
    } catch (err) {
      if (err instanceof api.ApiError && err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(err instanceof Error ? err.message : "Submission failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="review card">
      <div className="review-head">
        <h3>Ready to submit</h3>
        <span className="muted">
          {entries.length} {entries.length === 1 ? "entry" : "entries"} · {totalHours} h
        </span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Employee</th>
              <th>Project</th>
              <th>Work order</th>
              <th>Task</th>
              <th className="num">Hours</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={i}>
                <td>
                  {e.employeeName || "—"}
                  <span className="muted small"> #{e.employeeNumber || "—"}</span>
                </td>
                <td>
                  {e.projectName || "—"}
                  {e.projectNo != null && (
                    <span className="muted small"> ({e.projectNo})</span>
                  )}
                </td>
                <td>{e.workOrder || "—"}</td>
                <td>{e.taskDetails || "—"}</td>
                <td className="num">{e.hours ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {error && <div className="error" role="alert">{error}</div>}

      {result ? (
        <>
          <div className={`result ${result.failed ? "warn" : "ok"}`}>
            <strong>
              {result.succeeded}/{result.submitted} submitted to OTL
              {result.failed ? ` · ${result.failed} failed` : ""}.
            </strong>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Project</th>
                  <th>Task</th>
                  <th className="num">Hours</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((r) => {
                  const entry = entries[r.index];
                  return (
                    <tr key={r.index}>
                      <td className="muted">{r.index + 1}</td>
                      <td>
                        {entry?.projectName || "—"}
                        {entry?.projectNo != null && (
                          <span className="muted small"> ({entry.projectNo})</span>
                        )}
                      </td>
                      <td>{entry?.taskDetails || "—"}</td>
                      <td className="num">{entry?.hours ?? "—"}</td>
                      <td>
                        {r.ok ? (
                          <span className="status-ok">✓ {r.recordNumber || "Created"}</span>
                        ) : (
                          <span className="status-fail">✗ {r.error || "Failed"}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <button className="primary" onClick={submit} disabled={busy}>
          {busy ? "Submitting…" : `Submit ${entries.length} to OTL`}
        </button>
      )}
    </div>
  );
}
