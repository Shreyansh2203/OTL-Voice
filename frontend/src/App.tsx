import { useCallback, useState, useEffect } from "react";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "./api/client";
import LoginView from "./components/LoginView";
import ChatView from "./components/ChatView";
import type { Identity } from "./types";

function AppContent() {
  const qc = useQueryClient();
  
  const { data: identity, isLoading } = useQuery({
    queryKey: ["session"],
    queryFn: api.getSession,
  });

  const handleLogin = useCallback((user: Identity) => {
    qc.setQueryData(["session"], user);
  }, [qc]);

  const handleLogout = useCallback(async () => {
    await api.logout().catch(() => undefined);
    qc.setQueryData(["session"], null);
  }, [qc]);

  const handleSessionExpired = useCallback(() => {
    qc.setQueryData(["session"], null);
  }, [qc]);

  // Keep session alive while the user has the app open (proactive refresh every 15 mins)
  useEffect(() => {
    if (!identity) return;
    const interval = setInterval(() => {
      api.refreshSession().catch(() => handleSessionExpired());
    }, 1000 * 60 * 15); // Every 15 minutes
    return () => clearInterval(interval);
  }, [identity, handleSessionExpired]);

  if (isLoading) {
    return (
      <div className="centered">
        <div className="spinner" aria-label="Loading" />
      </div>
    );
  }

  if (!identity) {
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

export default function App() {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        retry: false, // Don't retry on 401s
        refetchOnWindowFocus: false,
      },
    },
  }));

  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}
