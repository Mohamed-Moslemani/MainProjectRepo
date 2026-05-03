import { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '@shared/context/useAuth';
import flagImg from '@shared/assets/Figure_1.png';
import '@shared/styles/dashboard.css';
import '@shared/styles/landing.css';
import L from '@shared/components/L';
import { useL } from '@shared/hooks/useL';

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
  {
    icon: '📤', ar: 'ارفع المستندات', en: 'Upload documents',
    body_ar: 'الجواز القديم، إخراج القيد، صورة شخصية. التطبيق يخبرك فوراً إن كانت الصورة ضبابية بما يكفي لرفضها.',
    body_en: 'Old passport, civil registry extract, selfie. The app tells you on the spot if a photo is too blurry to use.',
  },
  {
    icon: '🤖', ar: 'تحقق آلي', en: 'Automated check',
    body_ar: 'يقرأ النظام مستنداتك، ويطابق صورتك الشخصية مع صورة الوثيقة، ويتحقق من السجل المدني.',
    body_en: 'OCR reads your documents, face match against your selfie, and we cross-check the civil registry.',
  },
  {
    icon: '🪪', ar: 'ادفع واستلم', en: 'Pay & pick up',
    body_ar: 'بعد الموافقة، ادفع عبر الإنترنت واستلم وثيقتك من مركز الإصدار — زيارة واحدة دون انتظار.',
    body_en: 'Once approved, pay online and collect from the issuing centre — one visit, no queue.',
  },
];

const FEATURES = [
  { ar: 'تتبع علني للطلب برقم التتبع', en: 'Public tracking by reference ID' },
  { ar: 'سجل تدقيق لكل قرار آلي', en: 'Audit log on every automated decision' },
  { ar: 'واجهة عربية كاملة', en: 'Fully Arabic interface' },
  { ar: 'موافقة المختار رقمياً للجوازات', en: 'Digital mukhtar attestation for passports' },
];

// Pipeline tour for examiners landing on "/". Each step explains
// what the platform actually *does* with a submission — the kind
// of thing the citizen-facing copy ("upload, check, pay, pick up")
// hides. Surfaces the AI providers, the cross-checks, and where
// the human-in-the-loop sits.
const PIPELINE = [
  {
    n: '1',
    icon: '🔍',
    ar: 'استخراج النصوص (OCR)',
    en: 'OCR extraction',
    body_ar: 'Google Cloud Vision يقرأ بطاقة الهوية أو جواز السفر، ويستخرج الاسم وتاريخ الولادة ورقم السجل و MRZ للجوازات.',
    body_en: 'Google Cloud Vision reads the ID or passport, extracts name / DOB / registry number / MRZ for passports, scores image quality on the spot.',
  },
  {
    n: '2',
    icon: '🪪',
    ar: 'مطابقة الوجه + إثبات الحياة',
    en: 'Face match + liveness',
    body_ar: 'AWS Rekognition يقارن السيلفي بصورة المستند، ويتحقق من أن الشخص حي أمام الكاميرا (ليس صورة).',
    body_en: 'AWS Rekognition compares the selfie with the photo on the document and runs Face Liveness — proves the person is actually present, not a printed photo.',
  },
  {
    n: '3',
    icon: '📚',
    ar: 'مطابقة السجل المدني',
    en: 'Civil registry check',
    body_ar: 'النظام يطابق البيانات المدخلة مع السجل العائلي ويرفع علامة التناقضات قبل أي قرار آلي.',
    body_en: 'Declared fields are reconciled with the civil registry. Mismatches are surfaced before any automated decision is allowed.',
  },
  {
    n: '4',
    icon: '⚖️',
    ar: 'تقييم المخاطر',
    en: 'Risk scoring',
    body_ar: 'يتم احتساب نتيجة موزونة (جودة OCR، تطابق الوجه، إثبات الحياة، تناقضات السجل، حدّة الإشارات) لتحديد المسار.',
    body_en: 'Weighted score across OCR confidence, face similarity, liveness, registry reconciliation, image quality, severity. Threshold determines the routing.',
  },
  {
    n: '5',
    icon: '🧑‍⚖️',
    ar: 'القرار + المختار',
    en: 'Decision + mukhtar',
    body_ar: 'موافقة آلية للمنخفض الخطر، مراجعة موظف للحالات الحدية، رفض للمرتفع. الجوازات تمر بختم المختار رقمياً.',
    body_en: 'Auto-approved when risk is low, sent to a clerk when borderline, rejected when high. Passport applications additionally require a digital mukhtar attestation.',
  },
  {
    n: '6',
    icon: '💳',
    ar: 'دفع + استلام',
    en: 'Payment + pickup',
    body_ar: 'الدفع عبر Stripe برسوم محسوبة حسب الخدمة ومدة صلاحية الجواز، ثم زيارة واحدة لمركز GDGS لاستلام الوثيقة.',
    body_en: 'Stripe checkout with fees scaled by service type and passport validity tier, then a single visit to a GDGS centre for biometric capture and pickup.',
  },
];

export default function Landing() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { pick } = useL();
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
    <div className="landing">
      <a className="skip-link" href="#main">{pick({ ar: 'تخطي إلى المحتوى الرئيسي', en: 'Skip to main content' })}</a>

      <header className="landing__nav">
        <div className="landing__brand">
          <img src={flagImg} alt="" className="dashboard-header__flag" />
          <div>
            <strong>DocFlow Lebanon</strong>
            <span className="landing__tagline">
              <L ar="طلبات الهوية وجواز السفر عبر الإنترنت" en="Online ID & passport applications" />
            </span>
          </div>
        </div>
        <nav className="landing__nav-actions">
          <Link to="/track" className="btn btn--ghost btn--sm">
            <L ar="تتبع" en="· Track" />
          </Link>
          <Link to="/help" className="btn btn--ghost btn--sm">
            <L ar="مساعدة" en="· Help" />
          </Link>
          <Link to="/login" className="btn btn--outline btn--sm">
            <L ar="تسجيل الدخول" en="· Login" />
          </Link>
          <Link to="/register" className="btn btn--primary btn--sm">
            <L ar="حساب جديد" en="· Sign up" />
          </Link>
        </nav>
      </header>

      <main id="main" className="landing__main">
        <section className="landing__hero">
          <div className="landing__hero-text">
            <h1>
              <L ar="جدّد جواز السفر أو الهوية اللبنانية أونلاين" en="Renew your Lebanese ID or passport online — one visit, no queue." />
            </h1>
            <p className="landing__hero-sub">
              <L ar="ارفع مستنداتك، يتحقق منها النظام، ادفع الرسوم، ثم استلم وثيقتك. زيارة واحدة فقط للمركز." en="Upload your documents, the platform validates them automatically, you pay online, then collect from the issuing centre. One visit instead of standing in line." />
            </p>
            <div className="landing__cta">
              <Link to="/register" className="btn btn--primary btn--lg">
                <L ar="ابدأ طلباً جديداً" en="· Start a new application" />
              </Link>
              <Link to="/login" className="btn btn--outline btn--lg">
                <L ar="عندي حساب" en="· I have an account" />
              </Link>
            </div>
          </div>

          <aside className="landing__track-card">
            <h2>
              <L ar="تتبع طلباً موجوداً" en="Track an existing application" />
            </h2>
            <form onSubmit={goTrack} className="landing__track-form">
              <input
                type="text"
                value={trackId}
                onChange={(e) => setTrackId(e.target.value)}
                placeholder="DFL-XXXXXXXX"
                dir="ltr"
                aria-label={pick({ ar: 'رقم التتبع', en: 'Tracking ID' })}
              />
              <button type="submit" className="btn btn--primary" disabled={!trackId.trim()}>
                <L ar="تتبع" en="· Track" />
              </button>
            </form>
            <p className="landing__track-hint">
              <L ar="رقم التتبع يظهر بعد تقديم الطلب ويبدأ بـ DFL-." en="The reference ID is shown after you submit and starts with DFL-." />
            </p>
          </aside>
        </section>

        <section className="landing__how" aria-labelledby="how-h">
          <h2 id="how-h">
            <L ar="كيف يعمل النظام" en="How it works" />
          </h2>
          <div className="landing__how-grid">
            {HOW.map((h, i) => (
              <div key={i} className="landing__how-card">
                <span className="landing__how-icon" aria-hidden="true">{h.icon}</span>
                <h3>
                  <L>{{ ar: <>{h.ar}</>, en: <>{h.en}</> }}</L>
                </h3>
                <p>{pick({ ar: h.body_ar, en: h.body_en })}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="landing__pipeline" aria-labelledby="pipeline-h">
          <header className="landing__pipeline-header">
            <h2 id="pipeline-h">
              <L
                ar="ما يحدث لطلبك خلف الكواليس"
                en="What happens to your application, end-to-end"
              />
            </h2>
            <p className="landing__pipeline-sub">
              <L
                ar="ست مراحل آلية — استخراج، مطابقة، تحقق، تقييم، قرار، دفع — موثّقة في سجل تدقيق لكل قرار."
                en="Six automated stages — extract, match, verify, score, decide, pay — every decision logged to an audit trail."
              />
            </p>
          </header>

          <ol className="landing__pipeline-list">
            {PIPELINE.map((p) => (
              <li key={p.n} className="landing__pipeline-step">
                <span className="landing__pipeline-num" aria-hidden="true">{p.n}</span>
                <span className="landing__pipeline-icon" aria-hidden="true">{p.icon}</span>
                <div className="landing__pipeline-text">
                  <h3>
                    <L ar={p.ar} en={p.en} />
                  </h3>
                  <p>
                    <L ar={p.body_ar} en={p.body_en} />
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="landing__features">
          <h2>
            <L ar="مميزات" en="What's included" />
          </h2>
          <ul>
            {FEATURES.map((f, i) => (
              <li key={i}>
                <L>{{ ar: <>✓ {f.ar}</>, en: <>{f.en}</> }}</L>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="landing__footer">
        <span>
          © {new Date().getFullYear()} DocFlow Lebanon — <L ar="منصة تجريبية" en="demo platform" />
        </span>
        <nav>
          <Link to="/help"><L ar="مساعدة" en="Help" /></Link>
          <Link to="/terms"><L ar="الشروط" en="Terms" /></Link>
          <Link to="/privacy"><L ar="الخصوصية" en="Privacy" /></Link>
        </nav>
      </footer>
    </div>
  );
}
