import { useEffect, useState } from 'react';
import { useParams, useNavigate, useSearchParams, Link } from 'react-router-dom';
import { casesApi } from '@shared/api/cases';
import flagImg from '@shared/assets/Figure_1.png';
import '@shared/styles/dashboard.css';
import L from '@shared/components/L';
import { useL } from '@shared/hooks/useL';

const STATUS_MAP = {
  draft: { ar: 'مسودة', en: 'Draft', color: 'gray' },
  submitted: { ar: 'قيد المراجعة', en: 'Submitted', color: 'blue' },
  validated: { ar: 'تم التحقق', en: 'Validated', color: 'blue' },
  risk_evaluated: { ar: 'تم تقييم المخاطر', en: 'Risk Evaluated', color: 'orange' },
  approved: { ar: 'موافق عليه', en: 'Approved', color: 'green' },
  payment_pending: { ar: 'بانتظار الدفع', en: 'Payment Pending', color: 'orange' },
  rejected: { ar: 'مرفوض', en: 'Rejected', color: 'red' },
  need_info: { ar: 'بحاجة لمعلومات', en: 'Needs Info', color: 'orange' },
  pending_mukhtar: { ar: 'بانتظار المختار', en: 'Pending Mukhtar', color: 'orange' },
  in_production: { ar: 'قيد الإنتاج', en: 'In Production', color: 'blue' },
  ready_for_pickup: { ar: 'جاهز للاستلام', en: 'Ready for Pickup', color: 'green' },
  closed: { ar: 'مغلق', en: 'Closed', color: 'gray' },
};

/**
 * Public, no-login tracking page.
 *
 * Two entry points:
 *   /track                    → empty form, citizen types/pastes a tracking ID
 *   /track/:trackingId        → fetch immediately on mount
 *
 * The backend route /cases/track/{tracking_id} is already public, so we
 * just hit it without an Authorization header. We deliberately show
 * only the timeline + current status + service type — no PII, no
 * declared fields, no documents. Anyone with the tracking ID gets the
 * same view; the ID itself is the access token.
 */
export default function PublicTrack() {
  const { trackingId: routeId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const { pick } = useL();
  const initialId = routeId || searchParams.get('id') || '';
  const [input, setInput] = useState(initialId);
  const [tracking, setTracking] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!routeId) return undefined;
    let cancelled = false;

    // Defer state mutations + the network call to a microtask so
    // React doesn't see the setState as happening synchronously
    // inside the effect's render-phase body.
    queueMicrotask(() => {
      if (cancelled) return;
      setLoading(true);
      setError('');
      casesApi
        .trackByTrackingId(routeId)
        .then(({ data }) => {
          if (!cancelled) setTracking(data);
        })
        .catch((err) => {
          if (cancelled) return;
          if (err.response?.status === 404) {
            setError(pick({
              ar: 'لم يتم العثور على طلب بهذا الرقم. تحقق من صحة الرقم وحاول مجدداً.',
              en: 'No application found for this tracking ID. Check the number and try again.',
            }));
          } else {
            setError(pick({
              ar: 'تعذر تحميل بيانات التتبع. حاول لاحقاً.',
              en: 'Could not load tracking data. Please try again later.',
            }));
          }
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    });

    return () => {
      cancelled = true;
    };
  }, [routeId]);

  const onSubmit = (e) => {
    e.preventDefault();
    const id = input.trim().toUpperCase();
    if (!id) return;
    navigate(`/track/${encodeURIComponent(id)}`);
  };

  const st = tracking ? STATUS_MAP[tracking.current_status] || { ar: '', en: '', color: 'gray' } : null;

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div className="dashboard-header__inner">
          <div className="dashboard-header__brand">
            <img src={flagImg} alt="" className="dashboard-header__flag" />
            <div>
              <h1 className="dashboard-header__title"><L ar="تتبع الطلب" en="Track your application" /></h1>
            </div>
          </div>
          <div className="dashboard-header__actions">
            <Link to="/login" className="btn btn--outline btn--sm">
              <L ar="تسجيل الدخول" en="· Login" />
            </Link>
          </div>
        </div>
      </header>

      <main className="dashboard-main" style={{ maxWidth: 720 }}>
        <section className="detail-section">
          <h2>
            <L ar="أدخل رقم التتبع" en="Enter tracking ID" />
          </h2>
          <form onSubmit={onSubmit} style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="DFL-XXXXXXXX"
              aria-label={pick({ ar: 'رقم التتبع', en: 'Tracking ID' })}
              dir="ltr"
              style={{
                flex: 1,
                padding: '0.6rem 0.9rem',
                border: '1px solid #d1d5db',
                borderRadius: 6,
                fontFamily: 'monospace',
                fontSize: '0.95rem',
                letterSpacing: '0.04em',
              }}
              autoFocus
            />
            <button type="submit" className="btn btn--primary" disabled={!input.trim()}>
              <L ar="تتبع" en="· Track" />
            </button>
          </form>
          <p style={{ fontSize: '0.8rem', color: '#6b7280', marginTop: '0.5rem' }}>
            <L ar="رقم التتبع يبدأ بـ DFL- ويظهر عند تقديم طلبك." en="The tracking ID starts with DFL- and is shown when you submit an application." />
          </p>
        </section>

        {loading && (
          <section className="detail-section">
            <div className="loading-spinner" />
          </section>
        )}

        {error && (
          <div className="alert alert--error">{error}</div>
        )}

        {tracking && st && (
          <>
            <section className="detail-section">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
                <div>
                  <p style={{ fontSize: '0.8rem', color: '#6b7280', margin: 0 }}>
                    <L ar="رقم التتبع" en="· Tracking ID" />
                  </p>
                  <p style={{ fontFamily: 'monospace', fontSize: '1.1rem', margin: '0.25rem 0 0', letterSpacing: '0.04em' }}>
                    {tracking.tracking_id}
                  </p>
                  <p style={{ fontSize: '0.85rem', color: '#6b7280', margin: '0.5rem 0 0' }}>
                    <L ar="نوع الخدمة:" en="· Service:" />
                    <strong>{tracking.service_type.replace('_', ' ')}</strong>
                  </p>
                </div>
                <span className={`status-badge status-badge--${st.color} status-badge--lg`}>
                  <L>{{ ar: <>{st.ar}</>, en: <>{st.en}</> }}</L>
                </span>
              </div>
              {tracking.next_action && (
                <div className="alert alert--info" style={{ marginTop: '1rem' }}>
                  <L ar="الخطوة التالية:" en="· Next action:" />
                  {tracking.next_action}
                </div>
              )}
            </section>

            <section className="detail-section">
              <h2>
                <L ar="مسار الطلب" en="Application Timeline" />
              </h2>
              <div className="timeline">
                {tracking.events.map((ev, i) => {
                  const evSt = STATUS_MAP[ev.status] || { ar: ev.status, en: ev.status, color: 'gray' };
                  return (
                    <div key={i} className="timeline__item">
                      <div className={`timeline__dot timeline__dot--${evSt.color}`} />
                      <div className="timeline__content">
                        <div className="timeline__header">
                          <strong>
                            <L>{{ ar: <>{evSt.ar}</>, en: <>· {evSt.en}</> }}</L>
                          </strong>
                          <span className="timeline__time">
                            {new Date(ev.timestamp).toLocaleString('ar-LB')}
                          </span>
                        </div>
                        {ev.message && <p className="timeline__msg">{ev.message}</p>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
