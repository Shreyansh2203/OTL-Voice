import React from 'react';

export type VoiceOrbState = 'idle' | 'listening' | 'thinking' | 'speaking';

export interface VoiceOrbProps {
  state: VoiceOrbState;

  level?: number;
  size?: number;
  ringRef?: React.Ref<HTMLSpanElement>;
}

export default function VoiceOrb({
  state,
  level = 0,
  size = 14,
  ringRef,
}: VoiceOrbProps) {
  // Ring scale reacts to live amplitude only in the listening state so the
  // orb visibly "hears" the user, rather than just showing a generic pulse.
  const ringScale = state === 'listening' ? 1 + Math.min(level, 1) * 0.9 : 1;

  return (
    <span
      className={`voice-orb voice-orb--${state}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <span
        ref={ringRef}
        className="voice-orb-ring"
        style={{ transform: `scale(${ringScale})` }}
      />
      <span className="voice-orb-core" />
    </span>
  );
}
