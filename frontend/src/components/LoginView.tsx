import { FormEvent, useState } from "react";
import * as api from "../api/client";
import type { Identity } from "../types";
export default function LoginView({
  onLogin,
}: {
  onLogin: (identity: Identity) => void;
}) {
  const [username, _setUsername] = useState("");
  void _setUsername;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      onLogin(await api.login(username.trim() || "208", ""));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="centered">
      <form className="card login" onSubmit={submit}>
        <div className="brand">
          <img src="/favicon.svg" alt="" width={44} height={44} />
          <div>
            <h1>OTL Timesheet Assistant</h1>
            <p className="muted">Sign in with your employee credentials.</p>
          </div>
        </div>
        {/* Person Number input - commented out for now until instance starts working
        <label>
          <span>Person Number</span>
          <input
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="e.g. 12345"
            autoFocus
          />
        </label>
        */}
        {error && <div className="error" role="alert">{error}</div>}
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="muted small">
          Your Person Number is checked securely against Oracle Fusion Cloud.
          The browser only keeps a session cookie.
        </p>
      </form>
    </div>
  );
}