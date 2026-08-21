import { useState, useEffect, useRef } from "react";
import * as api from "../api/client";
import type { SubmitResponse, TimecardEntry } from "../types";

/**
 * Properties for the ReviewPanel component.
 */
export interface ReviewPanelProps {
  /** The timecard entries extracted from the assistant's response to be reviewed. */
  entries: TimecardEntry[];
  /** Callback fired when an API call indicates the session has expired. */
  onSessionExpired: () => void;
  /** Automatically trigger submission on mount. */
  autoSubmit?: boolean;
}

/**
 * An interactive panel allowing the user to review, approve, and submit extracted 
 * timecard entries to Oracle Fusion. Displays submission success/failure results.
 * 
 * @param props - Component properties.
 */
export default function ReviewPanel({
  entries,
  onSessionExpired,
  autoSubmit = false,
}: ReviewPanelProps) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SubmitResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [countdown, setCountdown] = useState<number | null>(null);

  const totalHours = entries.reduce((sum, e) => sum + (Number(e.hours) || 0), 0);

  const submit = async () => {
    setCountdown(null);
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
  };

  const hasAutoSubmitted = useRef(false);

  useEffect(() => {
    if (autoSubmit && !hasAutoSubmitted.current && !result && !error) {
      hasAutoSubmitted.current = true;
      setCountdown(4);
    }
  }, [autoSubmit, result, error]);

  useEffect(() => {
    if (countdown === null) return;
    if (countdown <= 0) {
      submit();
      return;
    }
    const timer = setTimeout(() => {
      setCountdown((prev) => (prev !== null ? prev - 1 : null));
    }, 1000);
    return () => clearTimeout(timer);
  }, [countdown]);

  return (
    <div className="approval-card" aria-busy={busy}>
      <div className="approval-head">
        <div className="approval-title">
          <span className="approval-badge">Action Required</span>
          <h3>Approve Timesheet</h3>
        </div>
        <span className="approval-meta">
          {entries.length} {entries.length === 1 ? "entry" : "entries"} • {totalHours}h total
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
          <div className={`result ${result.failed ? "warn" : "ok"}`} aria-live="polite">
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
        <div className="approval-actions" style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          {countdown !== null ? (
            <>
              <span className="muted small">Auto-submitting in {countdown}s...</span>
              <button className="ghost" onClick={() => setCountdown(null)}>
                Cancel Auto-Submit
              </button>
            </>
          ) : (
            <button className="btn-approve" onClick={submit} disabled={busy}>
              {busy ? "Approving…" : `Approve & Submit`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
