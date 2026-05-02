import { useEffect, useState } from 'react';
import { adminApi } from '@shared/api/admin';
import { useToast } from '@shared/context/useToast';
import { useConfirm } from '@shared/components/ConfirmDialog';
import L, { useL } from '@shared/components/L';

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
  const confirm = useConfirm();
  const { pick, lang } = useL();
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
      toast.error(pick({ ar: 'تعذّر تحميل أحداث Stripe', en: 'Failed to load Stripe events' }));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [filterType]);

  const onReplay = async (eventId) => {
    const ok = await confirm({
      ar: {
        title: 'إعادة تشغيل الحدث',
        message: `هل تريد إعادة تشغيل ${eventId}؟ المعالجات قابلة للتكرار — الإجراء آمن.`,
        confirm: 'إعادة',
        cancel: 'إلغاء',
      },
      en: {
        title: 'Replay event',
        message: `Replay ${eventId}? Handlers are idempotent — safe to retry.`,
        confirm: 'Replay',
        cancel: 'Cancel',
      },
    });
    if (!ok) return;
    setBusy(eventId);
    try {
      await adminApi.replayStripeEvent(eventId);
      toast.success(pick({ ar: `أُعيد تشغيل ${eventId}`, en: `Replayed ${eventId}` }));
    } catch (err) {
      toast.error(err.response?.data?.detail || pick({ ar: 'فشلت إعادة التشغيل', en: 'Replay failed' }));
    } finally {
      setBusy(null);
    }
  };

  const fmt = (iso) => new Date(iso).toLocaleString(
    lang === 'ar' ? 'ar-LB' : 'en-GB',
    {
      timeZone: 'Asia/Beirut',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    },
  );

  return (
    <div className="admin-page">
      <header className="admin-page__header">
        <div>
          <h1 className="admin-page__title">
            <L ar="أحداث Stripe" en="Stripe events" />
          </h1>
          <p className="admin-page__subtitle">
            <L
              ar="سجلّ الإشعارات الواردة من Stripe. تُعيد إعادة التشغيل تنفيذ المعالج على نفس الحمولة المحفوظة — العملية آمنة للتكرار ولا تؤثّر على حالة الطلب."
              en="Webhook ledger. Replay re-runs the handler against the stored payload — safe to retry, idempotent against case state."
            />
          </p>
        </div>
        <div className="admin-page__actions" style={{ display: 'flex', gap: '0.5rem' }}>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            style={{ padding: '0.4rem 0.6rem' }}
            aria-label={pick({ ar: 'تصفية حسب نوع الحدث', en: 'Filter by event type' })}
          >
            <option value="">{pick({ ar: 'جميع أنواع الأحداث', en: 'All event types' })}</option>
            <option value="checkout.session.completed">checkout.session.completed</option>
            <option value="checkout.session.expired">checkout.session.expired</option>
            <option value="payment_intent.payment_failed">payment_intent.payment_failed</option>
          </select>
          <button className="btn btn--outline btn--sm" onClick={load}>
            <L ar="تحديث" en="Refresh" />
          </button>
        </div>
      </header>

      {loading ? (
        <p><L ar="جارٍ التحميل…" en="Loading…" /></p>
      ) : events.length === 0 ? (
        <p><L ar="لا توجد أحداث Stripe مسجَّلة." en="No Stripe events recorded." /></p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="admin-table" style={{ width: '100%', fontSize: '0.85rem' }}>
            <thead>
              <tr>
                <th>{pick({ ar: 'تاريخ الاستلام', en: 'Received' })}</th>
                <th>{pick({ ar: 'معرّف الحدث', en: 'Event ID' })}</th>
                <th>{pick({ ar: 'النوع', en: 'Type' })}</th>
                <th>{pick({ ar: 'الطلب', en: 'Case' })}</th>
                <th>{pick({ ar: 'المبلغ', en: 'Amount' })}</th>
                <th>{pick({ ar: 'حالة الدفع', en: 'Payment status' })}</th>
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
                        title={replayable
                          ? pick({ ar: 'إعادة تشغيل المعالج', en: 'Re-run the handler' })
                          : pick({ ar: 'لا يوجد معالج مسجَّل لهذا النوع من الأحداث', en: 'No handler registered for this event type' })}
                      >
                        {busy === e.event_id
                          ? pick({ ar: 'جارٍ الإعادة…', en: 'Replaying…' })
                          : pick({ ar: 'إعادة', en: 'Replay' })}
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
        <L
          ar={<>متى تُستخدم إعادة التشغيل: عندما يفشل المعالج في منتصف المعاملة (انقطاع قاعدة البيانات أو خدمة خارجية) فيرى Stripe ردّاً ناجحاً (200) بينما لا تُنفَّذ التأثيرات الجانبية لدينا. كل إعادة تشغيل تُسجَّل في سجل التدقيق (<code>stripe_event_replayed</code>).</>}
          en={<>Replay use-cases: the handler errored mid-transition (DB blip, downstream service down) so Stripe sees 200 but our side-effects never ran. Each replay is recorded in the audit log (<code>stripe_event_replayed</code>).</>}
        />
      </p>
    </div>
  );
}
