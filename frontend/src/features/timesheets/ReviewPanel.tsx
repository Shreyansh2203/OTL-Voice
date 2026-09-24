import { useCallback, useMemo, useState } from 'react';
import { motion } from 'motion/react';
import * as api from '../../api/client';
import type { SubmitResponse, TimecardEntry } from '../../types';
export interface ReviewPanelProps {
  entries: TimecardEntry[];
  onSessionExpired: () => void;
}
export default function ReviewPanel(props: ReviewPanelProps) {
  return <ReviewPanelContent key={JSON.stringify(props.entries)} {...props} />;
}
function ReviewPanelContent({
  entries,
  onSessionExpired,
}: ReviewPanelProps) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SubmitResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adjustments, setAdjustments] = useState<Record<number, number>>({});

  const adjustHours = (index: number, delta: number) => {
    setAdjustments((prev) => {
      const cur =
        prev[index] !== undefined
          ? prev[index]
          : Number(entries[index]?.hours) || 0;
      const next = Math.max(0.5, Math.round((cur + delta) * 10) / 10);
      return { ...prev, [index]: next };
    });
  };

  const activeEntries = useMemo(
    () =>
      entries.map((e, i) => ({
        ...e,
        hours: adjustments[i] !== undefined ? adjustments[i] : e.hours,
      })),
    [entries, adjustments]
  );

  const totalHours = activeEntries.reduce(
    (sum, e) => sum + (Number(e.hours) || 0),
    0
  );
  const submit = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.submitTimecard(activeEntries));
    } catch (err) {
      if (err instanceof api.ApiError && err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(err instanceof Error ? err.message : 'Submission failed.');
    } finally {
      setBusy(false);
    }
  }, [activeEntries, onSessionExpired]);
  const retryFailed = useCallback(async () => {
    if (!result || !result.failed) return;
    setBusy(true);
    setError(null);
    const failedIndices = result.results
      .filter((row) => !row.ok)
      .map((row) => row.index);
    try {
      const retry = await api.submitTimecard(
        failedIndices.map((index) => activeEntries[index])
      );
      const replacements = new Map(
        retry.results.map((row) => [failedIndices[row.index], row])
      );
      const merged = result.results.map((row) => replacements.get(row.index) || row);
      setResult({
        ...result,
        succeeded: merged.filter((row) => row.ok).length,
        failed: merged.filter((row) => !row.ok).length,
        results: merged,
      });
    } catch (err) {
      if (err instanceof api.ApiError && err.status === 401) {
        onSessionExpired();
        return;
      }
      setError(err instanceof Error ? err.message : 'Retry failed.');
    } finally {
      setBusy(false);
    }
  }, [activeEntries, onSessionExpired, result]);
  return (
    <div className="approval-card" aria-busy={busy}>
      <div className="approval-head">
        <div className="approval-title">
          {!result ? (
            <span className="approval-badge">Action Required</span>
          ) : (
            <span
              className="approval-badge"
              style={{ background: 'var(--accent-color)' }}
            >
              Completed
            </span>
          )}
          <h3>{!result ? 'Approve Timesheet' : 'Timesheet Submitted'}</h3>
        </div>
        <span className="approval-meta">
          {activeEntries.length} {activeEntries.length === 1 ? 'entry' : 'entries'} &bull;{' '}
          {totalHours}h total
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
            {activeEntries.map((e, i) => (
              <tr
                key={
                  e.projectNo
                    ? `${e.projectNo}-${e.taskDetails}-${e.hours}-${i}`
                    : `entry-${i}`
                }
              >
                <td>
                  {e.employeeName || '—'}
                  <span className="muted small">
                    {' '}
                    #{e.employeeNumber || '—'}
                  </span>
                </td>
                <td>
                  {e.projectName || '—'}
                  {e.projectNo != null && (
                    <span className="muted small"> ({e.projectNo})</span>
                  )}
                </td>
                <td>{e.workOrder || '—'}</td>
                <td>{e.taskDetails || '—'}</td>
                <td className="num">
                  <div className="hour-stepper" style={{ display: 'inline-flex', alignItems: 'center' }}>
                    {!result && (
                      <button
                        type="button"
                        className="hour-stepper-btn"
                        onClick={() => adjustHours(i, -0.5)}
                        disabled={busy}
                        aria-label="Decrease hours"
                      >
                        -
                      </button>
                    )}
                    <span className="hour-stepper-val">{e.hours ?? '—'}</span>
                    {!result && (
                      <button
                        type="button"
                        className="hour-stepper-btn"
                        onClick={() => adjustHours(i, 0.5)}
                        disabled={busy}
                        aria-label="Increase hours"
                      >
                        +
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {result ? (
        <>
           <div
             className={`result ${result.failed ? 'warn' : 'ok'}`}
             aria-live="polite"
           >
             <strong>
               {result.succeeded}/{result.submitted} submitted to OTL
               {result.failed ? ` · ${result.failed} failed` : ''}.
             </strong>
             {result.failed > 0 && (
               <button
                 type="button"
                 className="btn btn-secondary"
                 onClick={retryFailed}
                 disabled={busy}
               >
                 {busy ? 'Retrying…' : 'Retry failed'}
               </button>
             )}
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
                    <tr
                      key={`${r.index}-${entry?.projectNo}-${entry?.taskDetails}`}
                    >
                      <td className="muted">{r.index + 1}</td>
                      <td>
                        {entry?.projectName || '—'}
                        {entry?.projectNo != null && (
                          <span className="muted small">
                            {' '}
                            ({entry.projectNo})
                          </span>
                        )}
                      </td>
                      <td>{entry?.taskDetails || '—'}</td>
                      <td className="num">{activeEntries[r.index]?.hours ?? '—'}</td>
                      <td>
                        {r.ok ? (
                          <span className="status-ok">
                            ✓ {r.recordNumber || 'Created'}
                          </span>
                        ) : (
                          <span className="status-fail">
                            ✗ {r.error || 'Failed'}
                          </span>
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
        <div
          className="approval-actions"
          style={{ display: 'flex', gap: '10px', alignItems: 'center' }}
        >
          <motion.button 
            whileHover={{ scale: 1.02 }} 
            whileTap={{ scale: 0.98 }} 
            className="btn-approve" 
            onClick={submit} 
            disabled={busy}
          >
            {busy ? 'Approving…' : 'Approve & Submit'}
          </motion.button>
        </div>
      )}
    </div>
  );
}
