import { createContext, useCallback, useEffect, useRef, useState } from 'react';

/**
 * App-wide toast notifications.
 *
 * Replaces the per-page setError / setSuccess + ephemeral .alert
 * pattern with a single stack rendered above all routes. One toast
 * per call, auto-dismisses after a tier-dependent timeout, dismissible
 * by click. Stack lives in the upper-end corner so it doesn't shove
 * page content around.
 *
 * Why a context (not a singleton in JS): we need re-renders when the
 * stack changes; a plain module-level array would not trigger them.
 *
 * The Provider also renders the stack itself — callers don't need to
 * mount anything, just call useToast() and fire toast.success(...) /
 * toast.error(...) etc.
 *
 * The actual hook is in ./useToast.js to keep this file
 * components-only (eslint react-refresh).
 */

// eslint-disable-next-line react-refresh/only-export-components
export const ToastContext = createContext(null);

const TIMEOUTS = {
  success: 3500,
  info: 4500,
  warning: 6000,
  error: 7000,
};

let _id = 0;
const nextId = () => ++_id;

function ToastStack({ toasts, dismiss }) {
  if (toasts.length === 0) return null;
  return (
    <div className="toast-stack" role="region" aria-live="polite" aria-label="Notifications">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`toast toast--${t.kind}`}
          role={t.kind === 'error' ? 'alert' : 'status'}
          onClick={() => dismiss(t.id)}
        >
          <div className="toast__body">{t.message}</div>
          <button
            type="button"
            className="toast__close"
            onClick={(e) => {
              e.stopPropagation();
              dismiss(t.id);
            }}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const tm = timers.current.get(id);
    if (tm) {
      clearTimeout(tm);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (kind, message, { duration } = {}) => {
      const id = nextId();
      setToasts((prev) => [...prev, { id, kind, message }]);
      const tm = setTimeout(() => dismiss(id), duration ?? TIMEOUTS[kind] ?? 4000);
      timers.current.set(id, tm);
      return id;
    },
    [dismiss],
  );

  // Clear all timers on unmount so the stack doesn't leak setTimeout
  // ids across HMR remounts in dev.
  useEffect(() => {
    const map = timers.current;
    return () => {
      map.forEach((tm) => clearTimeout(tm));
      map.clear();
    };
  }, []);

  const value = {
    success: (msg, opts) => push('success', msg, opts),
    error: (msg, opts) => push('error', msg, opts),
    info: (msg, opts) => push('info', msg, opts),
    warning: (msg, opts) => push('warning', msg, opts),
    dismiss,
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastStack toasts={toasts} dismiss={dismiss} />
    </ToastContext.Provider>
  );
}
