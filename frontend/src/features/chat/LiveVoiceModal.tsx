import { FC } from 'react';
import { MicIcon, StopIcon } from '../../components/ui/icons';
import { LiveVoiceState, ToolExecutionEvent } from '../../lib/useGeminiLive';

export interface LiveVoiceModalProps {
  isOpen: boolean;
  liveState: LiveVoiceState;
  errorMsg: string | null;
  transcript: string;
  toolCalls: ToolExecutionEvent[];
  isMuted: boolean;
  onToggleMute: () => void;
  onClose: () => void;
}

export const LiveVoiceModal: FC<LiveVoiceModalProps> = ({
  isOpen,
  liveState,
  errorMsg,
  transcript,
  toolCalls,
  isMuted,
  onToggleMute,
  onClose,
}) => {
  if (!isOpen) return null;

  const getStatusLabel = () => {
    if (isMuted) return 'Microphone Muted';
    switch (liveState) {
      case 'connecting':
        return 'Connecting to Gemini Live…';
      case 'listening':
        return 'Listening… (Speak naturally)';
      case 'thinking':
        return 'Processing…';
      case 'speaking':
        return 'Assistant Speaking (Speak to interrupt)';
      default:
        return 'Ready';
    }
  };

  return (
    <div
      className="live-voice-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Gemini Live Voice Session"
    >
      <div className="live-voice-container">
        {/* Header */}
        <div className="live-voice-header">
          <div className="live-badge">
            <span className="live-indicator-dot" />
            <span className="live-badge-text">GEMINI LIVE MULTIMODAL</span>
          </div>
          <button
            type="button"
            className="live-close-btn"
            onClick={onClose}
            aria-label="Close Live Session"
          >
            ✕
          </button>
        </div>

        {/* Visualizer Orb */}
        <div className="live-voice-center">
          <div
            className={`live-voice-orb ${liveState} ${isMuted ? 'muted' : ''}`}
          >
            <div className="orb-inner-glow" />
            <div className="orb-ring ring-1" />
            <div className="orb-ring ring-2" />
            <div className="orb-ring ring-3" />
            <div className="orb-core" />
          </div>

          <div className="live-status-label">{getStatusLabel()}</div>

          {errorMsg && (
            <div className="live-error-banner" role="alert">
              {errorMsg}
            </div>
          )}

          {/* Real-time Subtitles / Transcript */}
          {transcript && (
            <div className="live-transcript-box">
              <p className="live-transcript-text">{transcript}</p>
            </div>
          )}

          {/* Real-time Tool Execution Notifications */}
          {toolCalls.length > 0 && (
            <div className="live-tools-container">
              {toolCalls.map((t, idx) => (
                <div key={idx} className="live-tool-chip">
                  <span className="tool-icon">⚡</span>
                  <span className="tool-name">
                    {t.name === 'submit_timecard'
                      ? 'Logged Timecard to OTL'
                      : t.name}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Bottom Action Controls */}
        <div className="live-voice-footer">
          <button
            type="button"
            className={`live-action-btn mute-btn ${isMuted ? 'active' : ''}`}
            onClick={onToggleMute}
            aria-label={isMuted ? 'Unmute microphone' : 'Mute microphone'}
            title={isMuted ? 'Unmute' : 'Mute'}
          >
            {isMuted ? <MicIcon /> : <StopIcon />}
            <span>{isMuted ? 'Unmute' : 'Mute'}</span>
          </button>

          <button
            type="button"
            className="live-action-btn end-btn"
            onClick={onClose}
            aria-label="End conversation session"
          >
            End Session
          </button>
        </div>
      </div>
    </div>
  );
};

export default LiveVoiceModal;
