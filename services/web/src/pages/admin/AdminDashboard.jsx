import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { adminApi } from '../../api/admin';

const STATUS_LABELS = {
  draft: { ar: 'مسودة', en: 'Draft' },
  submitted: { ar: 'قيد المراجعة', en: 'Submitted' },
  validated: { ar: 'تم التحقق', en: 'Validated' },
  risk_evaluated: { ar: 'تم تقييم المخاطر', en: 'Risk Evaluated' },
  approved: { ar: 'موافق عليه', en: 'Approved' },
  rejected: { ar: 'مرفوض', en: 'Rejected' },
  need_info: { ar: 'بحاجة لمعلومات', en: 'Needs Info' },
  in_production: { ar: 'قيد الإنتاج', en: 'In Production' },
  ready_for_pickup: { ar: 'جاهز للاستلام', en: 'Ready for Pickup' },
  closed: { ar: 'مغلق', en: 'Closed' },
};

function statusClass(status) {
  if (['approved', 'closed'].includes(status)) return 'stat-card--green';
  if (['rejected'].includes(status)) return 'stat-card--red';
  if (['need_info'].includes(status)) return 'stat-card--yellow';
  if (['submitted', 'validated', 'risk_evaluated'].includes(status)) return 'stat-card--blue';
  return '';
}

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const load = async () => {
      try {
        const { data } = await adminApi.getStats();
        setStats(data);
      } catch (err) {
        setError(err.response?.data?.detail || 'فشل في تحميل الإحصائيات');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading) {
    return (
      <div className="admin-page">
        <div className="admin-loading">
          <div className="spinner spinner--dark" />
          <span className="ar">جارٍ التحميل...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="admin-page">
        <div className="alert alert--error">{error}</div>
      </div>
    );
  }

  const byStatus = stats?.by_status || {};

  return (
    <div className="admin-page">
      <div className="admin-page__header">
        <h1 className="admin-page__title">
          <span className="ar">لوحة التحكم</span>
          <span className="en">Dashboard</span>
        </h1>
        <p className="admin-page__subtitle">
          <span className="ar">نظرة عامة على جميع الطلبات</span>
          <span className="en">Overview of all case activity</span>
        </p>
      </div>

      <div className="stat-cards">
        <div className="stat-card stat-card--total" onClick={() => navigate('/admin/cases')}>
          <span className="stat-card__label">
            <span className="ar">إجمالي الطلبات</span>
            <span className="en">Total Cases</span>
          </span>
          <span className="stat-card__value">{stats?.total_cases || 0}</span>
        </div>

        {Object.entries(byStatus).map(([status, count]) => {
          const label = STATUS_LABELS[status] || { ar: status, en: status };
          return (
            <div
              key={status}
              className={`stat-card ${statusClass(status)}`}
              onClick={() => navigate(`/admin/cases?status=${status}`)}
            >
              <span className="stat-card__label">
                <span className="ar">{label.ar}</span>
                <span className="en">{label.en}</span>
              </span>
              <span className="stat-card__value">{count}</span>
              <span className="stat-card__status-dot" data-status={status} />
            </div>
          );
        })}
      </div>

      <div className="admin-section">
        <div className="admin-section__header">
          <h2 className="admin-section__title">
            <span className="ar">إجراءات سريعة</span>
            <span className="en">Quick Actions</span>
          </h2>
        </div>
        <div className="quick-actions">
          <button className="quick-action" onClick={() => navigate('/admin/cases?status=submitted')}>
            <span className="quick-action__icon quick-action__icon--blue">!</span>
            <div>
              <strong>
                <span className="ar">بانتظار المراجعة</span>
                <span className="en">Pending Review</span>
              </strong>
              <p>
                <span className="ar">{byStatus.submitted || 0} طلبات بانتظار المعالجة</span>
                <span className="en">{byStatus.submitted || 0} cases awaiting processing</span>
              </p>
            </div>
          </button>
          <button className="quick-action" onClick={() => navigate('/admin/cases?status=need_info')}>
            <span className="quick-action__icon quick-action__icon--yellow">?</span>
            <div>
              <strong>
                <span className="ar">بحاجة لمعلومات</span>
                <span className="en">Needs Information</span>
              </strong>
              <p>
                <span className="ar">{byStatus.need_info || 0} طلبات تنتظر رد المواطن</span>
                <span className="en">{byStatus.need_info || 0} cases need citizen response</span>
              </p>
            </div>
          </button>
          <button className="quick-action" onClick={() => navigate('/admin/cases?status=approved')}>
            <span className="quick-action__icon quick-action__icon--green">&#10003;</span>
            <div>
              <strong>
                <span className="ar">تمت الموافقة</span>
                <span className="en">Approved</span>
              </strong>
              <p>
                <span className="ar">{byStatus.approved || 0} طلبات جاهزة للإنتاج</span>
                <span className="en">{byStatus.approved || 0} cases ready for production</span>
              </p>
            </div>
          </button>
        </div>
      </div>
    </div>
  );
}
