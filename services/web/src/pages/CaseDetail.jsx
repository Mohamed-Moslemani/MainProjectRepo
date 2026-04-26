import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { casesApi } from '../api/cases';
import LivenessCheck from '../components/LivenessCheck';
import UploadPreview from '../components/UploadPreview';
import AuthImage from '../components/AuthImage';
import { checkImageQuality } from '../utils/imageQuality';
import { useCasePolling } from '../hooks/useCasePolling';
import flagImg from '../assets/Figure_1.png';
import { useAuth } from '../context/useAuth';
import { useToast } from '../context/useToast';
import '../styles/dashboard.css';

const LIVENESS_DOC_TYPES = ['selfie', 'liveness_capture'];

const DOC_LABELS = {
  national_id_front: { ar: 'الهوية - الوجه الأمامي', en: 'National ID (Front)' },
  national_id_back: { ar: 'الهوية - الوجه الخلفي', en: 'National ID (Back)' },
  old_id_front: { ar: 'الهوية القديمة - أمامي', en: 'Old ID (Front)' },
  old_id_back: { ar: 'الهوية القديمة - خلفي', en: 'Old ID (Back)' },
  civil_registry: { ar: 'سجل القيد العائلي', en: 'Civil Registry Extract' },
  selfie: { ar: 'صورة شخصية', en: 'Selfie Photo' },
  liveness: { ar: 'صورة التحقق من الحياة', en: 'Liveness Photo' },
  old_passport: { ar: 'جواز السفر القديم', en: 'Old Passport' },
  additional_proof: { ar: 'إثبات إضافي', en: 'Additional Proof' },
  guardian_id: { ar: 'هوية الولي', en: 'Guardian ID' },
  guardian_consent: { ar: 'موافقة الولي', en: 'Guardian Consent' },
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
  marital_status: { ar: 'الحالة الاجتماعية', en: 'Marital Status' },
  passport_number: { ar: 'رقم جواز السفر', en: 'Passport Number' },
  nationality: { ar: 'الجنسية', en: 'Nationality' },
};

const STATUS_MAP = {
  draft: { ar: 'مسودة', en: 'Draft', color: 'gray' },
  submitted: { ar: 'قيد المراجعة', en: 'Submitted', color: 'blue' },
  validated: { ar: 'تم التحقق', en: 'Validated', color: 'blue' },
  risk_evaluated: { ar: 'تم تقييم المخاطر', en: 'Risk Evaluated', color: 'orange' },
  approved: { ar: 'موافق عليه', en: 'Approved', color: 'green' },
  payment_pending: { ar: 'بانتظار الدفع', en: 'Payment Pending', color: 'orange' },
  rejected: { ar: 'مرفوض', en: 'Rejected', color: 'red' },
  need_info: { ar: 'بحاجة لمعلومات', en: 'Needs Info', color: 'orange' },
  in_production: { ar: 'قيد الإنتاج', en: 'In Production', color: 'blue' },
  ready_for_pickup: { ar: 'جاهز للاستلام', en: 'Ready for Pickup', color: 'green' },
  closed: { ar: 'مغلق', en: 'Closed', color: 'gray' },
};

export default function CaseDetail() {
  const { caseId } = useParams();
  const navigate = useNavigate();
  const { logout } = useAuth();
  const toast = useToast();

  const [caseData, setCaseData] = useState(null);
  const [requiredDocs, setRequiredDocs] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [completeness, setCompleteness] = useState(null);
  const [declaredFields, setDeclaredFields] = useState({});
  const [requiredFields, setRequiredFields] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [showLiveness, setShowLiveness] = useState(false);
  const [paying, setPaying] = useState(false);
  // Errors and successes go through the app-wide toast stack now;
  // these aliases keep the existing call sites readable while routing
  // through useToast under the hood.
  const setError = (msg) => msg && toast.error(msg);
  const setSuccess = (msg) => msg && toast.success(msg);

  // Pre-flight upload state. When a file is picked we run the client-
  // side quality checker, stash the verdict + the file, and render
  // <UploadPreview /> so the citizen can review before we hit the
  // gateway. Confirm flushes through to handleUpload below.
  const [pendingUpload, setPendingUpload] = useState(null);
  const [checkingFile, setCheckingFile] = useState(false);
  const fileInputsRef = useRef({});

  const loadCase = useCallback(async () => {
    try {
      const [caseRes, docsRes, reqDocsRes, compRes] = await Promise.all([
        casesApi.get(caseId),
        casesApi.getDocuments(caseId),
        casesApi.getRequiredDocuments(caseId),
        casesApi.getCompleteness(caseId),
      ]);
      setCaseData(caseRes.data);
      setDocuments(docsRes.data);
      setRequiredDocs(reqDocsRes.data.required_documents || []);
      setRequiredFields(reqDocsRes.data.declared_fields || []);
      setCompleteness(compRes.data);
      setDeclaredFields(caseRes.data.declared_fields || {});
    } catch {
      setError('فشل في تحميل بيانات الطلب');
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    loadCase();
  }, [loadCase]);

  // Live status updates while the case is moving through the pipeline.
  // Hook is a no-op for terminal / citizen-edit states.
  useCasePolling(caseData?.status, loadCase);

  // Run the client-side quality check, then open the preview modal so
  // the citizen can review before we actually hit the gateway. We
  // *don't* upload here — confirmUpload below does that once the user
  // OKs the preview.
  const handleFileSelected = async (docType, file) => {
    if (!file) return;
    setError('');
    setCheckingFile(true);
    try {
      const verdict = await checkImageQuality(file);
      setPendingUpload({ docType, file, verdict });
    } catch {
      setError('تعذر فحص جودة الصورة');
    } finally {
      setCheckingFile(false);
    }
  };

  const cancelPendingUpload = () => {
    if (pendingUpload?.verdict?.previewUrl) {
      URL.revokeObjectURL(pendingUpload.verdict.previewUrl);
    }
    setPendingUpload(null);
  };

  const retakePendingUpload = () => {
    const docType = pendingUpload?.docType;
    cancelPendingUpload();
    // Re-trigger the hidden <input type="file"> for this doc so the
    // citizen lands straight back in the picker.
    if (docType && fileInputsRef.current[docType]) {
      fileInputsRef.current[docType].value = '';
      fileInputsRef.current[docType].click();
    }
  };

  const confirmPendingUpload = async () => {
    if (!pendingUpload) return;
    const { docType, file, verdict } = pendingUpload;
    setUploading(docType);
    setError('');
    try {
      await casesApi.uploadDocument(caseId, file, docType);
      setSuccess('تم رفع الملف بنجاح');
      setTimeout(() => setSuccess(''), 3000);
      if (verdict.previewUrl) URL.revokeObjectURL(verdict.previewUrl);
      setPendingUpload(null);
      await loadCase();
    } catch (err) {
      setError(err.response?.data?.detail || 'فشل في رفع الملف');
    } finally {
      setUploading('');
    }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setError('');
    try {
      await casesApi.submit(caseId, declaredFields);
      setSuccess('تم تقديم الطلب بنجاح!');
      await loadCase();
    } catch (err) {
      setError(err.response?.data?.detail || 'فشل في تقديم الطلب');
    } finally {
      setSubmitting(false);
    }
  };

  const isDraft = caseData?.status === 'draft';
  const isNeedInfo = caseData?.status === 'need_info';
  const canEdit = isDraft || isNeedInfo;
  const st = STATUS_MAP[caseData?.status] || { ar: '', en: '', color: 'gray' };

  // Liveness: check if already completed via session
  const livenessCompleted = !!(caseData?.liveness_result?.liveness_passed);
  const requiresLiveness = requiredDocs.some((d) => LIVENESS_DOC_TYPES.includes(d));
  // Filter out selfie/liveness_capture from doc grid — handled by liveness component
  const uploadableDocs = requiresLiveness
    ? requiredDocs.filter((d) => !LIVENESS_DOC_TYPES.includes(d))
    : requiredDocs;

  const handleLivenessComplete = async (result) => {
    setShowLiveness(false);
    if (result.liveness_passed) {
      setSuccess('تم التحقق من الهوية بنجاح! / Identity verified successfully!');
      setTimeout(() => setSuccess(''), 4000);
    } else {
      setError('فشل التحقق من الهوية / Identity verification failed. ' + (result.reasons?.join(', ') || ''));
    }
    await loadCase();
  };

  const handleLivenessError = (msg) => {
    setShowLiveness(false);
    setError(msg);
  };

  const handlePayment = async () => {
    setPaying(true);
    setError('');
    try {
      const { data } = await casesApi.createPayment(caseId);
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'فشل في إنشاء جلسة الدفع / Payment session failed');
      setPaying(false);
    }
  };

  if (loading) {
    return (
      <div className="dashboard" dir="rtl">
        <div className="dashboard-main"><div className="loading-spinner" /></div>
      </div>
    );
  }

  if (!caseData) {
    return (
      <div className="dashboard" dir="rtl">
        <div className="dashboard-main">
          <div className="empty-state">
            <p className="ar">الطلب غير موجود</p>
            <p className="en">Case not found</p>
          </div>
        </div>
      </div>
    );
  }

  // Full-screen liveness check mode
  if (showLiveness) {
    return (
      <div className="dashboard" dir="rtl">
        <header className="dashboard-header">
          <div className="dashboard-header__brand">
            <img src={flagImg} alt="" className="dashboard-header__flag" />
            <span className="dashboard-header__title">DocFlow <span>Lebanon</span></span>
          </div>
          <div className="dashboard-header__actions">
            <button className="btn btn--ghost" onClick={() => setShowLiveness(false)}>
              <span className="ar">إلغاء</span>
              <span className="en">Cancel</span>
            </button>
          </div>
        </header>
        <main className="dashboard-main">
          <LivenessCheck
            caseId={caseId}
            onComplete={handleLivenessComplete}
            onError={handleLivenessError}
            onCancel={() => setShowLiveness(false)}
          />
        </main>
      </div>
    );
  }

  return (
    <div className="dashboard" dir="rtl">
      <header className="dashboard-header">
        <div className="dashboard-header__brand">
          <img src={flagImg} alt="" className="dashboard-header__flag" />
          <span className="dashboard-header__title">DocFlow <span>Lebanon</span></span>
        </div>
        <div className="dashboard-header__actions">
          <button className="btn btn--ghost" onClick={() => navigate('/dashboard')}>
            <span className="ar">العودة</span>
            <span className="en">Back</span>
          </button>
          <button className="btn btn--ghost" onClick={() => { logout(); navigate('/login'); }}>
            <span className="ar">خروج</span>
            <span className="en">Sign Out</span>
          </button>
        </div>
      </header>

      <main className="dashboard-main">
        {/* Case Header */}
        <div className="case-header">
          <div>
            <h1>
              <span className="ar">تفاصيل الطلب</span>
              <span className="en">Application Details</span>
            </h1>
            <p className="case-header__tracking">#{caseData.tracking_id}</p>
          </div>
          <span className={`status-badge status-badge--${st.color} status-badge--lg`}>
            <span className="ar">{st.ar}</span>
            <span className="en">{st.en}</span>
          </span>
        </div>

        {/* Per-page success/error banners replaced by the global toast
             stack — see ToastProvider in App.jsx. The retake banner
             below is structural (lives on the page until status changes)
             and stays inline. */}

        {/* Retake reasons (quality gate failed — citizen must re-upload) */}
        {isNeedInfo && caseData.retake_reasons?.length > 0 && (
          <div className="alert alert--warning">
            <strong className="ar">صور غير واضحة — يرجى إعادة الرفع:</strong>
            <strong className="en" style={{ display: 'block', fontSize: '0.75rem' }}>
              Some uploads couldn't be read. Please retake and re-submit:
            </strong>
            <ul style={{ marginTop: '0.5rem', paddingRight: '1.25rem' }}>
              {caseData.retake_reasons.map((finding, i) => {
                const docLabel = DOC_LABELS[finding.document_type];
                return (
                  <li key={i} style={{ marginBottom: '0.5rem' }}>
                    <strong>
                      {docLabel ? (
                        <>
                          <span className="ar">{docLabel.ar}</span>
                          <span className="en"> · {docLabel.en}</span>
                        </>
                      ) : (
                        finding.document_type
                      )}
                    </strong>
                    {finding.reasons?.length > 0 && (
                      <ul style={{ marginTop: '0.25rem', paddingRight: '1rem', fontSize: '0.85rem' }}>
                        {finding.reasons.map((r, j) => <li key={j}>{r}</li>)}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
            <p style={{ marginTop: '0.5rem', fontSize: '0.8rem', opacity: 0.85 }}>
              <span className="ar">
                نصائح: استخدم إضاءة جيدة، ضع المستند على سطح داكن، تجنب الانعكاسات والظل.
              </span>
              <span className="en" style={{ display: 'block' }}>
                Tip: bright even lighting, dark flat surface, avoid glare and shadows.
              </span>
            </p>
          </div>
        )}

        {/* Rejection reasons */}
        {caseData.rejection_reasons?.length > 0 && (
          <div className="alert alert--error">
            <strong className="ar">أسباب الرفض:</strong>
            <strong className="en" style={{ display: 'block', fontSize: '0.75rem' }}>Rejection Reasons:</strong>
            <ul style={{ marginTop: '0.5rem', paddingRight: '1.25rem' }}>
              {caseData.rejection_reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </div>
        )}

        {/* Notes */}
        {caseData.notes && (
          <div className="alert alert--info">
            <strong className="ar">ملاحظات:</strong>
            <strong className="en" style={{ display: 'block', fontSize: '0.75rem' }}>Notes:</strong>
            <p style={{ marginTop: '0.25rem' }}>{caseData.notes}</p>
          </div>
        )}

        {/* Documents Section */}
        <section className="detail-section">
          <h2>
            <span className="ar">المستندات المطلوبة</span>
            <span className="en">Required Documents</span>
          </h2>
          {completeness && (
            <div className="completeness-bar">
              <div
                className="completeness-bar__fill"
                style={{ width: `${(completeness.uploaded_count / Math.max(completeness.required_count, 1)) * 100}%` }}
              />
              <span className="completeness-bar__text">
                {completeness.uploaded_count} / {completeness.required_count}
              </span>
            </div>
          )}
          <div className="doc-grid">
            {uploadableDocs.map((docType) => {
              const uploaded = documents.find((d) => d.document_type === docType);
              const label = DOC_LABELS[docType] || { ar: docType, en: docType };
              const isUploading = uploading === docType;

              return (
                <div key={docType} className={`doc-card ${uploaded ? 'doc-card--uploaded' : ''}`}>
                  <div className="doc-card__info">
                    <span className="doc-card__label ar">{label.ar}</span>
                    <span className="doc-card__label en">{label.en}</span>
                    {uploaded && (
                      <>
                        {uploaded.mime_type?.startsWith('image/') && (
                          <AuthImage
                            src={casesApi.getDocumentImageUrl(caseId, uploaded.id)}
                            alt={`Uploaded ${label.en}`}
                            className="doc-card__thumb"
                          />
                        )}
                        <span className="doc-card__filename">{uploaded.original_filename}</span>
                      </>
                    )}
                  </div>
                  <div className="doc-card__action">
                    {uploaded ? (
                      <span className="doc-card__check">&#10003;</span>
                    ) : canEdit ? (
                      <label className={`btn btn--sm btn--outline ${isUploading || checkingFile ? 'btn--loading' : ''}`}>
                        {isUploading ? (
                          <span className="ar">جارٍ الرفع...</span>
                        ) : checkingFile ? (
                          <span className="ar">جاري الفحص...</span>
                        ) : (
                          <>
                            <span className="ar">رفع</span>
                            <span className="en">Upload</span>
                          </>
                        )}
                        <input
                          type="file"
                          accept="image/jpeg,image/png,image/webp,application/pdf"
                          style={{ display: 'none' }}
                          ref={(el) => { fileInputsRef.current[docType] = el; }}
                          onChange={(e) => {
                            if (e.target.files[0]) handleFileSelected(docType, e.target.files[0]);
                            // Reset so picking the same filename twice still triggers onChange
                            e.target.value = '';
                          }}
                          disabled={isUploading || checkingFile}
                        />
                      </label>
                    ) : (
                      <span className="doc-card__missing">&#10007;</span>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Liveness verification card */}
            {requiresLiveness && (
              <div className={`doc-card ${livenessCompleted ? 'doc-card--uploaded' : ''}`}>
                <div className="doc-card__info">
                  <span className="doc-card__label ar">التحقق من الهوية (كاميرا)</span>
                  <span className="doc-card__label en">Identity Verification (Camera)</span>
                  {livenessCompleted && (
                    <span className="doc-card__filename" style={{ color: '#16a34a' }}>
                      <span className="ar">تم التحقق بنجاح</span>
                      <span className="en">Verified successfully</span>
                    </span>
                  )}
                </div>
                <div className="doc-card__action">
                  {livenessCompleted ? (
                    <span className="doc-card__check">&#10003;</span>
                  ) : canEdit ? (
                    <button
                      className="btn btn--sm btn--primary"
                      onClick={() => setShowLiveness(true)}
                    >
                      <span className="ar">ابدأ التحقق</span>
                      <span className="en">Start Verification</span>
                    </button>
                  ) : (
                    <span className="doc-card__missing">&#10007;</span>
                  )}
                </div>
              </div>
            )}
          </div>
        </section>

        {/* Declared Fields */}
        {canEdit && requiredFields.length > 0 && (
          <section className="detail-section">
            <h2>
              <span className="ar">البيانات الشخصية</span>
              <span className="en">Personal Information</span>
            </h2>
            <div className="fields-grid">
              {requiredFields.map((field) => {
                const label = FIELD_LABELS[field] || { ar: field, en: field };
                return (
                  <div key={field} className="field-group">
                    <label>
                      <span className="ar">{label.ar}</span>
                      <span className="en">{label.en}</span>
                    </label>
                    {field === 'gender' ? (
                      <select
                        value={declaredFields[field] || ''}
                        onChange={(e) => setDeclaredFields({ ...declaredFields, [field]: e.target.value })}
                      >
                        <option value="">-- اختر --</option>
                        <option value="male">ذكر / Male</option>
                        <option value="female">أنثى / Female</option>
                      </select>
                    ) : field === 'marital_status' ? (
                      <select
                        value={declaredFields[field] || ''}
                        onChange={(e) => setDeclaredFields({ ...declaredFields, [field]: e.target.value })}
                      >
                        <option value="">-- اختر --</option>
                        <option value="single">أعزب / Single</option>
                        <option value="married">متزوج / Married</option>
                        <option value="divorced">مطلق / Divorced</option>
                        <option value="widowed">أرمل / Widowed</option>
                      </select>
                    ) : field === 'date_of_birth' ? (
                      <input
                        type="date"
                        value={declaredFields[field] || ''}
                        onChange={(e) => setDeclaredFields({ ...declaredFields, [field]: e.target.value })}
                      />
                    ) : (
                      <input
                        type="text"
                        value={declaredFields[field] || ''}
                        onChange={(e) => setDeclaredFields({ ...declaredFields, [field]: e.target.value })}
                        placeholder={label.en}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Non-editable declared fields display */}
        {!canEdit && Object.keys(caseData.declared_fields || {}).length > 0 && (
          <section className="detail-section">
            <h2>
              <span className="ar">البيانات المقدمة</span>
              <span className="en">Submitted Information</span>
            </h2>
            <div className="fields-display">
              {Object.entries(caseData.declared_fields).map(([key, val]) => {
                const label = FIELD_LABELS[key] || { ar: key, en: key };
                return (
                  <div key={key} className="field-display-item">
                    <span className="field-display-item__label">
                      <span className="ar">{label.ar}</span>
                      <span className="en">{label.en}</span>
                    </span>
                    <span className="field-display-item__value">{val}</span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Submit Button */}
        {canEdit && (
          <div className="submit-section">
            <button
              className={`btn btn--primary btn--lg ${submitting ? 'btn--loading' : ''}`}
              onClick={handleSubmit}
              disabled={submitting || !completeness?.complete}
            >
              {submitting ? (
                <span className="ar">جارٍ التقديم...</span>
              ) : (
                <>
                  <span className="ar">تقديم الطلب</span>
                  <span className="en">Submit Application</span>
                </>
              )}
            </button>
            {!completeness?.complete && completeness?.missing_documents?.length > 0 && (
              <p className="submit-hint">
                <span className="ar">يرجى رفع جميع المستندات المطلوبة قبل التقديم</span>
                <span className="en">Please upload all required documents before submitting</span>
              </p>
            )}
          </div>
        )}

        {/* Payment Section */}
        {caseData?.status === 'payment_pending' && (
          <section className="detail-section">
            <h2>
              <span className="ar">الدفع</span>
              <span className="en">Payment</span>
            </h2>
            <div className="payment-section">
              <p>
                <span className="ar">طلبك تمت الموافقة عليه. يرجى إتمام الدفع للمتابعة.</span>
                <span className="en">Your application has been approved. Please complete payment to proceed.</span>
              </p>
              <button
                className={`btn btn--primary btn--lg ${paying ? 'btn--loading' : ''}`}
                onClick={handlePayment}
                disabled={paying}
              >
                {paying ? (
                  <span className="ar">جارٍ التحويل...</span>
                ) : (
                  <>
                    <span className="ar">ادفع الآن</span>
                    <span className="en">Pay Now</span>
                  </>
                )}
              </button>
            </div>
          </section>
        )}

        {/* Tracking Timeline */}
        {!isDraft && <TrackingTimeline caseId={caseId} />}
      </main>

      {pendingUpload && (
        <UploadPreview
          docLabel={DOC_LABELS[pendingUpload.docType] || { ar: pendingUpload.docType, en: pendingUpload.docType }}
          file={pendingUpload.file}
          verdict={pendingUpload.verdict}
          onConfirm={confirmPendingUpload}
          onCancel={cancelPendingUpload}
          onRetake={retakePendingUpload}
        />
      )}
    </div>
  );
}

function TrackingTimeline({ caseId }) {
  const [tracking, setTracking] = useState(null);

  useEffect(() => {
    casesApi.getTracking(caseId).then(({ data }) => setTracking(data)).catch(() => {});
  }, [caseId]);

  if (!tracking || !tracking.events?.length) return null;

  return (
    <section className="detail-section">
      <h2>
        <span className="ar">مسار الطلب</span>
        <span className="en">Application Timeline</span>
      </h2>
      <div className="timeline">
        {tracking.events.map((ev, i) => (
          <div key={i} className={`timeline__item ${i === 0 ? 'timeline__item--active' : ''}`}>
            <div className="timeline__dot" />
            <div className="timeline__content">
              <p className="timeline__message">{ev.message}</p>
              <span className="timeline__date">
                {new Date(ev.timestamp).toLocaleString('ar-LB')}
              </span>
            </div>
          </div>
        ))}
      </div>
      {tracking.next_action && (
        <div className="next-action">
          <span className="ar">الخطوة التالية: </span>
          <span className="en">Next Step: </span>
          <strong>{tracking.next_action}</strong>
        </div>
      )}
    </section>
  );
}
