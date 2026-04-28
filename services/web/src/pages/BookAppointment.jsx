import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { appointmentsApi } from '../api/appointments';
import { casesApi } from '../api/cases';
import { useToast } from '../context/useToast';
import flagImg from '../assets/Figure_1.png';
import '../styles/dashboard.css';

// Biometric appointment booking. Lebanese passport flow gates on a
// physical visit to a GDGS centre for fingerprint + signature
// capture. Citizens land here once their case enters
// BIOMETRIC_APPOINTMENT_REQUIRED — they pick a centre and an open
// 30-min slot for the next ~14 days.
//
// Slots come back from the gateway in UTC ISO; we render in local
// Beirut time. The same-day moratorium (no slots within the next
// hour) is enforced server-side, but we still show local times so
// the choice is unambiguous.
export default function BookAppointment() {
  const { caseId } = useParams();
  const toast = useToast();
  const navigate = useNavigate();

  const [centres, setCentres] = useState([]);
  const [centreId, setCentreId] = useState('');
  const [slots, setSlots] = useState([]);
  const [loadingSlots, setLoadingSlots] = useState(false);
  const [existing, setExisting] = useState(null);
  const [booking, setBooking] = useState(false);
  const [caseStatus, setCaseStatus] = useState(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      appointmentsApi.centres(),
      appointmentsApi.forCase(caseId).catch(() => null),
      casesApi.get(caseId).catch(() => null),
    ]).then(([cs, ex, c]) => {
      if (cancelled) return;
      setCentres(cs.data.centres || []);
      if (ex?.data) {
        setExisting(ex.data);
        setCentreId(ex.data.centre_id || '');
      }
      if (c?.data) setCaseStatus(c.data.status);
    });
    return () => { cancelled = true; };
  }, [caseId]);

  useEffect(() => {
    if (!centreId) { setSlots([]); return; }
    let cancelled = false;
    setLoadingSlots(true);
    appointmentsApi.slots(centreId)
      .then(({ data }) => { if (!cancelled) setSlots(data.slots || []); })
      .catch(() => { if (!cancelled) toast.error('فشل في تحميل المواعيد'); })
      .finally(() => { if (!cancelled) setLoadingSlots(false); });
    return () => { cancelled = true; };
  // toast is stable from the provider
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centreId]);

  // Group slots by local day so the picker reads as a daily agenda
  // instead of a flat list of 80+ ISO strings.
  const slotsByDay = useMemo(() => {
    const map = new Map();
    for (const iso of slots) {
      const d = new Date(iso);
      const dayKey = d.toLocaleDateString('en-CA'); // YYYY-MM-DD
      if (!map.has(dayKey)) map.set(dayKey, []);
      map.get(dayKey).push(iso);
    }
    return [...map.entries()];
  }, [slots]);

  const handleBook = async (slotIso) => {
    if (!centreId) return;
    setBooking(true);
    try {
      const { data } = await appointmentsApi.book({
        caseId, centreId, slotStart: slotIso,
      });
      setExisting(data);
      toast.success('تم تأكيد الموعد');
      // Refresh slot list so the booked slot disappears.
      const { data: fresh } = await appointmentsApi.slots(centreId);
      setSlots(fresh.slots || []);
    } catch (err) {
      const msg = err.response?.data?.detail;
      if (err.response?.status === 409) {
        toast.error('هذا الموعد محجوز — اختر موعداً آخر');
      } else {
        toast.error(msg || 'فشل في حجز الموعد');
      }
    } finally {
      setBooking(false);
    }
  };

  const fmtLocal = (iso) => new Date(iso).toLocaleTimeString('en-GB', {
    hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Beirut',
  });
  const fmtDay = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', {
    weekday: 'short', day: '2-digit', month: 'short', timeZone: 'Asia/Beirut',
  });

  const wrongStatus = caseStatus && caseStatus !== 'biometric_appointment_required';

  return (
    <div className="dashboard" dir="rtl">
      <header className="dashboard-header">
        <div className="dashboard-header__inner">
          <div className="dashboard-header__brand">
            <img src={flagImg} alt="" className="dashboard-header__flag" />
            <div>
              <h1 className="dashboard-header__title">
                <span className="ar">حجز موعد البصمات</span>
              </h1>
              <p className="dashboard-header__subtitle">
                <span className="en">Book biometric appointment</span>
              </p>
            </div>
          </div>
          <div className="dashboard-header__actions">
            <Link to={`/case/${caseId}`} className="btn btn--outline btn--sm">
              <span className="ar">العودة للطلب</span>
              <span className="en"> · Back to case</span>
            </Link>
          </div>
        </div>
      </header>

      <main className="dashboard-main" style={{ maxWidth: 880 }}>
        {existing && (
          <section className="detail-section">
            <h2>
              <span className="ar">الموعد الحالي</span>
              <span className="en">Current appointment</span>
            </h2>
            <p>
              <strong>{existing.centre_name_ar} / {existing.centre_name_en}</strong>
              {' · '}
              {new Date(existing.slot_start).toLocaleString('en-GB', {
                timeZone: 'Asia/Beirut',
                weekday: 'short', day: '2-digit', month: 'short',
                hour: '2-digit', minute: '2-digit',
              })}
              {' · '}
              <span style={{ color: '#6b7280' }}>{existing.status}</span>
            </p>
            <p style={{ fontSize: '0.85rem', color: '#6b7280' }}>
              <span className="ar">يمكنك تعديل الموعد بحجز موعد جديد أدناه.</span>
              <span className="en" style={{ display: 'block' }}>
                You can reschedule by picking another slot below.
              </span>
            </p>
          </section>
        )}

        {wrongStatus && (
          <section className="detail-section" style={{ borderColor: '#fbbf24' }}>
            <p>
              <span className="ar">طلبك ليس بانتظار حجز موعد بصمات حالياً (الحالة: {caseStatus}).</span>
              <span className="en" style={{ display: 'block' }}>
                Your case is not currently awaiting a biometric appointment (status: {caseStatus}).
              </span>
            </p>
          </section>
        )}

        <section className="detail-section">
          <h2>
            <span className="ar">١. اختر مركز الأمن العام</span>
            <span className="en">1. Choose a GDGS centre</span>
          </h2>
          <select
            value={centreId}
            onChange={(e) => setCentreId(e.target.value)}
            style={{ width: '100%', padding: '0.6rem', fontSize: '1rem' }}
          >
            <option value="">-- اختر مركزاً / Select a centre --</option>
            {centres.map((c) => (
              <option key={c.id} value={c.id}>
                {c.ar} / {c.en} — {c.governorate}
              </option>
            ))}
          </select>
        </section>

        {centreId && (
          <section className="detail-section">
            <h2>
              <span className="ar">٢. اختر الموعد</span>
              <span className="en">2. Choose a time slot</span>
            </h2>
            {loadingSlots ? (
              <p>Loading slots…</p>
            ) : slots.length === 0 ? (
              <p>
                <span className="ar">لا توجد مواعيد متاحة في الأسبوعين القادمين.</span>
                <span className="en" style={{ display: 'block' }}>
                  No open slots in the next two weeks.
                </span>
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {slotsByDay.map(([day, daySlots]) => (
                  <div key={day}>
                    <h3 style={{ fontSize: '0.95rem', margin: '0 0 0.4rem' }}>{fmtDay(day)}</h3>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                      {daySlots.map((iso) => (
                        <button
                          key={iso}
                          className="btn btn--outline btn--sm"
                          disabled={booking || wrongStatus}
                          onClick={() => handleBook(iso)}
                        >
                          {fmtLocal(iso)}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        <p style={{ fontSize: '0.85rem', color: '#6b7280' }}>
          <span className="ar">
            ساعات العمل في مراكز الأمن العام: ٩:٠٠ – ١٥:٠٠ من الإثنين إلى الجمعة. لا يمكن الحجز قبل أقل من ساعة من الموعد.
          </span>
          <span className="en" style={{ display: 'block' }}>
            GDGS hours: 09:00–15:00, Mon–Fri. No same-hour bookings.
          </span>
        </p>
      </main>
    </div>
  );
}
