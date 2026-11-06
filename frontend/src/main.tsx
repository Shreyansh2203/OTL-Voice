import React from 'react';
import ReactDOM from 'react-dom/client';
import { registerSW } from 'virtual:pwa-register';
import * as Sentry from '@sentry/react';
import App from './App';
import { DENY_URLS, scrubEvent, scrubTransaction } from './lib/sentryPrivacy';
import './index.css';

if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    integrations: [
      Sentry.browserTracingIntegration(),
      // Session replay records every DOM mutation, which for this app would
      // include the Oracle person number and the whole timesheet conversation.
      // It stays installed but unsampled: if the rates below are ever raised,
      // text and media are already masked by default.
      Sentry.replayIntegration({
        maskAllText: true,
        blockAllMedia: true,
      }),
    ],
    // Explicitly opt out of Sentry's default PII collection. `sendDefaultPii`
    // is deprecated in v10 and removed in v11, so the per-category
    // `dataCollection` block below is the durable form of the same intent.
    sendDefaultPii: false,
    dataCollection: {
      userInfo: false,
      cookies: false,
      httpHeaders: false,
      httpBodies: [],
      urlQueryParams: false,
      graphQL: { document: false, variables: false },
      genAI: { inputs: false, outputs: false },
      databaseQueryData: false,
      stackFrameVariables: false,
    },
    tracesSampleRate: 1.0,
    // Replay is disabled. Tradeoff: no visual reproduction of a frontend bug
    // report. In exchange no keystroke-adjacent UI or employee timesheet text
    // is ever recorded, which is the same posture the backend takes by
    // dropping all breadcrumbs.
    replaysSessionSampleRate: 0.0,
    replaysOnErrorSampleRate: 0.0,
    denyUrls: DENY_URLS,
    beforeSend: (event) => scrubEvent(event),
    beforeSendTransaction: (event) => scrubTransaction(event),
  });
}

registerSW({ immediate: true });
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
