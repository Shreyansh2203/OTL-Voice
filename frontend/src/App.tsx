import { useCallback, useEffect, useState } from "react";
import * as api from "./api/client";
import LoginView from "./components/LoginView";
import ChatView from "./components/ChatView";
import type { Identity } from "./types";

type Phase = "loading" | "signed-out" | "signed-in";

export default function App() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [identity, setIdentity] = useState<Identity | null>(null);

  // Bypass login check for testing
  useEffect(() => {
    setIdentity({ username: "test.user", employeeId: "90407", fullName: "Test User (Bypass)" });
    setPhase("signed-in");
  }, []);

  const handleLogin = useCallback((user: Identity) => {
    setIdentity(user);
    setPhase("signed-in");
  }, []);

  const handleLogout = useCallback(async () => {
    await api.logout().catch(() => undefined);
    setIdentity(null);
    setPhase("signed-out");
  }, []);

  // Any protected call returning 401 bubbles up here to force re-login.
  const handleSessionExpired = useCallback(() => {
    setIdentity(null);
    setPhase("signed-out");
  }, []);

  if (phase === "loading") {
    return (
      <div className="centered">
        <div className="spinner" aria-label="Loading" />
      </div>
    );
  }

  if (phase === "signed-out" || identity === null) {
    return <LoginView onLogin={handleLogin} />;
  }

  return (
    <ChatView
      username={identity.fullName}
      onLogout={handleLogout}
      onSessionExpired={handleSessionExpired}
    />
  );
}
