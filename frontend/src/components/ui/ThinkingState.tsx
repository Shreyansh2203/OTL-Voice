import { useId, useState } from 'react';
export default function ThinkingState({ reasoning }: { reasoning?: string }) {
  const [expanded, setExpanded] = useState(false);
  const traceId = useId();
  if (!reasoning) {
    return (
      <div className="thinking-state-container">
        <div className="thinking-loader" style={{ cursor: 'default' }}>
          <div className="shimmer-grid">
            <div className="shimmer-dot"></div>
            <div className="shimmer-dot"></div>
            <div className="shimmer-dot"></div>
          </div>
          <span className="thinking-label">Thinking...</span>
        </div>
      </div>
    );
  }
  return (
    <div className="thinking-state-container">
      <button
        type="button"
        className="thinking-loader"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
        aria-controls={traceId}
      >
        <div className="shimmer-grid">
          <div className="shimmer-dot"></div>
          <div className="shimmer-dot"></div>
          <div className="shimmer-dot"></div>
        </div>
        <span className="thinking-label">Thinking...</span>
        <svg
          className={`chevron ${expanded ? 'expanded' : ''}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {expanded && (
        <div className="reasoning-trace" id={traceId}>
          {reasoning}
        </div>
      )}
    </div>
  );
}
