import { MicIcon } from "./icons";

export interface ListeningOverlayProps {
  listening: boolean;
  text: string;
  level: number; // 0 to 1
  onStop: () => void;
}

export default function ListeningOverlay({
  listening,
  text,
  level,
  onStop,
}: ListeningOverlayProps) {
  if (!listening) return null;

  // Scale height based on audio level
  const baseScale = 0.3;
  const s1 = Math.max(baseScale, level * 1.5 + baseScale);
  const s2 = Math.max(baseScale, level * 2.2 + baseScale);
  const s3 = Math.max(baseScale, level * 1.8 + baseScale);
  const s4 = Math.max(baseScale, level * 1.3 + baseScale);

  return (
    <div className="google-mic-overlay">
      <div className="google-mic-header">
        <button onClick={onStop} className="icon-btn" aria-label="Close">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5M12 19l-7-7 7-7"/>
          </svg>
        </button>
        <div className="language-pill">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{marginRight: 6}}>
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="2" y1="12" x2="22" y2="12"></line>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
          </svg>
          English
        </div>
        <button className="icon-btn" aria-label="Menu">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="5" r="1"></circle>
            <circle cx="12" cy="12" r="1"></circle>
            <circle cx="12" cy="19" r="1"></circle>
          </svg>
        </button>
      </div>

      <div className="google-mic-body">
        <h2 className={`transcript-text ${text ? "active" : ""}`}>
          {text || "Listening..."}
        </h2>

        <div className="equalizer-container">
          <div className="equalizer-bar" style={{ transform: `scaleY(${s1})` }} />
          <div className="equalizer-bar" style={{ transform: `scaleY(${s2})` }} />
          <div className="equalizer-bar" style={{ transform: `scaleY(${s3})` }} />
          <div className="equalizer-bar" style={{ transform: `scaleY(${s4})` }} />
        </div>

        <div className="auto-submit-badge">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
          Auto search on
        </div>
      </div>

      <div className="google-mic-footer">
        <button className="nav-item">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
          <span>Search</span>
        </button>
        <button className="nav-item active">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
          <span>AI Mode</span>
        </button>
        <button className="nav-item" onClick={onStop} aria-label="Stop recording">
          <MicIcon size={24} />
          <span>Talk</span>
        </button>
        <button className="nav-item">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18V5l12-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="18" cy="16" r="3"></circle></svg>
          <span>Song</span>
        </button>
      </div>
    </div>
  );
}
