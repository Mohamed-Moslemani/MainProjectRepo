import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { adminApi } from '@shared/api/admin';
import AgeBadge from '@shared/components/AgeBadge';
import ReconciliationDiff from '@shared/components/ReconciliationDiff';
import L from '@shared/components/L';
import { useAuth } from '@shared/context/useAuth';
import { useToast } from '@shared/context/useToast';
import { useConfirm } from '@shared/components/ConfirmDialog';

const ALL_STATUSES = [
  'draft', 'submitted', 'validated', 'risk_evaluated',
  'approved', 'payment_pending', 'rejected', 'need_info',
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

// Clerk can only transition these statuses (approve/reject only from review queue)
const TRANSITIONS = {
  payment_pending: ['in_production'],
  in_production: ['ready_for_pickup'],
  ready_for_pickup: ['closed'],
};

const PAGE_SIZE = 20;

export default function AdminCases() {
  const { user } = useAuth();
  const toast = useToast();
  const confirm = useConfirm();
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

  // Bulk select: lets a clerk advance a queue of cases through a
  // routine status (e.g. 50 ready_for_pickup → closed) in one go.
  // Only routine transitions show; approve/reject still go through
  // the review queue per-case.
  const [selected, setSelected] = useState(() => new Set());
  const [bulkRunning, setBulkRunning] = useState(false);

  const toggleSelected = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const allOnPageSelected = cases.length > 0 && cases.every((c) => selected.has(c.id));
  const togglePageSelection = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        cases.forEach((c) => next.delete(c.id));
      } else {
        cases.forEach((c) => next.add(c.id));
      }
      return next;
    });
  };

  // Common valid transition across every currently-selected case.
  // Returns [] if the selection mixes states that don't share a
  // routine clerk transition — bulk panel hides itself in that case.
  const bulkTargets = (() => {
    if (selected.size === 0) return [];
    const selectedCases = cases.filter((c) => selected.has(c.id));
    if (selectedCases.length !== selected.size) return [];
    const sets = selectedCases.map((c) => new Set(TRANSITIONS[c.status] || []));
    if (sets.some((s) => s.size === 0)) return [];
    const intersection = [...sets[0]].filter((t) => sets.every((s) => s.has(t)));
    return intersection;
  })();

  const runBulkTransition = async (targetStatus) => {
    if (selected.size === 0 || bulkRunning) return;
    const ok = await confirm({
      ar: {
        title: 'نقل الطلبات',
        message: `سيتم نقل ${selected.size} طلب(ات) إلى الحالة: ${targetStatus}.`,
        confirm: 'متابعة',
        cancel: 'إلغاء',
      },
      en: {
        title: 'Bulk transition',
        message: `Transition ${selected.size} case(s) → ${targetStatus}?`,
        confirm: 'Apply',
        cancel: 'Cancel',
      },
    });
    if (!ok) return;
    setBulkRunning(true);
    const ids = [...selected];
    let okCount = 0;
    let failCount = 0;
    for (const id of ids) {
      try {
        await adminApi.updateCaseStatus(id, { status: targetStatus });
        okCount += 1;
      } catch {
        failCount += 1;
      }
    }
    setSelected(new Set());
    setBulkRunning(false);
    await loadCases();
    alert(`Bulk transition done: ${okCount} succeeded, ${failCount} failed.`);
  };

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

  const handleExportCsv = async () => {
    try {
      const { data } = await adminApi.exportCasesCsv({
        status: filterStatus || undefined,
      });
      const url = window.URL.createObjectURL(new Blob([data], { type: 'text/csv' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `docflow-cases-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch {
      // Inline alert is enough — no toast wired into this page yet.
      setError('فشل في تصدير CSV');
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
      <div className="admin-page__header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
        <div>
          <h1 className="admin-page__title">
            <L ar="الطلبات" en="Cases" />
          </h1>
          <p className="admin-page__subtitle">
            <L>{{ ar: <>{total} طلب إجمالي</>, en: <>{total} total cases</> }}</L>
          </p>
        </div>
        <button
          type="button"
          className="btn-small btn-small--ghost"
          onClick={handleExportCsv}
          title="Export current filter to CSV"
        >
          ⬇ <L ar="تصدير CSV" en="Export CSV" />
        </button>
      </div>

      {/* Filter bar */}
      <div className="filter-bar">
        <button
          className={`filter-chip ${!filterStatus ? 'filter-chip--active' : ''}`}
          onClick={() => handleFilterChange('')}
        >
          <L ar="الكل" en="All" />
        </button>
        {ALL_STATUSES.map((s) => {
          const label = getStatusLabel(s);
          return (
            <button
              key={s}
              className={`filter-chip ${filterStatus === s ? 'filter-chip--active' : ''}`}
              onClick={() => handleFilterChange(s)}
            >
              <L>{{ ar: <>{label.ar}</>, en: <>{label.en}</> }}</L>
            </button>
          );
        })}
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {selected.size > 0 && (
        <div className="bulk-bar">
          <span>
            <strong>{selected.size}</strong> selected
          </span>
          {bulkTargets.length > 0 ? (
            bulkTargets.map((t) => (
              <button
                key={t}
                type="button"
                className="btn-small btn-small--primary"
                disabled={bulkRunning}
                onClick={() => runBulkTransition(t)}
              >
                {bulkRunning ? 'Running…' : `Mark all → ${t}`}
              </button>
            ))
          ) : (
            <span style={{ color: '#6b7280', fontSize: '0.85rem' }}>
              Selection mixes statuses with no shared transition.
            </span>
          )}
          <button
            type="button"
            className="btn-small btn-small--ghost"
            onClick={() => setSelected(new Set())}
            disabled={bulkRunning}
          >
            Clear
          </button>
        </div>
      )}

      {loading ? (
        <div className="admin-loading">
          <div className="spinner spinner--dark" />
          <L ar="جارٍ التحميل..." en="Loading..." />
        </div>
      ) : cases.length === 0 ? (
        <div className="admin-empty">
          <L ar="لا توجد طلبات" en="No cases found" />
        </div>
      ) : (
        <>
          <div className="cases-table-wrap">
            <table className="cases-table">
              <thead>
                <tr>
                  <th style={{ width: 36 }}>
                    <input
                      type="checkbox"
                      aria-label="Select all on this page"
                      checked={allOnPageSelected}
                      onChange={togglePageSelection}
                    />
                  </th>
                  <th><L ar="رقم التتبع" en="Tracking ID" /></th>
                  <th><L ar="الخدمة" en="Service" /></th>
                  <th><L ar="الحالة" en="Status" /></th>
                  <th><L ar="التاريخ" en="Created" /></th>
                  <th><L ar="إجراءات" en="Actions" /></th>
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
                        <td onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            aria-label={`Select ${c.tracking_id}`}
                            checked={selected.has(c.id)}
                            onChange={() => toggleSelected(c.id)}
                          />
                        </td>
                        <td className="cases-table__tracking">{c.tracking_id}</td>
                        <td>
                          <L>{{ ar: <>{svcLabel.ar}</>, en: <>{svcLabel.en}</> }}</L>
                        </td>
                        <td>
                          <span className={`status-badge status-badge--${c.status}`}>
                            <L>{{ ar: <>{stLabel.ar}</>, en: <>{stLabel.en}</> }}</L>
                          </span>
                        </td>
                        <td className="cases-table__date">
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                            <AgeBadge createdAt={c.created_at} />
                            <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>
                              {new Date(c.created_at).toLocaleDateString('ar-LB')}
                            </span>
                          </div>
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: '0.4rem', justifyContent: 'flex-end' }}>
                            {(TRANSITIONS[c.status] || []).length > 0 && (
                              <button
                                className="btn-small btn-small--primary"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  openUpdateModal(c);
                                }}
                              >
                                <L ar="تحديث" en="Update" />
                              </button>
                            )}
                            {/* Hard-delete escape hatch — admin role
                                only. Used for testing fixtures and
                                rare right-to-erasure requests. The
                                action is audit-logged server-side. */}
                            {(user?.role === 'admin') && (
                              <button
                                className="btn-small"
                                style={{ color: '#fff', background: '#b91c1c', borderColor: '#b91c1c' }}
                                onClick={async (e) => {
                                  e.stopPropagation();
                                  const ok = await confirm({
                                    destructive: true,
                                    ar: {
                                      title: 'حذف نهائي للطلب',
                                      message: `سيتم حذف الطلب ${c.tracking_id} بشكل نهائي مع جميع المستندات ونتائج التعرّف والدفعات. الإجراء مسجّل في سجل التدقيق.`,
                                      confirm: 'حذف',
                                      cancel: 'إلغاء',
                                    },
                                    en: {
                                      title: 'Hard-delete case',
                                      message: `Permanently delete case ${c.tracking_id}? This wipes documents, OCR/face results, payments, and the case row. Audit-logged.`,
                                      confirm: 'Delete',
                                      cancel: 'Cancel',
                                    },
                                  });
                                  if (!ok) return;
                                  try {
                                    await adminApi.deleteCase(c.id);
                                    toast.success(`Deleted ${c.tracking_id}`);
                                    loadCases();
                                  } catch (err) {
                                    toast.error(err.response?.data?.detail || 'Delete failed');
                                  }
                                }}
                              >
                                <L ar="حذف" en="Delete" />
                              </button>
                            )}
                          </div>
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
                                <L ar="فشل في تحميل التفاصيل" en="Failed to load details" />
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
                <L ar="السابق" en="Previous" />
              </button>
              <span className="pagination__info">
                <L>{{ ar: <>صفحة {page + 1} من {totalPages}</>, en: <>Page {page + 1} of {totalPages}</> }}</L>
              </span>
              <button className="pagination__btn" disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>
                <L ar="التالي" en="Next" />
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
              <L ar="تحديث حالة الطلب" en="Update Case Status" />
            </h3>
            <p className="modal__subtitle">
              {updateModal.tracking_id} &mdash;{' '}
              {getServiceLabel(updateModal.service_type).ar}
            </p>

            <form onSubmit={handleStatusUpdate}>
              <div className="form-group">
                <label className="form-label">
                  <L ar="الحالة الحالية" en="Current Status" />
                </label>
                <span className={`status-badge status-badge--${updateModal.status}`}>
                  {getStatusLabel(updateModal.status).ar}
                </span>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="newStatus">
                  <L ar="الحالة الجديدة" en="New Status" />
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
                    <L ar="أسباب الرفض (سبب في كل سطر)" en="Rejection Reasons (one per line)" />
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
                  <L ar="ملاحظات (اختياري)" en="Notes (optional)" />
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
                  <L ar="إلغاء" en="Cancel" />
                </button>
                <button type="submit" className="btn-small btn-small--primary" disabled={updating}>
                  {updating ? (
                    <L ar="جارٍ التحديث..." en="Updating..." />
                  ) : (
                    <>
                      <L ar="تأكيد" en="Confirm" />
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
          <h4><L ar="معلومات" en="Info" /></h4>
          <dl className="case-detail__dl">
            <dt><L ar="رقم الطلب" en="Case ID" /></dt><dd>{detail.id}</dd>
            <dt><L ar="الخدمة" en="Service" /></dt><dd>{getServiceLabel(detail.service_type).ar}</dd>
            <dt><L ar="الحالة" en="Status" /></dt>
            <dd><span className={`status-badge status-badge--${detail.status}`}>{getStatusLabel(detail.status).ar}</span></dd>
            <dt><L ar="تاريخ الإنشاء" en="Created" /></dt><dd>{new Date(detail.created_at).toLocaleString('ar-LB')}</dd>
            {detail.notes && <><dt><L ar="ملاحظات" en="Notes" /></dt><dd>{detail.notes}</dd></>}
          </dl>
        </div>

        {detail.risk_result && (
          <div className="case-detail__section">
            <h4><L ar="تقييم المخاطر" en="Risk Assessment" /></h4>
            <dl className="case-detail__dl">
              <dt><L ar="درجة المخاطر" en="Risk score" /></dt>
              <dd>
                <span className={`risk-score ${detail.risk_result.total_score > 60 ? 'risk-score--high' : detail.risk_result.total_score > 25 ? 'risk-score--medium' : 'risk-score--low'}`}>
                  {detail.risk_result.total_score}
                </span>
              </dd>
              <dt><L ar="القرار" en="Decision" /></dt><dd>{detail.risk_result.decision}</dd>
            </dl>
          </div>
        )}

        {detail.reconciliation_result && (
          <div className="case-detail__section">
            <h4><L ar="المطابقة" en="Reconciliation" /></h4>
            <dl className="case-detail__dl">
              <dt><L ar="نسبة التطابق" en="Match score" /></dt>
              <dd>{detail.reconciliation_result.match_rate != null
                ? `${Math.round(detail.reconciliation_result.match_rate * 100)}%`
                : 'N/A'}</dd>
              {detail.reconciliation_result.mismatches?.length > 0 && (
                <>
                  <dt><L ar="عدم تطابق" en="Mismatches" /></dt>
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

      {detail.reconciliation_result?.field_results && (
        <div className="case-detail__section">
          <ReconciliationDiff reconciliation={detail.reconciliation_result} />
        </div>
      )}

      {detail.rejection_reasons?.length > 0 && (
        <div className="case-detail__section">
          <h4><L ar="أسباب الرفض" en="Rejection Reasons" /></h4>
          <ul className="rejection-list">
            {detail.rejection_reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {detail.documents?.length > 0 && (
        <div className="case-detail__section">
          <h4><L ar="المستندات" en="Documents" /> ({detail.documents.length})</h4>
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
          <h4><L ar="البيانات المصرّحة" en="Declared Fields" /></h4>
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
