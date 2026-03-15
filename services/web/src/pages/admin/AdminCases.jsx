import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { adminApi } from '../../api/admin';

const ALL_STATUSES = [
  'draft', 'submitted', 'validated', 'risk_evaluated',
  'approved', 'rejected', 'need_info',
  'in_production', 'ready_for_pickup', 'closed',
];

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

const SERVICE_LABELS = {
  id_new: { ar: 'هوية جديدة', en: 'New ID' },
  id_renewal: { ar: 'تجديد هوية', en: 'ID Renewal' },
  passport_new: { ar: 'جواز جديد', en: 'New Passport' },
  passport_renewal: { ar: 'تجديد جواز', en: 'Passport Renewal' },
};

const TRANSITIONS = {
  draft: ['submitted'],
  submitted: ['validated'],
  validated: ['risk_evaluated'],
  risk_evaluated: ['approved', 'rejected', 'need_info'],
  need_info: ['submitted'],
  approved: ['in_production'],
  in_production: ['ready_for_pickup'],
  ready_for_pickup: ['closed'],
};

const PAGE_SIZE = 20;

export default function AdminCases() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filterStatus = searchParams.get('status') || '';

  const [cases, setCases] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [expanded, setExpanded] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [updateModal, setUpdateModal] = useState(null);
  const [updateNotes, setUpdateNotes] = useState('');
  const [updateStatus, setUpdateStatus] = useState('');
  const [updateRejectionReasons, setUpdateRejectionReasons] = useState('');
  const [updating, setUpdating] = useState(false);

  const loadCases = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { data } = await adminApi.getCases({
        status: filterStatus || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setCases(data.cases);
      setTotal(data.total);
    } catch (err) {
      setError(err.response?.data?.detail || 'فشل في تحميل الطلبات');
    } finally {
      setLoading(false);
    }
  }, [filterStatus, page]);

  useEffect(() => {
    loadCases();
  }, [loadCases]);

  const handleFilterChange = (status) => {
    setPage(0);
    setExpanded(null);
    if (status) {
      setSearchParams({ status });
    } else {
      setSearchParams({});
    }
  };

  const handleExpand = async (caseId) => {
    if (expanded === caseId) {
      setExpanded(null);
      setDetail(null);
      return;
    }
    setExpanded(caseId);
    setDetailLoading(true);
    try {
      const [caseRes, docsRes] = await Promise.all([
        adminApi.getCaseDetail(caseId),
        adminApi.getCaseDocuments(caseId),
      ]);
      setDetail({ ...caseRes.data, documents: docsRes.data });
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const openUpdateModal = (c) => {
    const nextStatuses = TRANSITIONS[c.status] || [];
    if (nextStatuses.length === 0) return;
    setUpdateModal(c);
    setUpdateStatus(nextStatuses[0]);
    setUpdateNotes('');
    setUpdateRejectionReasons('');
  };

  const handleStatusUpdate = async (e) => {
    e.preventDefault();
    setUpdating(true);
    try {
      const payload = { status: updateStatus, notes: updateNotes || undefined };
      if (updateStatus === 'rejected' && updateRejectionReasons.trim()) {
        payload.rejection_reasons = updateRejectionReasons
          .split('\n')
          .map((r) => r.trim())
          .filter(Boolean);
      }
      await adminApi.updateCaseStatus(updateModal.id, payload);
      setUpdateModal(null);
      loadCases();
      if (expanded === updateModal.id) {
        setExpanded(null);
        setDetail(null);
      }
    } catch (err) {
      alert(err.response?.data?.detail || 'فشل في تحديث الحالة');
    } finally {
      setUpdating(false);
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const getStatusLabel = (s) => STATUS_LABELS[s] || { ar: s, en: s };
  const getServiceLabel = (s) => SERVICE_LABELS[s] || { ar: s, en: s };

  return (
    <div className="admin-page">
      <div className="admin-page__header">
        <h1 className="admin-page__title">
          <span className="ar">الطلبات</span>
          <span className="en">Cases</span>
        </h1>
        <p className="admin-page__subtitle">
          <span className="ar">{total} طلب إجمالي</span>
          <span className="en">{total} total cases</span>
        </p>
      </div>

      {/* Filter bar */}
      <div className="filter-bar">
        <button
          className={`filter-chip ${!filterStatus ? 'filter-chip--active' : ''}`}
          onClick={() => handleFilterChange('')}
        >
          <span className="ar">الكل</span>
          <span className="en">All</span>
        </button>
        {ALL_STATUSES.map((s) => {
          const label = getStatusLabel(s);
          return (
            <button
              key={s}
              className={`filter-chip ${filterStatus === s ? 'filter-chip--active' : ''}`}
              onClick={() => handleFilterChange(s)}
            >
              <span className="ar">{label.ar}</span>
              <span className="en">{label.en}</span>
            </button>
          );
        })}
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {loading ? (
        <div className="admin-loading">
          <div className="spinner spinner--dark" />
          <span className="ar">جارٍ التحميل...</span>
        </div>
      ) : cases.length === 0 ? (
        <div className="admin-empty">
          <span className="ar">لا توجد طلبات</span>
          <span className="en">No cases found</span>
        </div>
      ) : (
        <>
          <div className="cases-table-wrap">
            <table className="cases-table">
              <thead>
                <tr>
                  <th><span className="ar">رقم التتبع</span><span className="en">Tracking ID</span></th>
                  <th><span className="ar">الخدمة</span><span className="en">Service</span></th>
                  <th><span className="ar">الحالة</span><span className="en">Status</span></th>
                  <th><span className="ar">التاريخ</span><span className="en">Created</span></th>
                  <th><span className="ar">إجراءات</span><span className="en">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {cases.map((c) => {
                  const svcLabel = getServiceLabel(c.service_type);
                  const stLabel = getStatusLabel(c.status);
                  return (
                    <>
                      <tr
                        key={c.id}
                        className={expanded === c.id ? 'cases-table__row--expanded' : ''}
                        onClick={() => handleExpand(c.id)}
                      >
                        <td className="cases-table__tracking">{c.tracking_id}</td>
                        <td>
                          <span className="ar">{svcLabel.ar}</span>
                          <span className="en">{svcLabel.en}</span>
                        </td>
                        <td>
                          <span className={`status-badge status-badge--${c.status}`}>
                            <span className="ar">{stLabel.ar}</span>
                            <span className="en">{stLabel.en}</span>
                          </span>
                        </td>
                        <td className="cases-table__date">
                          {new Date(c.created_at).toLocaleDateString('ar-LB')}
                        </td>
                        <td>
                          {(TRANSITIONS[c.status] || []).length > 0 && (
                            <button
                              className="btn-small btn-small--primary"
                              onClick={(e) => {
                                e.stopPropagation();
                                openUpdateModal(c);
                              }}
                            >
                              <span className="ar">تحديث</span>
                              <span className="en">Update</span>
                            </button>
                          )}
                        </td>
                      </tr>

                      {expanded === c.id && (
                        <tr key={`${c.id}-detail`} className="cases-table__detail-row">
                          <td colSpan="5">
                            {detailLoading ? (
                              <div className="admin-loading" style={{ padding: '1.5rem' }}>
                                <div className="spinner spinner--dark" />
                              </div>
                            ) : detail ? (
                              <CaseDetailView detail={detail} />
                            ) : (
                              <p style={{ padding: '1rem', color: 'var(--gray-500)' }}>
                                <span className="ar">فشل في تحميل التفاصيل</span>
                              </p>
                            )}
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="pagination">
              <button className="pagination__btn" disabled={page === 0} onClick={() => setPage(page - 1)}>
                <span className="ar">السابق</span>
                <span className="en">Previous</span>
              </button>
              <span className="pagination__info">
                <span className="ar">صفحة {page + 1} من {totalPages}</span>
                <span className="en">Page {page + 1} of {totalPages}</span>
              </span>
              <button className="pagination__btn" disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>
                <span className="ar">التالي</span>
                <span className="en">Next</span>
              </button>
            </div>
          )}
        </>
      )}

      {/* Status Update Modal */}
      {updateModal && (
        <div className="modal-overlay" onClick={() => setUpdateModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="modal__title">
              <span className="ar">تحديث حالة الطلب</span>
              <span className="en">Update Case Status</span>
            </h3>
            <p className="modal__subtitle">
              {updateModal.tracking_id} &mdash;{' '}
              {getServiceLabel(updateModal.service_type).ar}
            </p>

            <form onSubmit={handleStatusUpdate}>
              <div className="form-group">
                <label className="form-label">
                  <span className="ar">الحالة الحالية</span>
                  <span className="en">Current Status</span>
                </label>
                <span className={`status-badge status-badge--${updateModal.status}`}>
                  {getStatusLabel(updateModal.status).ar}
                </span>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="newStatus">
                  <span className="ar">الحالة الجديدة</span>
                  <span className="en">New Status</span>
                </label>
                <select
                  id="newStatus"
                  className="form-input"
                  value={updateStatus}
                  onChange={(e) => setUpdateStatus(e.target.value)}
                >
                  {(TRANSITIONS[updateModal.status] || []).map((s) => {
                    const label = getStatusLabel(s);
                    return (
                      <option key={s} value={s}>{label.ar} / {label.en}</option>
                    );
                  })}
                </select>
              </div>

              {updateStatus === 'rejected' && (
                <div className="form-group">
                  <label className="form-label" htmlFor="rejectionReasons">
                    <span className="ar">أسباب الرفض (سبب في كل سطر)</span>
                    <span className="en">Rejection Reasons (one per line)</span>
                  </label>
                  <textarea
                    id="rejectionReasons"
                    className="form-input"
                    rows={3}
                    value={updateRejectionReasons}
                    onChange={(e) => setUpdateRejectionReasons(e.target.value)}
                    placeholder="جودة المستند غير كافية&#10;فشل التحقق من الوجه"
                  />
                </div>
              )}

              <div className="form-group">
                <label className="form-label" htmlFor="notes">
                  <span className="ar">ملاحظات (اختياري)</span>
                  <span className="en">Notes (optional)</span>
                </label>
                <textarea
                  id="notes"
                  className="form-input"
                  rows={2}
                  value={updateNotes}
                  onChange={(e) => setUpdateNotes(e.target.value)}
                  placeholder="أضف ملاحظة..."
                />
              </div>

              <div className="modal__actions">
                <button type="button" className="btn-small btn-small--ghost" onClick={() => setUpdateModal(null)}>
                  <span className="ar">إلغاء</span>
                  <span className="en">Cancel</span>
                </button>
                <button type="submit" className="btn-small btn-small--primary" disabled={updating}>
                  {updating ? (
                    <span className="ar">جارٍ التحديث...</span>
                  ) : (
                    <>
                      <span className="ar">تأكيد</span>
                      <span className="en">Confirm</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function CaseDetailView({ detail }) {
  const getServiceLabel = (s) => SERVICE_LABELS[s] || { ar: s, en: s };
  const getStatusLabel = (s) => STATUS_LABELS[s] || { ar: s, en: s };

  return (
    <div className="case-detail">
      <div className="case-detail__grid">
        <div className="case-detail__section">
          <h4><span className="ar">معلومات</span><span className="en">Info</span></h4>
          <dl className="case-detail__dl">
            <dt><span className="ar">رقم الطلب</span></dt><dd>{detail.id}</dd>
            <dt><span className="ar">الخدمة</span></dt><dd>{getServiceLabel(detail.service_type).ar}</dd>
            <dt><span className="ar">الحالة</span></dt>
            <dd><span className={`status-badge status-badge--${detail.status}`}>{getStatusLabel(detail.status).ar}</span></dd>
            <dt><span className="ar">تاريخ الإنشاء</span></dt><dd>{new Date(detail.created_at).toLocaleString('ar-LB')}</dd>
            {detail.notes && <><dt><span className="ar">ملاحظات</span></dt><dd>{detail.notes}</dd></>}
          </dl>
        </div>

        {detail.risk_result && (
          <div className="case-detail__section">
            <h4><span className="ar">تقييم المخاطر</span><span className="en">Risk Assessment</span></h4>
            <dl className="case-detail__dl">
              <dt><span className="ar">درجة المخاطر</span></dt>
              <dd>
                <span className={`risk-score ${detail.risk_result.total_score > 60 ? 'risk-score--high' : detail.risk_result.total_score > 25 ? 'risk-score--medium' : 'risk-score--low'}`}>
                  {detail.risk_result.total_score}
                </span>
              </dd>
              <dt><span className="ar">القرار</span></dt><dd>{detail.risk_result.decision}</dd>
            </dl>
          </div>
        )}

        {detail.reconciliation_result && (
          <div className="case-detail__section">
            <h4><span className="ar">المطابقة</span><span className="en">Reconciliation</span></h4>
            <dl className="case-detail__dl">
              <dt><span className="ar">نسبة التطابق</span></dt>
              <dd>{detail.reconciliation_result.match_rate != null
                ? `${Math.round(detail.reconciliation_result.match_rate * 100)}%`
                : 'N/A'}</dd>
              {detail.reconciliation_result.mismatches?.length > 0 && (
                <>
                  <dt><span className="ar">عدم تطابق</span></dt>
                  <dd>
                    {detail.reconciliation_result.mismatches.map((m, i) => (
                      <span key={i} className="mismatch-tag">{m.field || m}</span>
                    ))}
                  </dd>
                </>
              )}
            </dl>
          </div>
        )}
      </div>

      {detail.rejection_reasons?.length > 0 && (
        <div className="case-detail__section">
          <h4><span className="ar">أسباب الرفض</span><span className="en">Rejection Reasons</span></h4>
          <ul className="rejection-list">
            {detail.rejection_reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {detail.documents?.length > 0 && (
        <div className="case-detail__section">
          <h4><span className="ar">المستندات ({detail.documents.length})</span></h4>
          <div className="doc-chips">
            {detail.documents.map((doc) => (
              <div key={doc.id} className="doc-chip">
                <span className="doc-chip__type">{doc.document_type}</span>
                <span className="doc-chip__size">{(doc.file_size / 1024).toFixed(0)} KB</span>
                {doc.ocr_status === 'completed' && <span className="doc-chip__ocr">OCR</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.declared_fields && Object.keys(detail.declared_fields).length > 0 && (
        <div className="case-detail__section">
          <h4><span className="ar">البيانات المصرّحة</span><span className="en">Declared Fields</span></h4>
          <dl className="case-detail__dl">
            {Object.entries(detail.declared_fields).map(([key, val]) => (
              <span key={key}><dt>{key}</dt><dd>{String(val)}</dd></span>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}
