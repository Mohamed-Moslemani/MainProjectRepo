import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import * as Sentry from '@sentry/react';
import '@shared/styles/index.css';
import App from './App.jsx';

// Sentry / GlitchTip — initialised only when a DSN is provided. The
// SDK works against both since GlitchTip implements the Sentry
// protocol; pointing VITE_SENTRY_DSN at http://localhost:8005/<id>
// or at a SaaS Sentry project both work without code changes.
const dsn = import.meta.env.VITE_SENTRY_DSN;
if (dsn) {
  Sentry.init({
    dsn,
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
