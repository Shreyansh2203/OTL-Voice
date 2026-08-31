import { useState } from 'react';
export default function ThinkingState({ reasoning }: { reasoning?: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="thinking-state-container">
      <div
        className="thinking-loader"
        onClick={() => reasoning && setExpanded(!expanded)}
        style={{ cursor: reasoning ? 'pointer' : 'default' }}
      >
        <div className="shimmer-grid">
          <div className="shimmer-dot"></div>
          <div className="shimmer-dot"></div>
          <div className="shimmer-dot"></div>
        </div>
        <span className="thinking-label">Thinking...</span>
        {reasoning && (
          <svg
            className={`chevron ${expanded ? 'expanded' : ''}`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        )}
      </div>
      {reasoning && expanded && (
        <div className="reasoning-trace">{reasoning}</div>
      )}
    </div>
  );
}
