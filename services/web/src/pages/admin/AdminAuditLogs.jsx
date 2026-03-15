import { useState, useEffect, useCallback } from 'react';
import { adminApi } from '../../api/admin';

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

  const [caseIdFilter, setCaseIdFilter] = useState('');
  const [actionFilter, setActionFilter] = useState('');
  const [appliedCaseId, setAppliedCaseId] = useState('');
  const [appliedAction, setAppliedAction] = useState('');

  const loadLogs = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { data } = await adminApi.getAuditLogs({
        case_id: appliedCaseId || undefined,
        action: appliedAction || undefined,
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
  }, [appliedCaseId, appliedAction, page]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  const applyFilters = (e) => {
    e.preventDefault();
    setPage(0);
    setAppliedCaseId(caseIdFilter.trim());
    setAppliedAction(actionFilter);
  };

  const clearFilters = () => {
    setCaseIdFilter('');
    setActionFilter('');
    setAppliedCaseId('');
    setAppliedAction('');
    setPage(0);
  };

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
      <form className="audit-filters" onSubmit={applyFilters}>
        <input
          type="text"
          className="form-input"
          placeholder="فلترة حسب رقم الطلب..."
          value={caseIdFilter}
          onChange={(e) => setCaseIdFilter(e.target.value)}
          style={{ maxWidth: 280 }}
          dir="ltr"
        />
        <select
          className="form-input"
          value={actionFilter}
          onChange={(e) => setActionFilter(e.target.value)}
          style={{ maxWidth: 220 }}
        >
          <option value="">كل الإجراءات / All Actions</option>
          {Object.entries(ACTION_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label.ar} / {label.en}</option>
          ))}
        </select>
        <button type="submit" className="btn-small btn-small--primary">
          <span className="ar">تطبيق</span>
          <span className="en">Apply</span>
        </button>
        {(appliedCaseId || appliedAction) && (
          <button type="button" className="btn-small btn-small--ghost" onClick={clearFilters}>
            <span className="ar">مسح</span>
            <span className="en">Clear</span>
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
                      <td className="audit-id">{log.user_id ? log.user_id.slice(0, 8) + '...' : '—'}</td>
                      <td className="audit-id">{log.case_id ? log.case_id.slice(0, 8) + '...' : '—'}</td>
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
