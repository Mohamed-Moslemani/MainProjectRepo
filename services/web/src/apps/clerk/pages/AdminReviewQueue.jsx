import { useState, useEffect, useCallback } from 'react';
import { adminApi } from '@shared/api/admin';
import AgeBadge from '@shared/components/AgeBadge';
import ReconciliationDiff from '@shared/components/ReconciliationDiff';
import L from '@shared/components/L';

const SERVICE_LABELS = {
  id_new: { ar: 'هوية جديدة', en: 'New ID' },
  id_renewal: { ar: 'تجديد هوية', en: 'ID Renewal' },
  passport_new: { ar: 'جواز سفر جديد', en: 'New Passport' },
  passport_renewal: { ar: 'تجديد جواز سفر', en: 'Passport Renewal' },
};

const FIELD_LABELS = {
  full_name: { ar: 'الاسم الكامل', en: 'Full Name' },
  father_name: { ar: 'اسم الأب', en: "Father's Name" },
  mother_name: { ar: 'اسم الأم', en: "Mother's Name" },
  date_of_birth: { ar: 'تاريخ الميلاد', en: 'Date of Birth' },
  place_of_birth: { ar: 'مكان الميلاد', en: 'Place of Birth' },
  gender: { ar: 'الجنس', en: 'Gender' },
  registry_number: { ar: 'رقم السجل', en: 'Registry Number' },
  registry_place: { ar: 'مكان السجل', en: 'Registry Place' },
  phone: { ar: 'الهاتف', en: 'Phone' },
  address: { ar: 'العنوان', en: 'Address' },
  marital_status: { ar: 'الحالة الاجتماعية', en: 'Marital Status' },
  email: { ar: 'البريد الإلكتروني', en: 'Email' },
};

const GOVERNORATES = {
  'Beirut': 'بيروت',
  'Mount Lebanon': 'جبل لبنان',
  'North Lebanon': 'الشمال',
  'Akkar': 'عكار',
  'South Lebanon': 'الجنوب',
  'Nabatieh': 'النبطية',
  'Beqaa': 'البقاع',
  'Baalbek-Hermel': 'بعلبك الهرمل',
};

export default function AdminReviewQueue() {
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedCase, setSelectedCase] = useState(null);
  const [caseDetail, setCaseDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionModal, setActionModal] = useState(null); // 'approve' | 'reject' | 'need_info'
  const [notes, setNotes] = useState('');
  const [rejectionReasons, setRejectionReasons] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState('');

  const loadQueue = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await adminApi.getCases({ status: 'risk_evaluated', limit: 100 });
      setCases(data.cases);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadQueue(); }, [loadQueue]);

  const openCase = async (c) => {
    setSelectedCase(c);
    setCaseDetail(null);
    setDetailLoading(true);
    try {
      const [fullRes, docsRes, trackRes] = await Promise.all([
        adminApi.getCaseFull(c.id),
        adminApi.getCaseDocuments(c.id),
        adminApi.getCaseTracking(c.id),
      ]);
      setCaseDetail({
        ...fullRes.data,
        documents: docsRes.data,
        tracking: trackRes.data,
      });
    } catch {
      setCaseDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleAction = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const payload = { notes: notes || undefined };
      if (actionModal === 'approve') {
        payload.status = 'approved';
      } else if (actionModal === 'reject') {
        payload.status = 'rejected';
        if (rejectionReasons.trim()) {
          payload.rejection_reasons = rejectionReasons.split('\n').map(r => r.trim()).filter(Boolean);
        }
      } else if (actionModal === 'need_info') {
        payload.status = 'need_info';
      }
      await adminApi.updateCaseStatus(selectedCase.id, payload);
      setSuccess(`Case ${selectedCase.tracking_id} updated to ${payload.status}`);
      setActionModal(null);
      setNotes('');
      setRejectionReasons('');
      setSelectedCase(null);
      setCaseDetail(null);
      setTimeout(() => setSuccess(''), 4000);
      loadQueue();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to update');
    } finally {
      setSubmitting(false);
    }
  };

  const riskColor = (score) => {
    if (score <= 25) return '#22c55e';
    if (score <= 60) return '#f59e0b';
    return '#ef4444';
  };

  const getGov = (place) => {
    if (!place) return null;
    const lower = place.toLowerCase();
    for (const [en, ar] of Object.entries(GOVERNORATES)) {
      if (lower.includes(en.toLowerCase()) || lower.includes(ar)) return { en, ar };
    }
    return null;
  };

  // ── Review detail panel ──
  if (selectedCase && caseDetail) {
    const d = caseDetail;
    const c = d.case;
    const owner = d.owner;
    const risk = c.risk_result || {};
    const recon = c.reconciliation_result || {};
    const liveness = c.liveness_result || {};
    const svcLabel = SERVICE_LABELS[c.service_type] || { ar: c.service_type, en: c.service_type };
    const gov = getGov(owner?.registry_place || owner?.place_of_birth);

    return (
      <div className="admin-page">
        <button className="btn-back" onClick={() => { setSelectedCase(null); setCaseDetail(null); }}>
          <L ar="← العودة للقائمة" en="← Back to Queue" />
        </button>

        <div className="review-header">
          <div className="review-header__left">
            <h1 className="review-header__tracking">#{c.tracking_id}</h1>
            <span className="review-header__service">
              <L>{{ ar: <>{svcLabel.ar}</>, en: <>{svcLabel.en}</> }}</L>
            </span>
          </div>
          <div className="review-header__right">
            <span className="review-header__status">
              <L ar="مراجعة يدوية" en="Manual Review" />
            </span>
            <AgeBadge createdAt={c.created_at} />
            <span className="review-header__date">
              {new Date(c.created_at).toLocaleDateString('ar-LB')}
            </span>
          </div>
        </div>

        {/* Risk Score Banner */}
        <div className="risk-banner" style={{ borderColor: riskColor(risk.risk_score || 0) }}>
          <div className="risk-banner__score" style={{ color: riskColor(risk.risk_score || 0) }}>
            {risk.risk_score != null ? Math.round(risk.risk_score) : '—'}
          </div>
          <div className="risk-banner__details">
            <strong>
              <L ar="درجة المخاطر" en="Risk Score" />
            </strong>
            <p>
              <L>{{ ar: <>القرار الآلي: {risk.routing === 'manual_review' ? 'مراجعة يدوية' : risk.routing || '—'}</>, en: <>AI Decision: {risk.routing || '—'}</> }}</L>
            </p>
            {risk.breakdown && (
              <div className="risk-breakdown">
                {Object.entries(risk.breakdown).map(([k, v]) => (
                  <span key={k} className="risk-breakdown__item">
                    {k}: <strong>{typeof v === 'number' ? v.toFixed(1) : v}</strong>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="review-grid">
          {/* Applicant Info */}
          <div className="review-section">
            <h3>
              <L ar="معلومات مقدم الطلب" en="Applicant Information" />
            </h3>
            {owner ? (
              <dl className="review-dl">
                {['full_name', 'father_name', 'mother_name', 'date_of_birth', 'place_of_birth', 'gender', 'registry_number', 'registry_place', 'phone', 'address', 'marital_status', 'email'].map(field => {
                  if (!owner[field]) return null;
                  const fl = FIELD_LABELS[field] || { ar: field, en: field };
                  return (
                    <div key={field} className="review-dl__row">
                      <dt><L>{{ ar: <>{fl.ar}</>, en: <>{fl.en}</> }}</L></dt>
                      <dd>{String(owner[field])}</dd>
                    </div>
                  );
                })}
                {gov && (
                  <div className="review-dl__row">
                    <dt><L ar="المحافظة" en="Governorate" /></dt>
                    <dd><L>{{ ar: <>{gov.ar}</>, en: <>({gov.en})</> }}</L></dd>
                  </div>
                )}
              </dl>
            ) : <p style={{ color: '#9ca3af' }}>No owner data</p>}
          </div>

          {/* Declared Fields vs OCR */}
          <div className="review-section">
            <h3>
              <L ar="البيانات المصرّحة" en="Declared Fields" />
            </h3>
            {c.declared_fields && Object.keys(c.declared_fields).length > 0 ? (
              <dl className="review-dl">
                {Object.entries(c.declared_fields).map(([key, val]) => {
                  const fl = FIELD_LABELS[key] || { ar: key, en: key };
                  const mismatch = recon.mismatch_flags?.includes(key);
                  return (
                    <div key={key} className={`review-dl__row ${mismatch ? 'review-dl__row--mismatch' : ''}`}>
                      <dt><L>{{ ar: <>{fl.ar}</>, en: <>{fl.en}</> }}</L></dt>
                      <dd>
                        {String(val)}
                        {mismatch && <span className="mismatch-badge">⚠ mismatch</span>}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            ) : <p style={{ color: '#9ca3af' }}>No declared fields</p>}
          </div>

          {/* Reconciliation */}
          <div className="review-section">
            <h3>
              <L ar="نتيجة المطابقة" en="Reconciliation" />
            </h3>
            <dl className="review-dl">
              <div className="review-dl__row">
                <dt><L ar="نسبة التكامل" en="Integrity Score" /></dt>
                <dd style={{ fontWeight: 700 }}>
                  {recon.integrity_score != null ? `${Math.round(recon.integrity_score * 100)}%` : '—'}
                </dd>
              </div>
              <div className="review-dl__row">
                <dt><L ar="النتيجة" en="Validation" /></dt>
                <dd>{recon.validation_result || '—'}</dd>
              </div>
              {recon.mismatch_flags?.length > 0 && (
                <div className="review-dl__row">
                  <dt><L ar="حقول غير متطابقة" en="Mismatches" /></dt>
                  <dd>
                    {recon.mismatch_flags.map((f, i) => (
                      <span key={i} className="mismatch-tag">{f}</span>
                    ))}
                  </dd>
                </div>
              )}
            </dl>
          </div>

          {/* Liveness / Face */}
          <div className="review-section">
            <h3>
              <L ar="التحقق من الوجه" en="Face Verification" />
            </h3>
            <dl className="review-dl">
              <div className="review-dl__row">
                <dt><L ar="حالة الحيوية" en="Liveness" /></dt>
                <dd>
                  {liveness.liveness_passed
                    ? <span style={{ color: '#22c55e', fontWeight: 700 }}>✓ Passed</span>
                    : liveness.status
                      ? <span style={{ color: '#ef4444', fontWeight: 700 }}>✗ {liveness.status}</span>
                      : '—'}
                </dd>
              </div>
              <div className="review-dl__row">
                <dt><L ar="الثقة" en="Confidence" /></dt>
                <dd>{liveness.confidence != null ? `${liveness.confidence.toFixed(1)}%` : '—'}</dd>
              </div>
              <div className="review-dl__row">
                <dt><L ar="تشابه الوجه" en="Similarity" /></dt>
                <dd>{liveness.similarity_score != null ? `${liveness.similarity_score.toFixed(1)}%` : '—'}</dd>
              </div>
              {liveness.reasons?.length > 0 && (
                <div className="review-dl__row">
                  <dt><L ar="ملاحظات" en="Reasons" /></dt>
                  <dd>
                    {liveness.reasons.map((r, i) => <div key={i} style={{ color: '#f59e0b', fontSize: '0.85rem' }}>{r}</div>)}
                  </dd>
                </div>
              )}
            </dl>
          </div>

          {/* Reconciliation diff */}
          {d.reconciliation_result?.field_results && (
            <div className="review-section">
              <ReconciliationDiff reconciliation={d.reconciliation_result} />
            </div>
          )}

          {/* Documents */}
          <div className="review-section">
            <h3>
              <L>{{ ar: <>المستندات ({d.documents?.length || 0})</>, en: <>Documents</> }}</L>
            </h3>
            <div className="review-docs">
              {(d.documents || []).map(doc => (
                <div key={doc.id} className="review-doc">
                  <span className="review-doc__type">{doc.document_type}</span>
                  <span className="review-doc__size">{(doc.file_size / 1024).toFixed(0)} KB</span>
                  {doc.ocr_status === 'completed' && <span className="review-doc__badge">OCR ✓</span>}
                  {doc.retake_required && <span className="review-doc__badge review-doc__badge--warn">Retake</span>}
                </div>
              ))}
            </div>
          </div>

          {/* Payments */}
          {d.payments?.length > 0 && (
            <div className="review-section">
              <h3><L ar="المدفوعات" en="Payments" /></h3>
              {d.payments.map(p => (
                <div key={p.id} className="review-payment">
                  <span>${(p.amount / 100).toFixed(2)}</span>
                  <span className={`status-badge status-badge--${p.status}`}>{p.status}</span>
                  <span>{new Date(p.created_at).toLocaleDateString('ar-LB')}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Action Buttons */}
        <div className="review-actions">
          <button className="review-action-btn review-action-btn--approve" onClick={() => { setActionModal('approve'); setNotes(''); }}>
            <L ar="✓ موافقة" en="✓ Approve" />
          </button>
          <button className="review-action-btn review-action-btn--need-info" onClick={() => { setActionModal('need_info'); setNotes(''); }}>
            <L ar="? طلب معلومات" en="? Request Info" />
          </button>
          <button className="review-action-btn review-action-btn--reject" onClick={() => { setActionModal('reject'); setNotes(''); setRejectionReasons(''); }}>
            <L ar="✗ رفض" en="✗ Reject" />
          </button>
        </div>

        {/* Action Modal */}
        {actionModal && (
          <div className="modal-overlay" onClick={() => setActionModal(null)}>
            <div className="modal" onClick={e => e.stopPropagation()}>
              <h3 className="modal__title">
                {actionModal === 'approve' && <><L ar="تأكيد الموافقة" en="Confirm Approval" /></>}
                {actionModal === 'reject' && <><L ar="تأكيد الرفض" en="Confirm Rejection" /></>}
                {actionModal === 'need_info' && <><L ar="طلب معلومات إضافية" en="Request More Info" /></>}
              </h3>
              <p className="modal__subtitle">{selectedCase.tracking_id}</p>
              <form onSubmit={handleAction}>
                {actionModal === 'reject' && (
                  <div className="form-group">
                    <label className="form-label">
                      <L ar="أسباب الرفض (سبب في كل سطر)" en="Rejection Reasons (one per line)" />
                    </label>
                    <textarea className="form-input" rows={3} value={rejectionReasons}
                      onChange={e => setRejectionReasons(e.target.value)}
                      placeholder="جودة المستند غير كافية&#10;معلومات غير صحيحة" required />
                  </div>
                )}
                <div className="form-group">
                  <label className="form-label">
                    <L>{{ ar: <>ملاحظات {actionModal !== 'reject' ? '(مطلوب)' : '(اختياري)'}</>, en: <>Notes {actionModal !== 'reject' ? '(required)' : '(optional)'}</> }}</L>
                  </label>
                  <textarea className="form-input" rows={2} value={notes}
                    onChange={e => setNotes(e.target.value)}
                    placeholder="أضف ملاحظة للمواطن..."
                    required={actionModal !== 'reject'} />
                </div>
                <div className="modal__actions">
                  <button type="button" className="btn-small btn-small--ghost" onClick={() => setActionModal(null)}>
                    <L ar="إلغاء" en="Cancel" />
                  </button>
                  <button type="submit" className={`btn-small btn-small--${actionModal === 'reject' ? 'danger' : 'primary'}`} disabled={submitting}>
                    {submitting ? '...' : <><L ar="تأكيد" en="Confirm" /></>}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Detail loading ──
  if (selectedCase && detailLoading) {
    return (
      <div className="admin-page">
        <button className="btn-back" onClick={() => setSelectedCase(null)}>
          <L ar="← العودة" en="← Back" />
        </button>
        <div className="admin-loading"><div className="spinner spinner--dark" /></div>
      </div>
    );
  }

  // ── Queue list ──
  return (
    <div className="admin-page">
      <div className="admin-page__header">
        <h1 className="admin-page__title">
          <L ar="طابور المراجعة اليدوية" en="Manual Review Queue" />
        </h1>
        <p className="admin-page__subtitle">
          <L ar="الطلبات التي لم تحصل على ثقة كافية من الذكاء الاصطناعي — تحتاج قرار الموظف" en="Cases with low AI confidence — require clerk decision" />
        </p>
      </div>

      {success && <div className="alert alert--success">{success}</div>}

      {loading ? (
        <div className="admin-loading"><div className="spinner spinner--dark" /></div>
      ) : cases.length === 0 ? (
        <div className="admin-empty" style={{ textAlign: 'center', padding: '4rem 2rem' }}>
          <div style={{ fontSize: '4rem', marginBottom: '1rem' }}>✓</div>
          <h3><L ar="لا توجد طلبات بحاجة لمراجعة" en="No cases need review" /></h3>
          <p style={{ color: '#9ca3af' }}><L ar="لا شيء في الانتظار" en="All caught up!" /></p>
        </div>
      ) : (
        <div className="review-queue">
          {cases.map(c => {
            const svcLabel = SERVICE_LABELS[c.service_type] || { ar: c.service_type, en: c.service_type };
            const riskScore = c.risk_result?.risk_score;
            return (
              <div key={c.id} className="review-queue__card" onClick={() => openCase(c)}>
                <div className="review-queue__card-left">
                  <span className="review-queue__tracking">#{c.tracking_id}</span>
                  <span className="review-queue__service">
                    <L>{{ ar: <>{svcLabel.ar}</>, en: <>{svcLabel.en}</> }}</L>
                  </span>
                  <span className="review-queue__date">
                    {new Date(c.created_at).toLocaleDateString('ar-LB')}
                  </span>
                  <AgeBadge createdAt={c.created_at} />
                </div>
                <div className="review-queue__card-right">
                  {riskScore != null && (
                    <span className="review-queue__risk" style={{ color: riskColor(riskScore) }}>
                      Risk: {Math.round(riskScore)}
                    </span>
                  )}
                  <span className="review-queue__arrow">←</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}