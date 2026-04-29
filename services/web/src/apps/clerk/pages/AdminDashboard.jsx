import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { adminApi } from '@shared/api/admin';

const STATUS_LABELS = {
  draft: { ar: 'مسودة', en: 'Draft', color: '#9ca3af' },
  submitted: { ar: 'قيد المراجعة', en: 'Submitted', color: '#3b82f6' },
  validated: { ar: 'تم التحقق', en: 'Validated', color: '#06b6d4' },
  risk_evaluated: { ar: 'مراجعة يدوية', en: 'Manual Review', color: '#f59e0b' },
  approved: { ar: 'موافق عليه', en: 'Approved', color: '#22c55e' },
  payment_pending: { ar: 'بانتظار الدفع', en: 'Payment Pending', color: '#a855f7' },
  rejected: { ar: 'مرفوض', en: 'Rejected', color: '#ef4444' },
  need_info: { ar: 'بحاجة لمعلومات', en: 'Needs Info', color: '#f97316' },
  in_production: { ar: 'قيد الإنتاج', en: 'In Production', color: '#2563eb' },
  ready_for_pickup: { ar: 'جاهز للاستلام', en: 'Ready for Pickup', color: '#16a34a' },
  closed: { ar: 'مغلق', en: 'Closed', color: '#6b7280' },
};

const SERVICE_LABELS = {
  id_new: { ar: 'هوية جديدة', en: 'New ID', icon: '🪪' },
  id_renewal: { ar: 'تجديد هوية', en: 'ID Renewal', icon: '🔄' },
  passport_new: { ar: 'جواز سفر جديد', en: 'New Passport', icon: '🛂' },
  passport_renewal: { ar: 'تجديد جواز سفر', en: 'Passport Renewal', icon: '✈️' },
};

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    adminApi.getStats().then(({ data }) => setStats(data)).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="admin-page"><div className="admin-loading"><div className="spinner spinner--dark" /></div></div>;
  }

  if (!stats) {
    return <div className="admin-page"><div className="alert alert--error">Failed to load stats</div></div>;
  }

  const byStatus = stats.by_status || {};
  const byService = stats.by_service || {};
  const totalActive = Object.entries(byStatus)
    .filter(([s]) => !['closed', 'rejected', 'draft'].includes(s))
    .reduce((sum, [, c]) => sum + c, 0);

  return (
    <div className="admin-page">
      <div className="admin-page__header">
        <h1 className="admin-page__title">
          <span className="ar">لوحة التحكم</span>
          <span className="en">Dashboard</span>
        </h1>
        <p className="admin-page__subtitle">
          <span className="ar">مركز إدارة الطلبات — نظرة عامة</span>
          <span className="en">Case management center — overview</span>
        </p>
      </div>

      {/* Top KPIs */}
      <div className="kpi-row">
        <div className="kpi-card kpi-card--primary" onClick={() => navigate('/admin/cases')}>
          <span className="kpi-card__value">{stats.total_cases}</span>
          <span className="kpi-card__label"><span className="ar">إجمالي الطلبات</span><span className="en">Total Cases</span></span>
        </div>
        <div className="kpi-card kpi-card--warning" onClick={() => navigate('/admin/review')}>
          <span className="kpi-card__value">{stats.review_queue}</span>
          <span className="kpi-card__label"><span className="ar">بانتظار المراجعة</span><span className="en">Review Queue</span></span>
        </div>
        <div className="kpi-card kpi-card--info">
          <span className="kpi-card__value">{stats.cases_today}</span>
          <span className="kpi-card__label"><span className="ar">طلبات اليوم</span><span className="en">Today's Cases</span></span>
        </div>
        <div className="kpi-card kpi-card--success">
          <span className="kpi-card__value">${((stats.total_revenue_cents || 0) / 100).toLocaleString()}</span>
          <span className="kpi-card__label"><span className="ar">إجمالي الإيرادات</span><span className="en">Total Revenue</span></span>
        </div>
        <div className="kpi-card">
          <span className="kpi-card__value">{stats.total_users}</span>
          <span className="kpi-card__label"><span className="ar">المستخدمين</span><span className="en">Users</span></span>
        </div>
        <div className="kpi-card kpi-card--info">
          <span className="kpi-card__value">{totalActive}</span>
          <span className="kpi-card__label"><span className="ar">طلبات نشطة</span><span className="en">Active Cases</span></span>
        </div>
      </div>

      {/* Review Queue Alert */}
      {stats.review_queue > 0 && (
        <div className="review-alert" onClick={() => navigate('/admin/review')}>
          <div className="review-alert__icon">⚠️</div>
          <div className="review-alert__content">
            <strong>
              <span className="ar">{stats.review_queue} طلبات تحتاج مراجعة يدوية</span>
              <span className="en">{stats.review_queue} cases need manual review</span>
            </strong>
            <p>
              <span className="ar">هذه الطلبات لم تحصل على ثقة كافية من الذكاء الاصطناعي وتحتاج قرار الموظف.</span>
              <span className="en">These cases had low AI confidence and need a clerk decision.</span>
            </p>
          </div>
          <span className="review-alert__action">
            <span className="ar">مراجعة الآن ←</span>
            <span className="en">Review Now →</span>
          </span>
        </div>
      )}

      {/* Status Breakdown */}
      <div className="admin-section">
        <h2 className="admin-section__title">
          <span className="ar">توزيع الحالات</span>
          <span className="en">Status Distribution</span>
        </h2>
        <div className="status-grid">
          {Object.entries(STATUS_LABELS).map(([status, label]) => {
            const count = byStatus[status] || 0;
            if (count === 0 && ['draft', 'validated'].includes(status)) return null;
            return (
              <div
                key={status}
                className="status-card"
                style={{ borderLeftColor: label.color }}
                onClick={() => navigate(`/admin/cases?status=${status}`)}
              >
                <span className="status-card__count" style={{ color: label.color }}>{count}</span>
                <span className="status-card__label">
                  <span className="ar">{label.ar}</span>
                  <span className="en">{label.en}</span>
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Service Type Breakdown */}
      <div className="admin-section">
        <h2 className="admin-section__title">
          <span className="ar">حسب نوع الخدمة</span>
          <span className="en">By Service Type</span>
        </h2>
        <div className="service-grid">
          {Object.entries(SERVICE_LABELS).map(([svc, label]) => {
            const count = byService[svc] || 0;
            return (
              <div
                key={svc}
                className="service-card"
                onClick={() => navigate(`/admin/cases?service_type=${svc}`)}
              >
                <span className="service-card__icon">{label.icon}</span>
                <span className="service-card__count">{count}</span>
                <span className="service-card__label">
                  <span className="ar">{label.ar}</span>
                  <span className="en">{label.en}</span>
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Pipeline Status Bar */}
      {stats.total_cases > 0 && (
        <div className="admin-section">
          <h2 className="admin-section__title">
            <span className="ar">حالة خط الأنابيب</span>
            <span className="en">Pipeline Status</span>
          </h2>
          <div className="pipeline-bar">
            {Object.entries(byStatus).map(([status, count]) => {
              const pct = (count / stats.total_cases) * 100;
              if (pct < 1) return null;
              const label = STATUS_LABELS[status] || { color: '#ccc' };
              return (
                <div
                  key={status}
                  className="pipeline-bar__segment"
                  style={{ width: `${pct}%`, backgroundColor: label.color }}
                  title={`${STATUS_LABELS[status]?.en || status}: ${count} (${pct.toFixed(1)}%)`}
                />
              );
            })}
          </div>
          <div className="pipeline-legend">
            {Object.entries(byStatus).filter(([, c]) => c > 0).map(([status, count]) => {
              const label = STATUS_LABELS[status] || { ar: status, en: status, color: '#ccc' };
              return (
                <span key={status} className="pipeline-legend__item">
                  <span className="pipeline-legend__dot" style={{ backgroundColor: label.color }} />
                  <span className="en">{label.en}</span> ({count})
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Quick Actions */}
      <div className="admin-section">
        <h2 className="admin-section__title">
          <span className="ar">إجراءات سريعة</span>
          <span className="en">Quick Actions</span>
        </h2>
        <div className="quick-actions">
          <button className="quick-action" onClick={() => navigate('/admin/review')}>
            <span className="quick-action__icon quick-action__icon--yellow">⚖</span>
            <div>
              <strong><span className="ar">مراجعة الطلبات</span><span className="en">Review Cases</span></strong>
              <p><span className="ar">{stats.review_queue} طلبات بانتظار قرارك</span><span className="en">{stats.review_queue} cases awaiting your decision</span></p>
            </div>
          </button>
          <button className="quick-action" onClick={() => navigate('/admin/cases?status=need_info')}>
            <span className="quick-action__icon quick-action__icon--orange">?</span>
            <div>
              <strong><span className="ar">بحاجة لمعلومات</span><span className="en">Needs Information</span></strong>
              <p><span className="ar">{byStatus.need_info || 0} طلبات تنتظر رد المواطن</span><span className="en">{byStatus.need_info || 0} awaiting citizen response</span></p>
            </div>
          </button>
          <button className="quick-action" onClick={() => navigate('/admin/cases?status=ready_for_pickup')}>
            <span className="quick-action__icon quick-action__icon--green">📦</span>
            <div>
              <strong><span className="ar">جاهز للاستلام</span><span className="en">Ready for Pickup</span></strong>
              <p><span className="ar">{byStatus.ready_for_pickup || 0} مستندات جاهزة</span><span className="en">{byStatus.ready_for_pickup || 0} documents ready</span></p>
            </div>
          </button>
        </div>
      </div>
    </div>
  );
}