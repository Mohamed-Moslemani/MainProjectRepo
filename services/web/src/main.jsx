import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import * as Sentry from '@sentry/react';
import '@shared/styles/index.css';
import '@shared/i18n';                  // initialises i18next before App renders
import App from './App.jsx';

// Sentry / GlitchTip — initialised only when a DSN is provided. The
// SDK works against both since GlitchTip implements the Sentry
// protocol; pointing VITE_SENTRY_DSN at http://localhost:8005/<id>
// or at a SaaS Sentry project both work without code changes.
//
// `tunnel` routes envelopes through our own gateway at
// /api/v1/sentry-tunnel instead of hitting *.ingest.sentry.io
// directly. ~30 % of users run an ad-blocker that drops Sentry
// requests on sight; same-origin POSTs go through. The gateway
// validates the envelope's DSN against an allowlist before forwarding.
const dsn = import.meta.env.VITE_SENTRY_DSN;
if (dsn) {
  const apiBase = import.meta.env.VITE_API_URL || '';
  Sentry.init({
    dsn,
    tunnel: `${apiBase}/api/v1/sentry-tunnel`,
    environment: import.meta.env.MODE,
    release: import.meta.env.VITE_GIT_SHA || 'dev',
    // Don't double-cost on traces — backend OTel already covers
    // pipeline timing. Frontend is errors-only.
    tracesSampleRate: 0,
    sendDefaultPii: false,
  });
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>
);
