export type VoiceOrbState = "idle" | "listening" | "thinking" | "speaking";

export interface VoiceOrbProps {
  state: VoiceOrbState;
  /** Live mic amplitude 0-1, only meaningful while listening. */
  level?: number;
  size?: number;
}

/**
 * A small animated indicator that gives the assistant a physical presence —
 * it breathes at idle, swells with the user's voice while listening, spins
 * gently while thinking, and pulses in rhythm while speaking.
 */
export default function VoiceOrb({ state, level = 0, size = 14 }: VoiceOrbProps) {
  // Ring scale reacts to live amplitude only in the listening state so the
  // orb visibly "hears" the user, rather than just showing a generic pulse.
  const ringScale = state === "listening" ? 1 + Math.min(level, 1) * 0.9 : 1;

  return (
    <span
      className={`voice-orb voice-orb--${state}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <span
        className="voice-orb-ring"
        style={{ transform: `scale(${ringScale})` }}
      />
      <span className="voice-orb-core" />
    </span>
  );
}
