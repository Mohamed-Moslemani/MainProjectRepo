import { useEffect, useState } from 'react';
import { adminApi } from '../../api/admin';
import { useToast } from '../../context/useToast';

// Stripe webhook ledger + manual replay.
//
// We persist every webhook delivery in the `stripe_events` table on
// receive. Stripe stops retrying once it sees a 200 from us, so if
// the handler later errors *after* persisting the row, the
// downstream side-effects (case → IN_PRODUCTION, audit log, email)
// never run. This page lets an admin re-invoke the handler against
// the stored payload — handlers are idempotent against the case
// state machine, so replay is safe to retry.
export default function AdminStripeEvents() {
  const toast = useToast();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);
  const [filterType, setFilterType] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const params = {};
      if (filterType) params.event_type = filterType;
      const { data } = await adminApi.listStripeEvents(params);
      setEvents(data.events || []);
    } catch {
      toast.error('Failed to load Stripe events');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [filterType]);

  const onReplay = async (eventId) => {
    if (!window.confirm(`Replay ${eventId}? Handlers are idempotent — safe to retry.`)) return;
    setBusy(eventId);
    try {
      await adminApi.replayStripeEvent(eventId);
      toast.success(`Replayed ${eventId}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Replay failed');
    } finally {
      setBusy(null);
    }
  };

  const fmt = (iso) => new Date(iso).toLocaleString('en-GB', {
    timeZone: 'Asia/Beirut',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });

  return (
    <div className="admin-page">
      <header className="admin-page__header">
        <div>
          <h1 className="admin-page__title">Stripe events</h1>
          <p className="admin-page__subtitle">
            Webhook ledger. Replay re-runs the handler against the stored
            payload — safe to retry, idempotent against case state.
          </p>
        </div>
        <div className="admin-page__actions" style={{ display: 'flex', gap: '0.5rem' }}>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            style={{ padding: '0.4rem 0.6rem' }}
          >
            <option value="">All event types</option>
            <option value="checkout.session.completed">checkout.session.completed</option>
            <option value="checkout.session.expired">checkout.session.expired</option>
            <option value="payment_intent.payment_failed">payment_intent.payment_failed</option>
          </select>
          <button className="btn btn--outline btn--sm" onClick={load}>
            Refresh
          </button>
        </div>
      </header>

      {loading ? (
        <p>Loading…</p>
      ) : events.length === 0 ? (
        <p>No Stripe events recorded.</p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="admin-table" style={{ width: '100%', fontSize: '0.85rem' }}>
            <thead>
              <tr>
                <th>Received</th>
                <th>Event ID</th>
                <th>Type</th>
                <th>Case</th>
                <th>Amount</th>
                <th>Payment status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => {
                const replayable = [
                  'checkout.session.completed',
                  'checkout.session.expired',
                  'payment_intent.payment_failed',
                ].includes(e.event_type);
                const amount = e.payload_summary?.amount_total;
                return (
                  <tr key={e.event_id}>
                    <td style={{ whiteSpace: 'nowrap' }}>{fmt(e.received_at)}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{e.event_id}</td>
                    <td>{e.event_type}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>
                      {e.case_id || '—'}
                    </td>
                    <td>{amount != null ? `$${(amount / 100).toFixed(2)}` : '—'}</td>
                    <td>{e.payload_summary?.payment_status || '—'}</td>
                    <td>
                      <button
                        className="btn btn--sm btn--outline"
                        disabled={!replayable || busy === e.event_id}
                        onClick={() => onReplay(e.event_id)}
                        title={replayable ? 'Re-run the handler' : 'No handler registered for this event type'}
                      >
                        {busy === e.event_id ? 'Replaying…' : 'Replay'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p style={{ marginTop: '1rem', fontSize: '0.85rem', color: '#6b7280' }}>
        Replay use-cases: the handler errored mid-transition (DB blip,
        downstream service down) so Stripe sees 200 but our side-effects
        never ran. Each replay is recorded in the audit log
        (<code>stripe_event_replayed</code>).
      </p>
    </div>
  );
}
