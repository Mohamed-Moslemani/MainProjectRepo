import { useEffect, useRef, useState, useCallback } from 'react';
import { useAuth } from '@shared/context/useAuth';

/**
 * Idle session expiry with a "still there?" warning.
 *
 * Citizens / officers leave laptops at cafés and lunch tables. If a
 * session sits open for an hour with no input, anyone walking by can
 * grab it. We can't blow up the session immediately on the first
 * minute of inactivity — that's hostile UX — so we use a two-stage
 * timer:
 *
 *   - 13 minutes idle → modal: "you'll be logged out in 2 minutes,
 *     click anywhere to stay signed in".
 *   - +2 minutes with no further input → logout + redirect to login.
 *
 * Any of pointer / keyboard / scroll events resets the timer. The
 * "stay signed in" button on the modal also resets. Once logged out,
 * the auth axios interceptor handles the redirect on the next 401.
 *
 * Mounted unconditionally inside AuthProvider's tree but the effect
 * is a no-op when no user is present, so public pages aren't
 * affected.
 */

const IDLE_WARN_MS = 13 * 60 * 1000;
const IDLE_LOGOUT_MS = 15 * 60 * 1000;
const ACTIVITY_EVENTS = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart'];

export default function IdleLogout() {
  const { user, logout } = useAuth();
  const [warning, setWarning] = useState(false);
  // Initialised in the useEffect below — keeping render pure (no
  // Date.now() during the body of the component).
  const lastActivity = useRef(0);
  const warnTimer = useRef(null);
  const logoutTimer = useRef(null);

  const armTimers = useCallback(() => {
    if (warnTimer.current) clearTimeout(warnTimer.current);
    if (logoutTimer.current) clearTimeout(logoutTimer.current);
    warnTimer.current = setTimeout(() => setWarning(true), IDLE_WARN_MS);
    logoutTimer.current = setTimeout(() => {
      logout();
      window.location.href = '/login?reason=idle';
    }, IDLE_LOGOUT_MS);
  }, [logout]);

  const dismiss = useCallback(() => {
    setWarning(false);
    lastActivity.current = Date.now();
    armTimers();
  }, [armTimers]);

  useEffect(() => {
    if (!user) return undefined;

    lastActivity.current = Date.now();
    armTimers();

    const onActivity = () => {
      lastActivity.current = Date.now();
      // Don't re-arm on every mouse movement — only when we're not
      // already in the warning state (so dismiss happens via the
      // explicit modal click). Saves O(n) timer churn.
      if (!warning) armTimers();
    };

    ACTIVITY_EVENTS.forEach((evt) => window.addEventListener(evt, onActivity, { passive: true }));

    return () => {
      ACTIVITY_EVENTS.forEach((evt) => window.removeEventListener(evt, onActivity));
      if (warnTimer.current) clearTimeout(warnTimer.current);
      if (logoutTimer.current) clearTimeout(logoutTimer.current);
    };
  }, [user, warning, armTimers]);

  if (!user || !warning) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="idle-warning-title"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.5)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 300,
      }}
    >
      <div
        style={{
          background: '#fff',
          borderRadius: 12,
          padding: '1.75rem 2rem',
          maxWidth: 460,
          width: '90%',
          boxShadow: '0 16px 40px rgba(0,0,0,0.25)',
          fontFamily: 'system-ui, sans-serif',
        }}
      >
        <h2 id="idle-warning-title" style={{ marginTop: 0, fontSize: '1.2rem' }}>
          <span lang="ar" dir="rtl" style={{ display: 'block' }}>
            هل ما زلت معنا؟
          </span>
          <span lang="en" style={{ fontSize: '0.95rem', color: '#6b7280' }}>
            Are you still there?
          </span>
        </h2>
        <p style={{ color: '#374151', lineHeight: 1.55 }}>
          <span lang="ar" dir="rtl" style={{ display: 'block' }}>
            سيتم تسجيل خروجك تلقائياً بعد دقيقتين بسبب عدم النشاط.
          </span>
          <span lang="en">
            You'll be logged out automatically in 2 minutes due to inactivity.
          </span>
        </p>
        <div style={{ display: 'flex', gap: '0.6rem', marginTop: '1.25rem', justifyContent: 'flex-end' }}>
          <button
            type="button"
            onClick={() => {
              logout();
              window.location.href = '/login';
            }}
            style={{
              padding: '0.55rem 1rem',
              background: '#fff',
              color: '#374151',
              border: '1px solid #d1d5db',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            <span lang="ar">تسجيل الخروج</span>
            <span lang="en"> · Log out</span>
          </button>
          <button
            type="button"
            onClick={dismiss}
            autoFocus
            style={{
              padding: '0.55rem 1rem',
              background: '#16a34a',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            <span lang="ar">البقاء متصلاً</span>
            <span lang="en"> · Stay signed in</span>
          </button>
        </div>
      </div>
    </div>
  );
}
