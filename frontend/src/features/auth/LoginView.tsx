import { FormEvent, useState } from 'react';
import * as api from '../../api/client';
import type { Identity } from '../../types';
import SpotlightCard from '../../components/ui/SpotlightCard';
import BlurText from '../../components/ui/BlurText';

export default function LoginView({
  onLogin,
}: {
  onLogin: (identity: Identity) => void;
}) {
  const [username, setUsername] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      onLogin(await api.login(username.trim(), ''));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="centered" style={{ position: 'relative', overflow: 'hidden' }}>
      <SpotlightCard className="login" spotlightColor="rgba(255, 255, 255, 0.15)">
        <form className="card" onSubmit={submit} style={{ zIndex: 1, position: 'relative', border: 'none', background: 'transparent', boxShadow: 'none' }}>
          <div className="brand">
            <img src="/favicon.svg" alt="" width={44} height={44} />
            <div>
              <BlurText text="OTL Timesheet Assistant" delay={40} className="h1-replacement" animateBy="words" />
              <p className="muted">Sign in with your employee credentials.</p>
            </div>
          </div>
        <label>
          <span>Person Number</span>
          <input
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="e.g. 7"
            required
            autoFocus
          />
        </label>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <button className="primary" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="muted small">
          Your Person Number is checked securely against Oracle Fusion Cloud.
          The browser only keeps a session cookie.
        </p>
        </form>
      </SpotlightCard>
    </div>
  );
}
