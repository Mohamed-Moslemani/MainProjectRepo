import { useState, useEffect, useCallback } from 'react';
import { adminApi } from '@shared/api/admin';

const PAGE_SIZE = 30;

const ACTION_LABELS = {
  case_created: { ar: 'إنشاء طلب', en: 'Case Created' },
  case_submitted: { ar: 'تقديم طلب', en: 'Case Submitted' },
  case_status_updated: { ar: 'تحديث الحالة', en: 'Status Updated' },
  document_uploaded: { ar: 'رفع مستند', en: 'Document Uploaded' },
  user_registered: { ar: 'تسجيل مستخدم', en: 'User Registered' },
  user_login: { ar: 'تسجيل دخول', en: 'User Login' },
  email_verified: { ar: 'تحقق من البريد', en: 'Email Verified' },
  verification_resent: { ar: 'إعادة إرسال التحقق', en: 'Verification Resent' },
  password_reset_requested: { ar: 'طلب إعادة تعيين كلمة المرور', en: 'Password Reset Requested' },
  password_reset_completed: { ar: 'إعادة تعيين كلمة المرور', en: 'Password Reset Completed' },
  payment_created: { ar: 'إنشاء دفعة', en: 'Payment Created' },
  payment_completed: { ar: 'اكتمال الدفعة', en: 'Payment Completed' },
  payment_failed: { ar: 'فشل الدفعة', en: 'Payment Failed' },
};

export default function AdminAuditLogs() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);

  const [filters, setFilters] = useState({
    case_id: '', action: '', user_id: '', request_id: '', since: '', until: '',
  });
  const [applied, setApplied] = useState(filters);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      // Convert local <input type="datetime-local"> values (no tz) to
      // ISO-8601 with explicit UTC suffix so the backend interprets
      // them consistently across DST changes.
      const toIso = (v) => (v ? new Date(v).toISOString() : undefined);
      const { data } = await adminApi.getAuditLogs({
        case_id: applied.case_id || undefined,
        action: applied.action || undefined,
        user_id: applied.user_id || undefined,
        request_id: applied.request_id || undefined,
        since: toIso(applied.since),
        until: toIso(applied.until),
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setLogs(data.logs);
      setHasMore(data.logs.length === PAGE_SIZE);
    } catch (err) {
      setError(err.response?.data?.detail || 'فشل في تحميل سجل التدقيق');
    } finally {
      setLoading(false);
    }
  }, [applied, page]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  const applyFilters = (e) => {
    e.preventDefault();
    setPage(0);
    setApplied({
      case_id: filters.case_id.trim(),
      action: filters.action,
      user_id: filters.user_id.trim(),
      request_id: filters.request_id.trim(),
      since: filters.since,
      until: filters.until,
    });
  };

  const clearFilters = () => {
    const empty = { case_id: '', action: '', user_id: '', request_id: '', since: '', until: '' };
    setFilters(empty);
    setApplied(empty);
    setPage(0);
  };

  const hasActiveFilters = Object.values(applied).some(Boolean);
  const setF = (k, v) => setFilters({ ...filters, [k]: v });

  const getActionLabel = (action) => ACTION_LABELS[action] || { ar: action, en: action };

  return (
    <div className="admin-page">
      <div className="admin-page__header">
        <h1 className="admin-page__title">
          <span className="ar">سجل التدقيق</span>
          <span className="en">Audit Logs</span>
        </h1>
        <p className="admin-page__subtitle">
          <span className="ar">سجل غير قابل للتعديل لجميع إجراءات النظام</span>
          <span className="en">Immutable record of all system actions</span>
        </p>
      </div>

      {/* Filters */}
      <form className="audit-filters" onSubmit={applyFilters} style={{ flexWrap: 'wrap', gap: '0.5rem' }}>
        <input
          type="text"
          className="form-input"
          placeholder="Case ID"
          value={filters.case_id}
          onChange={(e) => setF('case_id', e.target.value)}
          style={{ maxWidth: 200 }}
          dir="ltr"
        />
        <input
          type="text"
          className="form-input"
          placeholder="User ID"
          value={filters.user_id}
          onChange={(e) => setF('user_id', e.target.value)}
          style={{ maxWidth: 200 }}
          dir="ltr"
        />
        <input
          type="text"
          className="form-input"
          placeholder="Request ID"
          value={filters.request_id}
          onChange={(e) => setF('request_id', e.target.value)}
          style={{ maxWidth: 200 }}
          dir="ltr"
        />
        <select
          className="form-input"
          value={filters.action}
          onChange={(e) => setF('action', e.target.value)}
          style={{ maxWidth: 220 }}
        >
          <option value="">All actions</option>
          {Object.entries(ACTION_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label.en}</option>
          ))}
        </select>
        <input
          type="datetime-local"
          className="form-input"
          value={filters.since}
          onChange={(e) => setF('since', e.target.value)}
          title="Since (inclusive)"
        />
        <input
          type="datetime-local"
          className="form-input"
          value={filters.until}
          onChange={(e) => setF('until', e.target.value)}
          title="Until (inclusive)"
        />
        <button type="submit" className="btn-small btn-small--primary">
          <span className="ar">تطبيق</span>
          <span className="en"> · Apply</span>
        </button>
        {hasActiveFilters && (
          <button type="button" className="btn-small btn-small--ghost" onClick={clearFilters}>
            <span className="ar">مسح</span>
            <span className="en"> · Clear</span>
          </button>
        )}
      </form>

      {error && <div className="alert alert--error">{error}</div>}

      {loading ? (
        <div className="admin-loading">
          <div className="spinner spinner--dark" />
          <span className="ar">جارٍ التحميل...</span>
        </div>
      ) : logs.length === 0 ? (
        <div className="admin-empty">
          <span className="ar">لا توجد سجلات</span>
          <span className="en">No audit logs found</span>
        </div>
      ) : (
        <>
          <div className="cases-table-wrap">
            <table className="cases-table">
              <thead>
                <tr>
                  <th><span className="ar">الوقت</span><span className="en">Timestamp</span></th>
                  <th><span className="ar">الإجراء</span><span className="en">Action</span></th>
                  <th><span className="ar">المستخدم</span><span className="en">User ID</span></th>
                  <th><span className="ar">الطلب</span><span className="en">Case ID</span></th>
                  <th><span className="ar">طلب HTTP</span><span className="en">Request ID</span></th>
                  <th><span className="ar">التفاصيل</span><span className="en">Details</span></th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => {
                  const actionLabel = getActionLabel(log.action);
                  return (
                    <tr key={log.id}>
                      <td className="cases-table__date">
                        {new Date(log.created_at).toLocaleString('ar-LB')}
                      </td>
                      <td>
                        <span className="action-badge">
                          <span className="ar">{actionLabel.ar}</span>
                          <span className="en">{actionLabel.en}</span>
                        </span>
                      </td>
                      <td className="audit-id">
                        {log.user_id ? (
                          <button
                            type="button"
                            className="btn-link"
                            title="Filter by this user"
                            onClick={() => { setF('user_id', log.user_id); setApplied({ ...applied, user_id: log.user_id }); setPage(0); }}
                          >
                            {log.user_id.slice(0, 8)}…
                          </button>
                        ) : '—'}
                      </td>
                      <td className="audit-id">
                        {log.case_id ? (
                          <button
                            type="button"
                            className="btn-link"
                            title="Filter by this case"
                            onClick={() => { setF('case_id', log.case_id); setApplied({ ...applied, case_id: log.case_id }); setPage(0); }}
                          >
                            {log.case_id.slice(0, 8)}…
                          </button>
                        ) : '—'}
                      </td>
                      <td className="audit-id">
                        {log.request_id ? (
                          <button
                            type="button"
                            className="btn-link"
                            title="Filter by this request"
                            onClick={() => { setF('request_id', log.request_id); setApplied({ ...applied, request_id: log.request_id }); setPage(0); }}
                          >
                            {log.request_id.slice(0, 8)}…
                          </button>
                        ) : '—'}
                      </td>
                      <td>
                        {log.details && Object.keys(log.details).length > 0 ? (
                          <code className="audit-details">
                            {JSON.stringify(log.details)}
                          </code>
                        ) : (
                          <span style={{ color: 'var(--gray-400)' }}>—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="pagination">
            <button className="pagination__btn" disabled={page === 0} onClick={() => setPage(page - 1)}>
              <span className="ar">السابق</span>
              <span className="en">Previous</span>
            </button>
            <span className="pagination__info">
              <span className="ar">صفحة {page + 1}</span>
              <span className="en">Page {page + 1}</span>
            </span>
            <button className="pagination__btn" disabled={!hasMore} onClick={() => setPage(page + 1)}>
              <span className="ar">التالي</span>
              <span className="en">Next</span>
            </button>
          </div>
        </>
      )}
    </div>
  );
}
