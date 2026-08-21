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
          padding: 1.25rem 1.5rem 3rem;
          max-width: 780px;
          margin: 0 auto;
        }

        /* ── Header ── */
        .pa-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 1rem;
          margin-bottom: 1.25rem;
        }
        .pa-title {
          margin: 0 0 0.2rem;
          font-size: 1.25rem;
          font-weight: 700;
          letter-spacing: -0.02em;
        }
        .pa-subtitle {
          margin: 0;
          font-size: 0.85rem;
          color: var(--muted);
        }
        .pa-summary-chips {
          display: flex;
          gap: 0.5rem;
          flex-shrink: 0;
        }
        .pa-stat {
          background: var(--surface-2);
          border: 1px solid var(--border);
          border-radius: 8px;
          padding: 0.3rem 0.65rem;
          font-size: 0.8rem;
          white-space: nowrap;
        }
        .pa-stat strong { color: var(--brand); }

        /* ── Search ── */
        .pa-search-wrap {
          position: relative;
          margin-bottom: 1.25rem;
        }
        .pa-search-icon {
          position: absolute;
          left: 0.75rem;
          top: 50%;
          transform: translateY(-50%);
          color: var(--muted);
          display: flex;
          align-items: center;
        }
        .pa-search {
          width: 100%;
          padding: 0.6rem 2.5rem 0.6rem 2.35rem;
          border: 1px solid var(--border);
          border-radius: 10px;
          background: var(--surface);
          color: var(--text);
          font-size: 0.9rem;
          outline: none;
          transition: border-color 0.15s;
        }
        .pa-search:focus { border-color: var(--brand); }
        .pa-search-clear {
          position: absolute;
          right: 0.65rem;
          top: 50%;
          transform: translateY(-50%);
          background: none;
          border: none;
          cursor: pointer;
          font-size: 1.1rem;
          color: var(--muted);
          padding: 0.1rem 0.35rem;
          border-radius: 50%;
          line-height: 1;
        }
        .pa-search-clear:hover { color: var(--text); }

        /* ── Cards ── */
        .pa-list { display: flex; flex-direction: column; gap: 0.75rem; }
        .pa-card {
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          overflow: hidden;
          box-shadow: var(--shadow);
        }
        .pa-card-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          width: 100%;
          padding: 0.85rem 1rem;
          background: none;
          border: none;
          cursor: pointer;
          color: var(--text);
          text-align: left;
          gap: 0.75rem;
        }
        .pa-card-header:hover { background: var(--surface-2); }
        .pa-card-header-left {
          display: flex;
          align-items: center;
          gap: 0.55rem;
          font-weight: 600;
          font-size: 0.95rem;
        }
        .pa-folder-icon { color: var(--brand); display: flex; align-items: center; }
        .pa-wo-label { font-family: "SF Mono", "Fira Code", monospace; }
        .pa-card-header-right {
          display: flex;
          align-items: center;
          gap: 0.4rem;
          flex-shrink: 0;
        }
        .pa-badge {
          background: rgba(11, 95, 255, 0.12);
          color: var(--brand);
          border-radius: 999px;
          padding: 0.15rem 0.55rem;
          font-size: 0.75rem;
          font-weight: 600;
        }
        .pa-badge-subtle {
          background: var(--surface-2);
          color: var(--muted);
        }
        .pa-chevron { color: var(--muted); display: flex; align-items: center; }

        /* ── Card body ── */
        .pa-card-body {
          border-top: 1px solid var(--border);
          padding: 0.5rem 0;
        }
        .pa-project {
          padding: 0.75rem 1rem;
        }
        .pa-project + .pa-project {
          border-top: 1px dashed var(--border);
        }
        .pa-project-header {
          display: flex;
          align-items: baseline;
          justify-content: space-between;
          gap: 0.5rem;
          margin-bottom: 0.6rem;
        }
        .pa-project-title {
          font-weight: 600;
          font-size: 0.9rem;
        }
        .pa-project-num {
          font-size: 0.75rem;
          color: var(--muted);
          background: var(--surface-2);
          border-radius: 6px;
          padding: 0.1rem 0.4rem;
          white-space: nowrap;
          flex-shrink: 0;
        }

        /* ── Task chips ── */
        .pa-tasks {
          display: flex;
          flex-wrap: wrap;
          gap: 0.4rem;
        }
        .pa-task-chip {
          display: inline-flex;
          align-items: center;
          gap: 0.3rem;
          background: var(--surface-2);
          border: 1px solid var(--border);
          border-radius: 8px;
          padding: 0.25rem 0.6rem;
          font-size: 0.78rem;
          color: var(--text);
          white-space: nowrap;
        }
        .pa-task-icon { color: var(--ok); display: flex; align-items: center; }
        .pa-task-id {
          font-family: "SF Mono", "Fira Code", monospace;
          font-size: 0.7rem;
          color: var(--muted);
          background: var(--bg);
          border-radius: 4px;
          padding: 0 0.3rem;
        }
        .pa-task-sep { color: var(--border); }
        .pa-no-tasks { margin: 0; font-size: 0.8rem; color: var(--muted); font-style: italic; }

        /* ── Loading ── */
        .pa-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 0.75rem;
          padding: 3rem;
          color: var(--muted);
          font-size: 0.9rem;
        }
        .pa-spinner {
          width: 28px; height: 28px;
          border: 3px solid var(--border);
          border-top-color: var(--brand);
          border-radius: 50%;
          animation: pa-spin 0.8s linear infinite;
        }
        @keyframes pa-spin { to { transform: rotate(360deg); } }

        /* ── Error / empty ── */
        .pa-error-box {
          background: rgba(220, 38, 38, 0.1);
          color: var(--danger);
          border: 1px solid rgba(220, 38, 38, 0.3);
          border-radius: var(--radius);
          padding: 0.85rem 1rem;
          font-size: 0.9rem;
        }
        .pa-empty {
          text-align: center;
          padding: 3rem 1rem;
          color: var(--muted);
        }
        .pa-empty-icon { font-size: 2.5rem; margin-bottom: 0.75rem; }
        .pa-empty-title { font-size: 1rem; font-weight: 600; color: var(--text); margin: 0 0 0.35rem; }
        .pa-empty-sub { font-size: 0.85rem; margin: 0; }
      `}</style>
    </div>
  );
}
