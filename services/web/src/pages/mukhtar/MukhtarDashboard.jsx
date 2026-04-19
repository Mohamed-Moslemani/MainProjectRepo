import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { mukhtarApi } from '../../api/mukhtar';

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
    return <div className="admin-page"><div className="alert alert--error">Failed to load stats</div></div>;
  }

  return (
    <div className="admin-page">
      <div className="admin-page__header">
        <h1 className="admin-page__title">
          <span className="ar">لوحة تحكم المختار</span>
          <span className="en">Mukhtar Dashboard</span>
        </h1>
        <p className="admin-page__subtitle">
          <span className="ar">مراجعة طلبات جوازات السفر والتصديق عليها رقميا</span>
          <span className="en">Review passport applications and digitally certify them</span>
        </p>
      </div>

      {/* KPIs */}
      <div className="kpi-row">
        <div className="kpi-card kpi-card--warning" onClick={() => navigate('/mukhtar/cases')}>
          <span className="kpi-card__value">{stats.pending_review}</span>
          <span className="kpi-card__label">
            <span className="ar">بانتظار المصادقة</span>
            <span className="en">Pending Review</span>
          </span>
        </div>
        <div className="kpi-card kpi-card--success">
          <span className="kpi-card__value">{stats.approved}</span>
          <span className="kpi-card__label">
            <span className="ar">تمت الموافقة</span>
            <span className="en">Approved</span>
          </span>
        </div>
        <div className="kpi-card kpi-card--primary">
          <span className="kpi-card__value">{stats.total_cases}</span>
          <span className="kpi-card__label">
            <span className="ar">إجمالي الطلبات</span>
            <span className="en">Total Cases</span>
          </span>
        </div>
        <div className="kpi-card kpi-card--info">
          <span className="kpi-card__value">{stats.today_activity}</span>
          <span className="kpi-card__label">
            <span className="ar">نشاط اليوم</span>
            <span className="en">Today's Activity</span>
          </span>
        </div>
      </div>

      {/* Pending alert */}
      {stats.pending_review > 0 && (
        <div className="review-alert" onClick={() => navigate('/mukhtar/cases')}>
          <div className="review-alert__icon">&#9998;</div>
          <div className="review-alert__content">
            <strong>
              <span className="ar">{stats.pending_review} طلبات تحتاج مصادقتك</span>
              <span className="en">{stats.pending_review} applications need your certification</span>
            </strong>
            <p>
              <span className="ar">هذه الطلبات تم التحقق منها آليا وتنتظر توقيعك الرقمي.</span>
              <span className="en">These applications have been auto-verified and await your digital stamp.</span>
            </p>
          </div>
          <span className="review-alert__action">
            <span className="ar">مراجعة الآن &#8592;</span>
            <span className="en">Review Now &#8594;</span>
          </span>
        </div>
      )}

      {/* How it works */}
      <div className="admin-section">
        <h2 className="admin-section__title">
          <span className="ar">كيف يعمل النظام</span>
          <span className="en">How It Works</span>
        </h2>
        <div className="quick-actions">
          <div className="quick-action" style={{ cursor: 'default' }}>
            <span className="quick-action__icon quick-action__icon--blue">1</span>
            <div>
              <strong><span className="ar">المواطن يقدم الطلب</span><span className="en">Citizen Submits</span></strong>
              <p><span className="ar">يرفع المستندات ويقوم بالتحقق من الهوية</span><span className="en">Uploads docs & completes identity verification</span></p>
            </div>
          </div>
          <div className="quick-action" style={{ cursor: 'default' }}>
            <span className="quick-action__icon quick-action__icon--yellow">2</span>
            <div>
              <strong><span className="ar">النظام يتحقق تلقائيا</span><span className="en">System Auto-Verifies</span></strong>
              <p><span className="ar">OCR + مطابقة الوجه + تقييم المخاطر</span><span className="en">OCR + face match + risk scoring</span></p>
            </div>
          </div>
          <div className="quick-action" style={{ cursor: 'default' }}>
            <span className="quick-action__icon quick-action__icon--green">3</span>
            <div>
              <strong><span className="ar">أنت تصادق رقميا</span><span className="en">You Certify Digitally</span></strong>
              <p><span className="ar">راجع البيانات ووافق أو ارفض</span><span className="en">Review the data and approve or reject</span></p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}