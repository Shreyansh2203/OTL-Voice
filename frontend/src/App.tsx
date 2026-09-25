import { useCallback, useState, useEffect } from 'react';
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import * as api from './api/client';
import { LoginView } from './features/auth';
import { ChatView } from './features/chat';
import ErrorBoundary from './components/ErrorBoundary';
import type { Identity } from './types';

function AppContent() {
  const qc = useQueryClient();
  const { data: identity, isLoading, isError, refetch } = useQuery({
    queryKey: ['session'],
    queryFn: api.getSession,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const [sessionRevoked, setSessionRevoked] = useState(false);
  const handleLogin = useCallback(
    (user: Identity) => {
      setSessionRevoked(false);
      qc.setQueryData(['session'], user);
    },
    [qc]
  );
  const handleLogout = useCallback(async () => {
    await api.logout();
    qc.clear();
    qc.setQueryData(['session'], null);
    setSessionRevoked(true);
  }, [qc]);
  const handleSessionExpired = useCallback(() => {
    qc.clear();
    qc.setQueryData(['session'], null);
    setSessionRevoked(true);
  }, [qc]);
  useEffect(() => {
    if (!identity) return;
    const baseInterval = 1000 * 60 * 15;
    const jitter = Math.random() * 1000 * 60 * 2;
    const interval = setInterval(() => {
      api.refreshSession().catch((err) => {
        if (err instanceof api.ApiError && err.status === 401) {
          handleSessionExpired();
        }
      });
    }, baseInterval + jitter);
    return () => clearInterval(interval);
  }, [identity, handleSessionExpired]);
  if (sessionRevoked) {
    return <LoginView onLogin={handleLogin} />;
  }
  if (isLoading) {
    return (
      <div className="centered">
        <div className="spinner" aria-label="Loading" />
      </div>
    );
  }
  if (isError && !identity) {
    return (
      <div className="centered">
        <div className="error" role="alert">
          Unable to verify your session. Please try again.
        </div>
        <button type="button" onClick={() => void refetch()}>
          Try again
        </button>
      </div>
    );
  }
  if (!identity) {
    return <LoginView onLogin={handleLogin} />;
  }
  return (
    <ChatView
      username={identity.fullName}
      employeeNumber={identity.employeeId}
      onLogout={handleLogout}
      onSessionExpired={handleSessionExpired}
    />
  );
}
export default function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            refetchOnWindowFocus: false,
          },
        },
      })
  );
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <div
          aria-hidden="true"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: -1,
            background:
              'radial-gradient(ellipse at top, #1b0a33 0%, #0b0618 55%, #050014 100%)',
          }}
        />
        <AppContent />
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
