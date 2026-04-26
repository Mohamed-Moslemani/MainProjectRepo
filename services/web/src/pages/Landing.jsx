import { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/useAuth';
import flagImg from '../assets/Figure_1.png';
import '../styles/dashboard.css';
import '../styles/landing.css';

/**
 * Public landing page at "/".
 *
 * Logged-in users get bounced straight to the right home for their
 * role — citizen → /dashboard, admin/clerk → /admin, mukhtar →
 * /mukhtar. Anonymous visitors see a marketing-style hero with the
 * three primary actions: track an existing application by ID, log
 * in, or register.
 *
 * The page also doubles as the public face of the platform — a
 * three-up "how it works" panel + a feature list to set citizen
 * expectations before they sign up.
 */

const HOW = [
  { icon: '📤', ar: 'ارفع المستندات', en: 'Upload documents', body_en: 'Old passport, civil registry extract, selfie. The app tells you on the spot if a photo is too blurry to use.' },
  { icon: '🤖', ar: 'تحقق آلي', en: 'Automated check', body_en: 'OCR reads your documents, face match against your selfie, and we cross-check the civil registry.' },
  { icon: '🪪', ar: 'استلم وثيقتك', en: 'Pay & pick up', body_en: 'Once approved, pay online and collect from the issuing centre — one visit, no queue.' },
];

const FEATURES = [
  { ar: 'تتبع علني للطلب برقم التتبع', en: 'Public tracking by reference ID' },
  { ar: 'سجل تدقيق لكل قرار آلي', en: 'Audit log on every automated decision' },
  { ar: 'دعم العربية والإنجليزية', en: 'Arabic + English throughout' },
  { ar: 'موافقة المختار رقمياً للجوازات', en: 'Digital mukhtar attestation for passports' },
];

export default function Landing() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [trackId, setTrackId] = useState('');

  // Bounce signed-in users to their role home so they never see the
  // marketing page after login.
  if (user) {
    if (user.role === 'admin' || user.role === 'clerk') return <Navigate to="/admin" replace />;
    if (user.role === 'mukhtar') return <Navigate to="/mukhtar" replace />;
    return <Navigate to="/dashboard" replace />;
  }

  const goTrack = (e) => {
    e.preventDefault();
    const id = trackId.trim().toUpperCase();
    if (id) navigate(`/track/${encodeURIComponent(id)}`);
  };

  return (
    <div className="landing" dir="rtl">
      <a className="skip-link" href="#main">Skip to main content</a>

      <header className="landing__nav">
        <div className="landing__brand">
          <img src={flagImg} alt="" className="dashboard-header__flag" />
          <div>
            <strong>DocFlow Lebanon</strong>
            <span className="landing__tagline en">Online ID &amp; passport applications</span>
          </div>
        </div>
        <nav className="landing__nav-actions">
          <Link to="/track" className="btn btn--ghost btn--sm">
            <span className="ar">تتبع</span>
            <span className="en"> · Track</span>
          </Link>
          <Link to="/help" className="btn btn--ghost btn--sm">
            <span className="ar">مساعدة</span>
            <span className="en"> · Help</span>
          </Link>
          <Link to="/login" className="btn btn--outline btn--sm">
            <span className="ar">تسجيل الدخول</span>
            <span className="en"> · Login</span>
          </Link>
          <Link to="/register" className="btn btn--primary btn--sm">
            <span className="ar">حساب جديد</span>
            <span className="en"> · Sign up</span>
          </Link>
        </nav>
      </header>

      <main id="main" className="landing__main">
        <section className="landing__hero">
          <div className="landing__hero-text">
            <h1>
              <span className="ar">جدّد جواز السفر أو الهوية اللبنانية أونلاين</span>
              <span className="en" style={{ display: 'block', fontSize: '1.05rem', color: '#6b7280', marginTop: '0.4rem' }}>
                Renew your Lebanese ID or passport online — one visit, no queue.
              </span>
            </h1>
            <p className="landing__hero-sub">
              <span className="ar">
                ارفع مستنداتك، يتحقق منها النظام، ادفع الرسوم، ثم استلم وثيقتك. زيارة واحدة فقط للمركز.
              </span>
              <span className="en" style={{ display: 'block', marginTop: '0.4rem' }}>
                Upload your documents, the platform validates them automatically, you pay online, then collect from the issuing centre. One visit instead of standing in line.
              </span>
            </p>
            <div className="landing__cta">
              <Link to="/register" className="btn btn--primary btn--lg">
                <span className="ar">ابدأ طلباً جديداً</span>
                <span className="en"> · Start a new application</span>
              </Link>
              <Link to="/login" className="btn btn--outline btn--lg">
                <span className="ar">عندي حساب</span>
                <span className="en"> · I have an account</span>
              </Link>
            </div>
          </div>

          <aside className="landing__track-card">
            <h2>
              <span className="ar">تتبع طلباً موجوداً</span>
              <span className="en" style={{ display: 'block', fontSize: '0.85rem', color: '#6b7280' }}>
                Track an existing application
              </span>
            </h2>
            <form onSubmit={goTrack} className="landing__track-form">
              <input
                type="text"
                value={trackId}
                onChange={(e) => setTrackId(e.target.value)}
                placeholder="DFL-XXXXXXXX"
                dir="ltr"
                aria-label="Tracking ID"
              />
              <button type="submit" className="btn btn--primary" disabled={!trackId.trim()}>
                <span className="ar">تتبع</span>
                <span className="en"> · Track</span>
              </button>
            </form>
            <p className="landing__track-hint">
              <span className="ar">رقم التتبع يظهر بعد تقديم الطلب ويبدأ بـ DFL-.</span>
              <span className="en" style={{ display: 'block' }}>
                The reference ID is shown after you submit and starts with DFL-.
              </span>
            </p>
          </aside>
        </section>

        <section className="landing__how" aria-labelledby="how-h">
          <h2 id="how-h">
            <span className="ar">كيف يعمل النظام</span>
            <span className="en" style={{ display: 'block', fontSize: '0.95rem', color: '#6b7280' }}>
              How it works
            </span>
          </h2>
          <div className="landing__how-grid">
            {HOW.map((h, i) => (
              <div key={i} className="landing__how-card">
                <span className="landing__how-icon" aria-hidden="true">{h.icon}</span>
                <h3>
                  <span className="ar">{h.ar}</span>
                  <span className="en" style={{ display: 'block', fontSize: '0.8rem', color: '#6b7280' }}>{h.en}</span>
                </h3>
                <p>{h.body_en}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="landing__features">
          <h2>
            <span className="ar">مميزات</span>
            <span className="en" style={{ display: 'block', fontSize: '0.95rem', color: '#6b7280' }}>
              What's included
            </span>
          </h2>
          <ul>
            {FEATURES.map((f, i) => (
              <li key={i}>
                <span className="ar">✓ {f.ar}</span>
                <span className="en" style={{ display: 'block', color: '#6b7280', fontSize: '0.85rem' }}>
                  {f.en}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="landing__footer">
        <span>© {new Date().getFullYear()} DocFlow Lebanon — demo platform</span>
        <nav>
          <Link to="/help">Help</Link>
          <Link to="/terms">Terms</Link>
          <Link to="/privacy">Privacy</Link>
        </nav>
      </footer>
    </div>
  );
}
