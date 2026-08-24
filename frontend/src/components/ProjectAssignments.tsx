import { useEffect, useState } from "react";
import * as api from "../api/client";
import type { AssignmentsResponse, AssignedWorkOrder } from "../types";

function FolderIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
      strokeLinecap="round" strokeLinejoin="round"
      style={{ transition: "transform 0.2s", transform: open ? "rotate(90deg)" : "rotate(0deg)" }}
    >
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function TaskIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 11 12 14 22 4" />
      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

function ProjectCard({ wo }: { wo: AssignedWorkOrder }) {
  const [open, setOpen] = useState(true);
  const totalTasks = wo.projects.reduce((sum, p) => sum + (p.tasks?.length ?? 0), 0);

  return (
    <div className="pa-card">
      <button className="pa-card-header" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="pa-card-header-left">
          <span className="pa-folder-icon"><FolderIcon /></span>
          <span className="pa-wo-label">{wo.workOrder}</span>
        </span>
        <span className="pa-card-header-right">
          <span className="pa-badge">{wo.projects.length} project{wo.projects.length !== 1 ? "s" : ""}</span>
          <span className="pa-badge pa-badge-subtle">{totalTasks} task{totalTasks !== 1 ? "s" : ""}</span>
          <span className="pa-chevron"><ChevronIcon open={open} /></span>
        </span>
      </button>

      {open && (
        <div className="pa-card-body">
          {wo.projects.map((p, j) => (
            <div key={j} className="pa-project">
              <div className="pa-project-header">
                <div className="pa-project-title">{p.projectName}</div>
                <div className="pa-project-num">#{p.projectNo}</div>
              </div>
              {p.tasks && p.tasks.length > 0 ? (
                <div className="pa-tasks">
                  {p.tasks.map((t, k) => (
                    <span key={k} className="pa-task-chip">
                      <span className="pa-task-icon"><TaskIcon /></span>
                      <span className="pa-task-id">{t.taskId}</span>
                      <span className="pa-task-sep">·</span>
                      <span>{t.taskDetails}</span>
                    </span>
                  ))}
                </div>
              ) : (
                <p className="pa-no-tasks">No tasks defined</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ProjectAssignments({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [data, setData] = useState<AssignmentsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    api.getAssignments()
      .then((res) => { setData(res); setLoading(false); })
      .catch((err) => {
        if (err instanceof api.ApiError && (err.status === 401 || err.status === 403)) {
          onSessionExpired();
        } else {
          setError(err.message || "Failed to load projects.");
        }
        setLoading(false);
      });
  }, [onSessionExpired]);

  if (loading) {
    return (
      <div className="pa-wrapper">
        <div className="pa-loading">
          <div className="pa-spinner" />
          <span>Loading your projects…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="pa-wrapper">
        <div className="pa-error-box">⚠️ {error}</div>
      </div>
    );
  }

  const workOrders = data?.workOrders ?? [];

  const filtered = search.trim()
    ? workOrders.filter((wo) => {
        const q = search.toLowerCase();
        return (
          wo.workOrder.toLowerCase().includes(q) ||
          wo.projects.some(
            (p) =>
              p.projectName.toLowerCase().includes(q) ||
              String(p.projectNo).includes(q) ||
              p.tasks?.some((t) => t.taskDetails.toLowerCase().includes(q))
          )
        );
      })
    : workOrders;

  const totalProjects = workOrders.reduce((s, wo) => s + wo.projects.length, 0);

  return (
    <div className="pa-wrapper">
      {/* Header */}
      <div className="pa-header">
        <div className="pa-header-text">
          <h2 className="pa-title">My Projects</h2>
          <p className="pa-subtitle">
            {workOrders.length === 0
              ? "You have no project assignments."
              : `${totalProjects} project${totalProjects !== 1 ? "s" : ""} across ${workOrders.length} work order${workOrders.length !== 1 ? "s" : ""}`}
          </p>
        </div>
        {workOrders.length > 0 && (
          <div className="pa-summary-chips">
            <span className="pa-stat"><strong>{workOrders.length}</strong> WOs</span>
            <span className="pa-stat"><strong>{totalProjects}</strong> Projects</span>
          </div>
        )}
      </div>

      {/* Search */}
      {workOrders.length > 0 && (
        <div className="pa-search-wrap">
          <span className="pa-search-icon"><SearchIcon /></span>
          <input
            className="pa-search"
            type="text"
            placeholder="Search by work order, project, or task…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button className="pa-search-clear" onClick={() => setSearch("")} aria-label="Clear search">×</button>
          )}
        </div>
      )}

      {/* Empty state */}
      {workOrders.length === 0 && (
        <div className="pa-empty">
          <div className="pa-empty-icon">🗂️</div>
          <p className="pa-empty-title">No projects assigned</p>
          <p className="pa-empty-sub">Please contact your manager to get project access.</p>
        </div>
      )}

      {/* No search results */}
      {workOrders.length > 0 && filtered.length === 0 && (
        <div className="pa-empty">
          <div className="pa-empty-icon">🔍</div>
          <p className="pa-empty-title">No results for "{search}"</p>
          <p className="pa-empty-sub">Try a different search term.</p>
        </div>
      )}

      {/* Project cards */}
      <div className="pa-list">
        {filtered.map((wo, i) => (
          <ProjectCard key={i} wo={wo} />
        ))}
      </div>

      <style>{`
        .pa-wrapper {
          padding: var(--space-5) var(--space-6) var(--space-8);
          max-width: 780px;
          margin: 0 auto;
        }

        /* ── Header ── */
        .pa-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 1rem;
          margin-bottom: var(--space-5);
        }
        .pa-title {
          margin: 0 0 0.2rem;
          font-size: 1.5rem;
          font-variation-settings: 'wght' var(--font-weight-display);
          letter-spacing: -0.03em;
        }
        .pa-subtitle {
          margin: 0;
          font-size: 14px;
          color: var(--color-text-tertiary);
        }
        .pa-summary-chips {
          display: flex;
          gap: var(--space-2);
          flex-shrink: 0;
        }
        .pa-stat {
          background: var(--color-bg-primary);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-button);
          padding: 6px 12px;
          font-size: 13px;
          font-variation-settings: 'wght' var(--font-weight-ui);
          white-space: nowrap;
          color: var(--color-text-secondary);
          box-shadow: rgba(0, 0, 0, 0.02) 0 1px 2px 0;
        }
        .pa-stat strong { color: var(--color-accent-primary); }

        /* ── Search ── */
        .pa-search-wrap {
          position: relative;
          margin-bottom: var(--space-5);
        }
        .pa-search-icon {
          position: absolute;
          left: 14px;
          top: 50%;
          transform: translateY(-50%);
          color: var(--color-text-tertiary);
          display: flex;
          align-items: center;
        }
        .pa-search {
          width: 100%;
          padding: 12px 2.5rem 12px 2.5rem;
          border: 1px solid var(--color-border-strong);
          border-radius: var(--radius-input);
          background: var(--color-bg-primary);
          color: var(--color-text-primary);
          font-size: 14px;
          outline: none;
          box-shadow: rgba(0, 0, 0, 0.02) 0 1px 2px 0 inset;
          transition: border-color var(--duration-fast) var(--ease-default),
                      box-shadow var(--duration-fast) var(--ease-default);
        }
        .pa-search::placeholder { color: var(--color-text-tertiary); }
        .pa-search:focus {
          border-color: var(--color-accent-primary);
          box-shadow: var(--shadow-focus);
        }
        .pa-search-clear {
          position: absolute;
          right: 12px;
          top: 50%;
          transform: translateY(-50%);
          background: none;
          border: none;
          cursor: pointer;
          font-size: 1.1rem;
          color: var(--color-text-tertiary);
          padding: 2px 6px;
          border-radius: var(--radius-circle);
          line-height: 1;
          transition: color var(--duration-fast) var(--ease-default);
        }
        .pa-search-clear:hover { color: var(--color-text-primary); }

        /* ── Cards ── */
        .pa-list { display: flex; flex-direction: column; gap: var(--space-4); }
        .pa-card {
          background: var(--color-bg-primary);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-card);
          overflow: hidden;
          box-shadow: var(--shadow-card);
        }
        .pa-card-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          width: 100%;
          padding: 16px var(--space-5);
          background: var(--color-bg-primary);
          border: none;
          cursor: pointer;
          color: var(--color-text-primary);
          text-align: left;
          gap: var(--space-3);
          transition: background-color var(--duration-fast) var(--ease-default);
        }
        .pa-card-header:hover { background: var(--color-bg-secondary); }
        .pa-card-header-left {
          display: flex;
          align-items: center;
          gap: 12px;
          font-variation-settings: 'wght' var(--font-weight-ui);
          font-size: 15px;
        }
        .pa-folder-icon { color: var(--color-accent-primary); display: flex; align-items: center; }
        .pa-wo-label { font-family: var(--font-mono); font-variation-settings: 'wght' var(--font-weight-ui); }
        .pa-card-header-right {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-shrink: 0;
        }
        .pa-badge {
          background: var(--color-accent-light);
          color: var(--color-accent-active);
          border-radius: var(--radius-button);
          padding: 4px 10px;
          font-size: 12px;
          font-variation-settings: 'wght' var(--font-weight-ui);
        }
        .pa-badge-subtle {
          background: var(--color-bg-secondary);
          color: var(--color-text-secondary);
          border: 1px solid var(--color-border-subtle);
        }
        .pa-chevron { color: var(--color-text-tertiary); display: flex; align-items: center; }

        /* ── Card body ── */
        .pa-card-body {
          border-top: 1px solid var(--color-border-subtle);
          padding: var(--space-2) 0;
          background: var(--color-bg-secondary);
        }
        .pa-project {
          padding: var(--space-4) var(--space-5);
        }
        .pa-project + .pa-project {
          border-top: 1px solid var(--color-border-subtle);
        }
        .pa-project-header {
          display: flex;
          align-items: baseline;
          justify-content: space-between;
          gap: var(--space-2);
          margin-bottom: 12px;
        }
        .pa-project-title {
          font-variation-settings: 'wght' var(--font-weight-ui);
          font-size: 14px;
          color: var(--color-text-primary);
        }
        .pa-project-num {
          font-size: 12px;
          color: var(--color-text-tertiary);
          background: var(--color-bg-primary);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-button);
          padding: 2px 8px;
          white-space: nowrap;
          flex-shrink: 0;
          font-family: var(--font-mono);
        }

        /* ── Task chips ── */
        .pa-tasks {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .pa-task-chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: var(--color-bg-primary);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-button);
          padding: 6px 12px;
          font-size: 13px;
          color: var(--color-text-secondary);
          white-space: nowrap;
          box-shadow: rgba(0, 0, 0, 0.02) 0 1px 2px 0;
          transition: border-color var(--duration-fast) var(--ease-default);
        }
        .pa-task-chip:hover { border-color: var(--color-border-strong); }
        .pa-task-icon { color: var(--color-status-success); display: flex; align-items: center; }
        .pa-task-id {
          font-family: var(--font-mono);
          font-size: 12px;
          color: var(--color-text-tertiary);
          background: var(--color-bg-secondary);
          border-radius: 2px;
          padding: 2px 6px;
        }
        .pa-task-sep { color: var(--color-border-subtle); }
        .pa-no-tasks { margin: 0; font-size: 13px; color: var(--color-text-tertiary); font-style: italic; }

        /* ── Loading ── */
        .pa-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: var(--space-3);
          padding: var(--space-8);
          color: var(--color-text-tertiary);
          font-size: 14px;
          font-variation-settings: 'wght' var(--font-weight-ui);
        }
        .pa-spinner {
          width: 32px; height: 32px;
          border: 3px solid var(--color-border-subtle);
          border-top-color: var(--color-accent-primary);
          border-radius: var(--radius-circle);
          animation: pa-spin 700ms linear infinite;
        }
        @keyframes pa-spin { to { transform: rotate(360deg); } }

        /* ── Error / empty ── */
        .pa-error-box {
          background: var(--color-status-error-bg);
          color: var(--color-status-error);
          border: 1px solid rgba(224, 30, 90, 0.2);
          border-radius: var(--radius-card);
          padding: 16px var(--space-5);
          font-size: 14px;
          box-shadow: rgba(0, 0, 0, 0.02) 0 1px 2px 0;
        }
        .pa-empty {
          text-align: center;
          padding: var(--space-8) var(--space-4);
          color: var(--color-text-tertiary);
        }
        .pa-empty-icon { font-size: 2.5rem; margin-bottom: var(--space-3); }
        .pa-empty-title { font-size: 1.2rem; font-variation-settings: 'wght' var(--font-weight-ui); color: var(--color-text-primary); margin: 0 0 6px; }
        .pa-empty-sub { font-size: 14px; margin: 0; }
      `}</style>
    </div>
  );
}
