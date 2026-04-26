import { useState, useEffect, useCallback } from 'react';
import { mukhtarApi } from '../../api/mukhtar';
import AuthImage from '../../components/AuthImage';
import AgeBadge from '../../components/AgeBadge';

const DOC_TYPE_LABELS = {
  selfie: { ar: 'صورة شخصية (سيلفي)', en: 'Selfie' },
  liveness_capture: { ar: 'صورة التحقق من الحياة', en: 'Liveness Capture' },
  national_id_front: { ar: 'الهوية - أمام', en: 'National ID (Front)' },
  national_id_back: { ar: 'الهوية - خلف', en: 'National ID (Back)' },
  old_passport_data_page: { ar: 'صفحة بيانات جواز السفر القديم', en: 'Old Passport Data Page' },
  civil_registry_extract: { ar: 'إخراج قيد فردي', en: 'Civil Registry Extract' },
  guardian_docs: { ar: 'وثائق الولي', en: 'Guardian Documents' },
  additional_identity_proof: { ar: 'إثبات هوية إضافي', en: 'Additional ID Proof' },
};

const STATUS_LABELS = {
  pending_mukhtar: { ar: 'بانتظار المصادقة', en: 'Pending Review', color: '#f59e0b' },
  approved: { ar: 'موافق عليه', en: 'Approved', color: '#22c55e' },
  payment_pending: { ar: 'بانتظار الدفع', en: 'Payment Pending', color: '#a855f7' },
  rejected: { ar: 'مرفوض', en: 'Rejected', color: '#ef4444' },
  need_info: { ar: 'بحاجة لمعلومات', en: 'Needs Info', color: '#f97316' },
  in_production: { ar: 'قيد الإنتاج', en: 'In Production', color: '#2563eb' },
  ready_for_pickup: { ar: 'جاهز للاستلام', en: 'Ready', color: '#16a34a' },
  closed: { ar: 'مغلق', en: 'Closed', color: '#6b7280' },
};

const SERVICE_LABELS = {
  passport_new: { ar: 'جواز سفر جديد', en: 'New Passport' },
  passport_renewal: { ar: 'تجديد جواز سفر', en: 'Passport Renewal' },
};

export default function MukhtarCases() {
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('pending_mukhtar');
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [modal, setModal] = useState(null);
  const [notes, setNotes] = useState('');
  const [rejectionReasons, setRejectionReasons] = useState('');
  // The three attestations a Lebanese mukhtar signs for in person:
  const [residenceVerified, setResidenceVerified] = useState(false);
  const [photoVerified, setPhotoVerified] = useState(false);
  const [presenceVerified, setPresenceVerified] = useState(false);
  const [residenceNotes, setResidenceNotes] = useState('');
  const [failedAttestationReason, setFailedAttestationReason] = useState('');
  const [deciding, setDeciding] = useState(false);
  const [alert, setAlert] = useState(null);
  const [transferModal, setTransferModal] = useState(false);
  const [availableMukhtars, setAvailableMukhtars] = useState([]);
  const [transferTarget, setTransferTarget] = useState('');
  const [transferReason, setTransferReason] = useState('');

  const loadCases = useCallback(() => {
    setLoading(true);
    mukhtarApi.getCases({ status: filter || undefined })
      .then(({ data }) => setCases(data.cases || []))
      .catch(() => setCases([]))
      .finally(() => setLoading(false));
  }, [filter]);

  useEffect(() => { loadCases(); }, [loadCases]);

  const openDetail = async (caseId) => {
    setSelected(caseId);
    setDetailLoading(true);
    try {
      const { data } = await mukhtarApi.getCaseDetail(caseId);
      setDetail(data);
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDownloadForm = async (caseId) => {
    try {
      const { data } = await mukhtarApi.downloadForm(caseId);
      const url = window.URL.createObjectURL(new Blob([data], { type: 'application/pdf' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `passport_application_${caseId}.pdf`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch {
      setAlert({ type: 'error', msg: 'Failed to download form' });
    }
  };

  const openTransferModal = async () => {
    try {
      const { data } = await mukhtarApi.getAvailableMukhtars(selected);
      setAvailableMukhtars(data.mukhtars || []);
      setTransferTarget('');
      setTransferReason('');
      setTransferModal(true);
    } catch {
      setAlert({ type: 'error', msg: 'Failed to load available mukhtars' });
    }
  };

  const handleTransfer = async () => {
    if (!transferTarget) {
      setAlert({ type: 'error', msg: 'Select a mukhtar to transfer to' });
      return;
    }
    setDeciding(true);
    try {
      const { data } = await mukhtarApi.transfer(selected, {
        target_mukhtar_id: transferTarget,
        reason: transferReason || null,
      });
      setAlert({ type: 'success', msg: data.message });
      setTransferModal(false);
      setSelected(null);
      setDetail(null);
      loadCases();
    } catch (err) {
      setAlert({ type: 'error', msg: err.response?.data?.detail || 'Transfer failed' });
    } finally {
      setDeciding(false);
    }
  };

  const allAttested = residenceVerified && photoVerified && presenceVerified;

  const resetDecisionForm = () => {
    setNotes('');
    setRejectionReasons('');
    setResidenceVerified(false);
    setPhotoVerified(false);
    setPresenceVerified(false);
    setResidenceNotes('');
    setFailedAttestationReason('');
  };

  const handleDecision = async (decision) => {
    if (decision === 'approve' && !allAttested) {
      setAlert({ type: 'error', msg: 'All three attestations (residence, photo, presence) are required to approve' });
      return;
    }
    if (decision === 'reject' && !rejectionReasons.trim()) {
      setAlert({ type: 'error', msg: 'Rejection reasons are required' });
      return;
    }
    setDeciding(true);
    try {
      await mukhtarApi.decide(selected, {
        decision,
        residence_verified: residenceVerified,
        photo_verified: photoVerified,
        presence_verified: presenceVerified,
        residence_notes: residenceNotes || null,
        failed_attestation_reason: failedAttestationReason || null,
        notes: notes || null,
        rejection_reasons: decision === 'reject' ? rejectionReasons.split('\n').filter(Boolean) : null,
      });
      setAlert({ type: 'success', msg: decision === 'approve' ? 'Application approved and stamped' : decision === 'reject' ? 'Application rejected' : 'More information requested' });
      setModal(null);
      setSelected(null);
      setDetail(null);
      resetDecisionForm();
      loadCases();
    } catch (err) {
      setAlert({ type: 'error', msg: err.response?.data?.detail || 'Decision failed' });
    } finally {
      setDeciding(false);
    }
  };

  return (
    <div className="admin-page">
      <div className="admin-page__header">
        <h1 className="admin-page__title">
          <span className="ar">الطلبات</span>
          <span className="en">Cases</span>
        </h1>
      </div>

      {alert && (
        <div className={`alert alert--${alert.type}`} style={{ marginBottom: '1rem' }}>
          {alert.msg}
          <button onClick={() => setAlert(null)} style={{ marginRight: '1rem', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 'bold' }}>x</button>
        </div>
      )}

      {/* Filter */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        {['pending_mukhtar', '', 'approved', 'rejected', 'need_info'].map((f) => (
          <button
            key={f}
            className={`btn btn--sm ${filter === f ? 'btn--primary' : 'btn--ghost'}`}
            onClick={() => setFilter(f)}
          >
            {f === '' ? 'All' : (STATUS_LABELS[f]?.en || f)}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="admin-loading"><div className="spinner spinner--dark" /></div>
      ) : cases.length === 0 ? (
        <div className="admin-empty">
          <span className="ar">لا توجد طلبات</span>
          <span className="en">No cases found</span>
        </div>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th><span className="ar">رقم التتبع</span><span className="en">Tracking ID</span></th>
                <th><span className="ar">الخدمة</span><span className="en">Service</span></th>
                <th><span className="ar">الحالة</span><span className="en">Status</span></th>
                <th><span className="ar">التاريخ</span><span className="en">Date</span></th>
                <th><span className="ar">إجراء</span><span className="en">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => {
                const sl = STATUS_LABELS[c.status] || { ar: c.status, en: c.status, color: '#999' };
                const svc = SERVICE_LABELS[c.service_type] || { ar: c.service_type, en: c.service_type };
                return (
                  <tr key={c.id} className={selected === c.id ? 'row--selected' : ''}>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>{c.tracking_id}</td>
                    <td><span className="ar">{svc.ar}</span><span className="en">{svc.en}</span></td>
                    <td>
                      <span className="status-badge" style={{ backgroundColor: sl.color + '20', color: sl.color, border: `1px solid ${sl.color}40` }}>
                        <span className="en">{sl.en}</span>
                      </span>
                    </td>
                    <td style={{ fontSize: '0.85rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <AgeBadge createdAt={c.created_at} />
                        <span style={{ color: '#6b7280' }}>{new Date(c.created_at).toLocaleDateString('en-GB')}</span>
                      </div>
                    </td>
                    <td>
                      <button className="btn btn--sm btn--ghost" onClick={() => openDetail(c.id)}>
                        <span className="ar">عرض</span><span className="en">View</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail Panel */}
      {selected && (
        <div className="review-panel" style={{ marginTop: '1.5rem', background: 'var(--white)', borderRadius: '12px', padding: '1.5rem', border: '1px solid var(--gray-200)' }}>
          {detailLoading ? (
            <div className="admin-loading"><div className="spinner spinner--dark" /></div>
          ) : detail ? (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h2 style={{ margin: 0 }}>
                  <span className="ar">تفاصيل الطلب</span>
                  <span className="en">Case Detail</span>
                </h2>
                <button className="btn btn--sm btn--ghost" onClick={() => { setSelected(null); setDetail(null); }}>X</button>
              </div>

              {/* Applicant Identity */}
              <div className="admin-section" style={{ marginBottom: '1.25rem' }}>
                <h3 className="admin-section__title">
                  <span className="ar">هوية مقدم الطلب</span>
                  <span className="en">Applicant Identity</span>
                </h3>
                {detail.applicant && (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '0.75rem' }}>
                    {[
                      ['Full Name / الاسم الكامل', detail.applicant.full_name],
                      ['Father / اسم الأب', detail.applicant.father_name],
                      ['Mother / اسم الأم', detail.applicant.mother_name],
                      ['DOB / تاريخ الولادة', detail.applicant.date_of_birth],
                      ['Place of Birth / مكان الولادة', detail.applicant.place_of_birth],
                      ['Gender / الجنس', detail.applicant.gender],
                      ['Marital Status / الحالة', detail.applicant.marital_status],
                      ['Registry # / رقم السجل', detail.applicant.registry_number],
                      ['Registry Place / محل السجل', detail.applicant.registry_place],
                      ['Phone / الهاتف', detail.applicant.phone],
                      ['Address / العنوان', detail.applicant.address],
                    ].map(([label, val]) => (
                      <div key={label} style={{ padding: '0.5rem', background: 'var(--gray-50)', borderRadius: '8px' }}>
                        <div style={{ fontSize: '0.75rem', color: 'var(--gray-400)' }}>{label}</div>
                        <div style={{ fontWeight: 500 }}>{val || 'N/A'}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Uploaded Documents - the core of what the mukhtar reviews */}
              <div className="admin-section" style={{ marginBottom: '1.25rem' }}>
                <h3 className="admin-section__title">
                  <span className="ar">المستندات المرفوعة</span>
                  <span className="en">Uploaded Documents</span>
                </h3>
                {detail.documents && detail.documents.length > 0 ? (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '1rem' }}>
                    {detail.documents.map((doc) => {
                      const docLabel = DOC_TYPE_LABELS[doc.document_type] || { ar: doc.document_type, en: doc.document_type };
                      const imgUrl = mukhtarApi.getDocumentImageUrl(selected, doc.id);
                      const isImage = doc.mime_type?.startsWith('image/');
                      return (
                        <div key={doc.id} style={{
                          border: '1px solid var(--gray-200)', borderRadius: '10px', overflow: 'hidden', background: 'var(--white)',
                        }}>
                          {isImage ? (
                            <AuthImage
                              src={imgUrl}
                              alt={docLabel.en}
                              style={{ width: '100%', height: '180px', objectFit: 'cover', cursor: 'pointer', background: '#f3f4f6' }}
                              onClick={() => {
                                const token = localStorage.getItem('access_token');
                                fetch(imgUrl, { headers: { Authorization: `Bearer ${token}` } })
                                  .then(r => r.blob())
                                  .then(blob => {
                                    const url = URL.createObjectURL(blob);
                                    window.open(url, '_blank');
                                  });
                              }}
                            />
                          ) : (
                            <div style={{ width: '100%', height: '180px', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f3f4f6', color: 'var(--gray-400)' }}>
                              PDF
                            </div>
                          )}
                          <div style={{ padding: '0.5rem 0.75rem' }}>
                            <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>
                              <span className="ar">{docLabel.ar}</span>
                              <span className="en">{docLabel.en}</span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p style={{ color: 'var(--gray-400)' }}>No documents uploaded</p>
                )}
              </div>

              {/* System Verification - simplified for mukhtar */}
              <div className="admin-section" style={{ marginBottom: '1.25rem' }}>
                <h3 className="admin-section__title">
                  <span className="ar">التحقق التلقائي من النظام</span>
                  <span className="en">System Verification</span>
                </h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '0.75rem' }}>
                  <div style={{ padding: '0.75rem', borderRadius: '8px', border: '1px solid',
                    ...(detail.verification_summary?.identity_verified
                      ? { background: '#f0fdf4', borderColor: '#bbf7d0', color: '#166534' }
                      : { background: '#fefce8', borderColor: '#fde68a', color: '#854d0e' })
                  }}>
                    <div style={{ fontSize: '0.75rem' }}>
                      <span className="ar">التحقق من الهوية</span>
                      <span className="en">Identity Verification</span>
                    </div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>
                      {detail.verification_summary?.identity_verified ? 'Verified / تم التحقق' : 'Pending / قيد الانتظار'}
                    </div>
                    {detail.verification_summary?.liveness_confidence != null && (
                      <div style={{ fontSize: '0.75rem', marginTop: '0.25rem' }}>
                        Liveness: {detail.verification_summary.liveness_confidence}%
                        {detail.verification_summary.face_similarity != null && ` | Face match: ${detail.verification_summary.face_similarity}%`}
                      </div>
                    )}
                  </div>
                  <div style={{ padding: '0.75rem', background: '#eff6ff', borderRadius: '8px', border: '1px solid #bfdbfe' }}>
                    <div style={{ fontSize: '0.75rem', color: '#1e40af' }}>
                      <span className="ar">تطابق البيانات</span>
                      <span className="en">Data Match</span>
                    </div>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#1e40af' }}>
                      {detail.verification_summary?.data_integrity != null
                        ? `${(detail.verification_summary.data_integrity * 100).toFixed(0)}%`
                        : 'N/A'}
                    </div>
                    {detail.verification_summary?.mismatches?.length > 0 && (
                      <div style={{ fontSize: '0.75rem', color: '#dc2626', marginTop: '0.25rem' }}>
                        Mismatches: {detail.verification_summary.mismatches.join(', ')}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Download form + Actions */}
              <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
                {detail.verification_summary?.has_generated_form && (
                  <button className="btn btn--primary" onClick={() => handleDownloadForm(selected)}>
                    <span className="ar">تحميل استمارة الطلب PDF</span>
                    <span className="en">Download Application Form (PDF)</span>
                  </button>
                )}
              </div>

              {detail.case?.status === 'pending_mukhtar' && (
                <div style={{ display: 'flex', gap: '0.75rem', paddingTop: '1rem', borderTop: '2px solid var(--gray-200)' }}>
                  <button className="btn btn--success" onClick={() => setModal('approve')}>
                    <span className="ar">موافقة وتصديق</span>
                    <span className="en">Approve & Stamp</span>
                  </button>
                  <button className="btn btn--danger" onClick={() => setModal('reject')}>
                    <span className="ar">رفض</span>
                    <span className="en">Reject</span>
                  </button>
                  <button className="btn btn--warning" onClick={() => setModal('need_info')}>
                    <span className="ar">طلب معلومات إضافية</span>
                    <span className="en">Request Info</span>
                  </button>
                  <button className="btn btn--ghost" onClick={openTransferModal} style={{ marginRight: 'auto' }}>
                    <span className="ar">تحويل لمختار آخر</span>
                    <span className="en">Transfer</span>
                  </button>
                </div>
              )}
            </>
          ) : (
            <div className="alert alert--error">Failed to load case</div>
          )}
        </div>
      )}

      {/* Decision Modal */}
      {modal && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '500px' }}>
            <h3 style={{ marginTop: 0 }}>
              {modal === 'approve' && <><span className="ar">تأكيد الموافقة والتصديق</span><span className="en">Confirm Approval & Stamp</span></>}
              {modal === 'reject' && <><span className="ar">تأكيد الرفض</span><span className="en">Confirm Rejection</span></>}
              {modal === 'need_info' && <><span className="ar">طلب معلومات إضافية</span><span className="en">Request Additional Info</span></>}
            </h3>

            {modal === 'approve' && (
              <div style={{ marginBottom: '1rem', padding: '0.75rem 1rem', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8 }}>
                <p style={{ margin: '0 0 0.5rem', fontWeight: 500, fontSize: '0.9rem', color: '#334155' }}>
                  <span className="ar">أصادق كمختار على التالي</span>
                  <span className="en">As mukhtar, I attest to the following</span>
                </p>
                <label style={{ display: 'block', marginBottom: '0.4rem', cursor: 'pointer' }}>
                  <input type="checkbox" checked={residenceVerified} onChange={(e) => setResidenceVerified(e.target.checked)} style={{ marginInlineEnd: '0.5rem' }} />
                  <span className="ar">المواطن يقيم في نطاق اختصاصي</span>
                  <span className="en">The citizen resides in my jurisdiction</span>
                </label>
                <label style={{ display: 'block', marginBottom: '0.4rem', cursor: 'pointer' }}>
                  <input type="checkbox" checked={photoVerified} onChange={(e) => setPhotoVerified(e.target.checked)} style={{ marginInlineEnd: '0.5rem' }} />
                  <span className="ar">الصورة المقدّمة تُطابق المواطن</span>
                  <span className="en">The submitted photo matches the citizen</span>
                </label>
                <label style={{ display: 'block', marginBottom: '0.5rem', cursor: 'pointer' }}>
                  <input type="checkbox" checked={presenceVerified} onChange={(e) => setPresenceVerified(e.target.checked)} style={{ marginInlineEnd: '0.5rem' }} />
                  <span className="ar">المواطن حضر شخصيًا في مكتبي</span>
                  <span className="en">The citizen was physically present in my office</span>
                </label>
                <textarea
                  value={residenceNotes}
                  onChange={(e) => setResidenceNotes(e.target.value)}
                  rows={2}
                  style={{ width: '100%', padding: '0.5rem', borderRadius: 6, border: '1px solid var(--gray-300)', resize: 'vertical', marginTop: '0.25rem' }}
                  placeholder="Residence notes, e.g. 'resident for 12+ years, known to me'"
                />
              </div>
            )}

            <div style={{ marginBottom: '1rem' }}>
              <label style={{ display: 'block', marginBottom: '0.25rem', fontWeight: 500 }}>
                <span className="ar">ملاحظات</span>
                <span className="en">Notes</span>
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid var(--gray-300)', resize: 'vertical' }}
                placeholder="Optional notes..."
              />
            </div>

            {modal === 'reject' && (
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', marginBottom: '0.25rem', fontWeight: 500, color: '#dc2626' }}>
                  <span className="ar">أسباب الرفض (مطلوب)</span>
                  <span className="en">Rejection Reasons (required)</span>
                </label>
                <textarea
                  value={rejectionReasons}
                  onChange={(e) => setRejectionReasons(e.target.value)}
                  rows={3}
                  style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid #fca5a5', resize: 'vertical' }}
                  placeholder="One reason per line..."
                />
              </div>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
              <button className="btn btn--ghost" onClick={() => setModal(null)} disabled={deciding}>
                <span className="ar">إلغاء</span><span className="en">Cancel</span>
              </button>
              <button
                className={`btn ${modal === 'approve' ? 'btn--success' : modal === 'reject' ? 'btn--danger' : 'btn--warning'}`}
                onClick={() => handleDecision(modal)}
                disabled={deciding || (modal === 'approve' && !allAttested)}
                title={
                  modal === 'approve' && !allAttested
                    ? 'All three attestations required'
                    : undefined
                }
              >
                {deciding ? <div className="spinner" /> : (
                  modal === 'approve' ? <><span className="ar">موافقة</span><span className="en">Approve</span></> :
                  modal === 'reject' ? <><span className="ar">رفض</span><span className="en">Reject</span></> :
                  <><span className="ar">إرسال</span><span className="en">Send</span></>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Transfer Modal */}
      {transferModal && (
        <div className="modal-backdrop" onClick={() => setTransferModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '500px' }}>
            <h3 style={{ marginTop: 0 }}>
              <span className="ar">تحويل الطلب لمختار آخر</span>
              <span className="en">Transfer Case to Another Mukhtar</span>
            </h3>

            {availableMukhtars.length === 0 ? (
              <p style={{ color: 'var(--gray-400)' }}>
                <span className="ar">لا يوجد مختارين آخرين في نفس القضاء</span>
                <span className="en">No other mukhtars available in your district</span>
              </p>
            ) : (
              <>
                <div style={{ marginBottom: '1rem' }}>
                  <label style={{ display: 'block', marginBottom: '0.25rem', fontWeight: 500 }}>
                    <span className="ar">اختر المختار</span>
                    <span className="en">Select Mukhtar</span>
                  </label>
                  <select
                    className="form-input"
                    value={transferTarget}
                    onChange={(e) => setTransferTarget(e.target.value)}
                    style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid var(--gray-300)' }}
                  >
                    <option value="">-- Select --</option>
                    {availableMukhtars.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.full_name}{m.municipality ? ` (${m.municipality})` : ''}
                      </option>
                    ))}
                  </select>
                </div>
                <div style={{ marginBottom: '1rem' }}>
                  <label style={{ display: 'block', marginBottom: '0.25rem', fontWeight: 500 }}>
                    <span className="ar">السبب</span>
                    <span className="en">Reason (optional)</span>
                  </label>
                  <textarea
                    value={transferReason}
                    onChange={(e) => setTransferReason(e.target.value)}
                    rows={2}
                    style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid var(--gray-300)', resize: 'vertical' }}
                    placeholder="e.g. This person is in the other mukhtar's zone..."
                  />
                </div>
              </>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
              <button className="btn btn--ghost" onClick={() => setTransferModal(false)} disabled={deciding}>
                <span className="ar">إلغاء</span><span className="en">Cancel</span>
              </button>
              {availableMukhtars.length > 0 && (
                <button className="btn btn--primary" onClick={handleTransfer} disabled={deciding || !transferTarget}>
                  {deciding ? <div className="spinner" /> : (
                    <><span className="ar">تحويل</span><span className="en">Transfer</span></>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}