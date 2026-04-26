import { useEffect, useRef } from 'react';

/**
 * Poll a case's state only while it's actively moving.
 *
 * The citizen submits → SUBMITTED → VALIDATED → RISK_EVALUATED →
 * APPROVED / PENDING_MUKHTAR — that whole pipeline finishes in a few
 * seconds in real life. Without polling the citizen has to refresh the
 * page to know it ran. With polling they see it flip live.
 *
 * Polling rules:
 *   - Only fire when status is in IN_FLIGHT_STATUSES below.
 *   - Pause when the tab is hidden (Page Visibility API). No point
 *     burning gateway requests for a tab the user isn't watching.
 *   - Stop polling when the status leaves the in-flight set (drafts,
 *     need_info — citizen is editing — and terminal states).
 *
 * Caller passes in the current status + a callback that re-fetches.
 * The callback is wrapped in a ref so its identity doesn't reset the
 * interval on every render.
 */

const IN_FLIGHT_STATUSES = new Set([
  'submitted',
  'validated',
  'risk_evaluated',
  'pending_mukhtar',
  'in_production',
]);

const DEFAULT_INTERVAL_MS = 4000;

export function useCasePolling(status, refresh, { intervalMs = DEFAULT_INTERVAL_MS } = {}) {
  const refreshRef = useRef(refresh);
  // Keep the ref pointed at the latest callback without resetting the
  // interval each render. Done in an effect (not during render) to
  // satisfy the React strict-mode rules.
  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  useEffect(() => {
    if (!status || !IN_FLIGHT_STATUSES.has(status)) return undefined;

    let timer = null;

    const tick = () => {
      if (document.visibilityState !== 'visible') return;
      refreshRef.current?.();
    };

    timer = setInterval(tick, intervalMs);

    // Catch up immediately when the tab becomes visible again so a
    // returning citizen doesn't wait for the next interval.
    const onVisibility = () => {
      if (document.visibilityState === 'visible') tick();
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [status, intervalMs]);
}
