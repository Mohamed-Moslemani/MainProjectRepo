import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { mukhtarApi } from '@shared/api/mukhtar';
import L from '@shared/components/L';

export default function MukhtarDashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    mukhtarApi.getStats()
      .then(({ data }) => setStats(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="admin-page"><div className="admin-loading"><div className="spinner spinner--dark" /></div></div>;
  }

  if (!stats) {
    return <div className="admin-page"><div className="alert alert--error"><L ar="فشل في تحميل الإحصائيات" en="Failed to load stats" /></div></div>;
  }

  return (
    <div className="admin-page">
      <div className="admin-page__header">
        <h1 className="admin-page__title">
          <L ar="لوحة تحكم المختار" en="Mukhtar Dashboard" />
        </h1>
        <p className="admin-page__subtitle">
          <L ar="مراجعة طلبات جوازات السفر والتصديق عليها رقميا" en="Review passport applications and digitally certify them" />
        </p>
      </div>

      {/* KPIs */}
      <div className="kpi-row">
        <div className="kpi-card kpi-card--warning" onClick={() => navigate('/mukhtar/cases')}>
          <span className="kpi-card__value">{stats.pending_review}</span>
          <span className="kpi-card__label">
            <L ar="بانتظار المصادقة" en="Pending Review" />
          </span>
        </div>
        <div className="kpi-card kpi-card--success">
          <span className="kpi-card__value">{stats.approved}</span>
          <span className="kpi-card__label">
            <L ar="تمت الموافقة" en="Approved" />
          </span>
        </div>
        <div className="kpi-card kpi-card--primary">
          <span className="kpi-card__value">{stats.total_cases}</span>
          <span className="kpi-card__label">
            <L ar="إجمالي الطلبات" en="Total Cases" />
          </span>
        </div>
        <div className="kpi-card kpi-card--info">
          <span className="kpi-card__value">{stats.today_activity}</span>
          <span className="kpi-card__label">
            <L ar="نشاط اليوم" en="Today's Activity" />
          </span>
        </div>
      </div>

      {/* Pending alert */}
      {stats.pending_review > 0 && (
        <div className="review-alert" onClick={() => navigate('/mukhtar/cases')}>
          <div className="review-alert__icon">&#9998;</div>
          <div className="review-alert__content">
            <strong>
              <L>{{ ar: <>{stats.pending_review} طلبات تحتاج مصادقتك</>, en: <>{stats.pending_review} applications need your certification</> }}</L>
            </strong>
            <p>
              <L ar="هذه الطلبات تم التحقق منها آليا وتنتظر توقيعك الرقمي." en="These applications have been auto-verified and await your digital stamp." />
            </p>
          </div>
          <span className="review-alert__action">
            <L ar="مراجعة الآن &#8592;" en="Review Now &#8594;" />
          </span>
        </div>
      )}

      {/* How it works */}
      <div className="admin-section">
        <h2 className="admin-section__title">
          <L ar="كيف يعمل النظام" en="How It Works" />
        </h2>
        <div className="quick-actions">
          <div className="quick-action" style={{ cursor: 'default' }}>
            <span className="quick-action__icon quick-action__icon--blue">1</span>
            <div>
              <strong><L ar="المواطن يقدم الطلب" en="Citizen Submits" /></strong>
              <p><L ar="يرفع المستندات ويقوم بالتحقق من الهوية" en="Uploads docs & completes identity verification" /></p>
            </div>
          </div>
          <div className="quick-action" style={{ cursor: 'default' }}>
            <span className="quick-action__icon quick-action__icon--yellow">2</span>
            <div>
              <strong><L ar="النظام يتحقق تلقائيا" en="System Auto-Verifies" /></strong>
              <p><L ar="OCR + مطابقة الوجه + تقييم المخاطر" en="OCR + face match + risk scoring" /></p>
            </div>
          </div>
          <div className="quick-action" style={{ cursor: 'default' }}>
            <span className="quick-action__icon quick-action__icon--green">3</span>
            <div>
              <strong><L ar="أنت تصادق رقميا" en="You Certify Digitally" /></strong>
              <p><L ar="راجع البيانات ووافق أو ارفض" en="Review the data and approve or reject" /></p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}