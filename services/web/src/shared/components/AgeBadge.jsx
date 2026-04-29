/**
 * Compact "case age + SLA" badge.
 *
 * Shows how long ago a case was created, with a colour cue based on
 * how concerning the age is. Officers / mukhtars use it to triage —
 * a 3-day-old passport-renewal case in pending_mukhtar is more
 * urgent than one that arrived an hour ago.
 *
 * Tier thresholds (in hours):
 *   < 24h    → green   "fresh"
 *   24–72h   → amber   "aging"
 *   ≥ 72h    → red     "overdue"
 *
 * Tiers are intentionally generic (not service-type-specific) for
 * v1 — once we have real SLAs per service, plumb the per-service
 * thresholds through props.
 */

const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;

function tierFor(ageMs) {
  if (ageMs < DAY) return { color: 'green', label: { ar: 'جديد', en: 'Fresh' } };
  if (ageMs < 3 * DAY) return { color: 'orange', label: { ar: 'قيد الانتظار', en: 'Aging' } };
  return { color: 'red', label: { ar: 'متأخر', en: 'Overdue' } };
}

function humanAge(ageMs) {
  if (ageMs < HOUR) return `${Math.max(1, Math.round(ageMs / 60000))}m`;
  if (ageMs < DAY) return `${Math.round(ageMs / HOUR)}h`;
  return `${Math.round(ageMs / DAY)}d`;
}

import { useEffect, useState } from 'react';

export default function AgeBadge({ createdAt }) {
  // Refresh once a minute so a card sitting on screen ticks up from
  // "5m" to "6m" without a page reload. Initial state is computed in
  // an effect to keep the render pure (no Date.now() during render).
  const [now, setNow] = useState(null);
  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) setNow(Date.now());
    });
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  if (!createdAt || now == null) return null;
  const ageMs = now - new Date(createdAt).getTime();
  if (ageMs < 0 || Number.isNaN(ageMs)) return null;
  const tier = tierFor(ageMs);
  return (
    <span
      className={`status-badge status-badge--${tier.color}`}
      title={`${tier.label.en} · created ${new Date(createdAt).toLocaleString('en-GB')}`}
      style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}
    >
      {humanAge(ageMs)}
    </span>
  );
}
