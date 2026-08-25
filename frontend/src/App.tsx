import { useCallback, useState, useEffect } from "react";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "./api/client";
import LoginView from "./components/LoginView";
import ChatView from "./components/ChatView";
import type { Identity } from "./types";
function AppContent() {
  const qc = useQueryClient();
  const { data: identity, isLoading, error: _error } = useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      try {
        return await api.getSession();
      } catch (err) {
        if (err instanceof api.ApiError && err.status === 401) {
          return null;
        }
        throw err;
      }
    },
    retry: false,
    refetchOnWindowFocus: false,
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
  useEffect(() => {
    if (!identity) return;
    const baseInterval = 1000 * 60 * 15; 
    const jitter = Math.random() * 1000 * 60 * 2; 
    const interval = setInterval(() => {
      api.refreshSession().catch(() => handleSessionExpired());
    }, baseInterval + jitter);
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
        retry: false, 
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