import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { casesApi } from '@shared/api/cases';
import { useConfirm } from '@shared/components/ConfirmDialog';
import { localizeTimelineMessage, formatBeirutDateTime } from '@shared/utils/localizeTimeline';
import { useTranslation } from 'react-i18next';
import { referenceApi } from '@shared/api/reference';
import LivenessCheck from '@shared/components/LivenessCheck';
import UploadPreview from '@shared/components/UploadPreview';
import DocumentCapture from '@shared/components/DocumentCapture';
import { isCaptureRequired } from '@shared/constants/captureSpec';
import AuthImage from '@shared/components/AuthImage';
import { SkeletonCard } from '@shared/components/Skeleton';
import { checkImageQuality } from '@shared/utils/imageQuality';
import { useCasePolling } from '@shared/hooks/useCasePolling';
import flagImg from '@shared/assets/Figure_1.png';
import { useAuth } from '@shared/context/useAuth';
import { useToast } from '@shared/context/useToast';
import '@shared/styles/dashboard.css';
import L from '@shared/components/L';
import { useL } from '@shared/hooks/useL';

const LIVENESS_DOC_TYPES = ['selfie', 'liveness_capture'];

// Keys here MUST match the canonical DocumentType enum values used
// by the backend (shared/schemas.py). Mismatched slugs (e.g. the
// old "civil_registry" key vs the actual "civil_registry_extract"
// the API emits) cause the citizen to see the raw slug in retake
// banners — surface fix is just keeping these aligned.
const DOC_LABELS = {
  national_id_front: { ar: 'الهوية - الوجه الأمامي', en: 'National ID (Front)' },
  national_id_back: { ar: 'الهوية - الوجه الخلفي', en: 'National ID (Back)' },
  old_id_front: { ar: 'الهوية القديمة - أمامي', en: 'Old ID (Front)' },
  old_id_back: { ar: 'الهوية القديمة - خلفي', en: 'Old ID (Back)' },
  civil_registry_extract: { ar: 'بيان قيد إفرادي', en: 'Civil Registry Extract' },
  selfie: { ar: 'صورة شخصية', en: 'Selfie Photo' },
  liveness_capture: { ar: 'صورة التحقق من الحياة', en: 'Liveness Capture' },
  passport_data_page: { ar: 'صفحة بيانات الجواز', en: 'Passport Data Page' },
  old_passport_data_page: { ar: 'جواز السفر القديم', en: 'Old Passport Data Page' },
  additional_identity_proof: { ar: 'إثبات إضافي للهوية', en: 'Additional Identity Proof' },
  guardian_docs: { ar: 'وثائق الولي', en: 'Guardian Documents' },
  police_report: { ar: 'محضر شرطة', en: 'Police Report' },
  damaged_passport: { ar: 'الجواز التالف', en: 'Damaged Passport' },
  court_ruling: { ar: 'حكم محكمة', en: 'Court Ruling' },
};

const FIELD_LABELS = {
  first_name: { ar: 'الاسم', en: 'First Name' },
  surname: { ar: 'الشهرة', en: 'Surname' },
  // Legacy: cases created before the first/surname split carry
  // declared_fields["full_name"]. Keep the label so pre-split
  // cases still display correctly on the read-only view.
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
  old_passport_number: { ar: 'رقم الجواز القديم', en: 'Old Passport Number' },
  passport_type: { ar: 'نوع الجواز', en: 'Passport Type' },
  renewal_reason: { ar: 'سبب التجديد', en: 'Renewal Reason' },
  passport_validity_years: { ar: 'مدة صلاحية الجواز', en: 'Passport Validity' },
  reason_for_renewal: { ar: 'سبب التجديد', en: 'Renewal Reason' },
};

const STATUS_MAP = {
  draft: { ar: 'مسودة', en: 'Draft', color: 'gray' },
  submitted: { ar: 'قيد المراجعة', en: 'Submitted', color: 'blue' },
  validated: { ar: 'تم التحقق', en: 'Validated', color: 'blue' },
  risk_evaluated: { ar: 'تم تقييم المخاطر', en: 'Risk Evaluated', color: 'orange' },
  approved: { ar: 'موافق عليه', en: 'Approved', color: 'green' },
  payment_pending: { ar: 'بانتظار الدفع', en: 'Payment Pending', color: 'orange' },
  payment_failed: { ar: 'فشل الدفع', en: 'Payment Failed', color: 'red' },
  biometric_appointment_required: { ar: 'بانتظار حجز موعد البصمات', en: 'Book Biometric Appointment', color: 'orange' },
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
  const confirm = useConfirm();
  const { pick } = useL();

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
  // docType currently being captured via the live-camera modal
  // (national IDs, passports, civil-registry extracts). null means
  // the modal is closed; supporting docs never set this and use the
  // legacy file-picker path instead.
  const [captureFor, setCaptureFor] = useState(null);
  const fileInputsRef = useRef({});

  // Reference dropdowns served by /api/v1/reference. Loaded lazily
  // on mount so the gateway is the source of truth for both the
  // policy engine and the UI.
  const [renewalReasons, setRenewalReasons] = useState([]);
  const [validityOptions, setValidityOptions] = useState([]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      referenceApi.renewalReasons().catch(() => ({ data: { reasons: [] } })),
      referenceApi.passportValidity().catch(() => ({ data: { options: [] } })),
    ]).then(([r, v]) => {
      if (cancelled) return;
      setRenewalReasons(r.data.reasons || []);
      setValidityOptions(v.data.options || []);
    });
    return () => { cancelled = true; };
  }, []);

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
      setError(pick({ ar: 'فشل في تحميل بيانات الطلب', en: 'Failed to load case data' }));
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
      setError(pick({ ar: 'تعذر فحص جودة الصورة', en: 'Could not check image quality' }));
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
    if (!docType) return;
    if (isCaptureRequired(docType)) {
      // Capture-required docs: re-open the camera modal so the user
      // shoots a fresh frame instead of being dropped back into the
      // file picker.
      setCaptureFor(docType);
      return;
    }
    // Re-trigger the hidden <input type="file"> for this doc so the
    // citizen lands straight back in the picker.
    if (fileInputsRef.current[docType]) {
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
      setSuccess(pick({ ar: 'تم رفع الملف بنجاح', en: 'File uploaded successfully' }));
      setTimeout(() => setSuccess(''), 3000);
      if (verdict.previewUrl) URL.revokeObjectURL(verdict.previewUrl);
      setPendingUpload(null);
      await loadCase();
    } catch (err) {
      setError(err.response?.data?.detail || pick({ ar: 'فشل في رفع الملف', en: 'File upload failed' }));
    } finally {
      setUploading('');
    }
  };

  const handleSubmit = async () => {
    // Gate: every personal-info field the policy declared as required
    // must be populated before submit. Without this, citizens could
    // submit with empty declared_fields, the backend's reconciliation
    // would have nothing to compare against the OCR output, and the
    // case would auto-route based purely on doc-quality signals —
    // skipping the entire identity-coherence check.
    const missing = requiredFields.filter((f) => {
      const v = declaredFields[f];
      if (typeof v === 'string') return v.trim() === '';
      return v === undefined || v === null || v === '';
    });
    if (missing.length > 0) {
      const labels = missing
        .map((f) => FIELD_LABELS[f]?.[i18n.resolvedLanguage === 'en' ? 'en' : 'ar'] || f)
        .join('، ');
      setError(pick({
        ar: `يرجى تعبئة الحقول المطلوبة: ${labels}`,
        en: `Please fill the required fields: ${labels}`,
      }));
      return;
    }

    setSubmitting(true);
    setError('');
    try {
      await casesApi.submit(caseId, declaredFields);
      setSuccess(pick({ ar: 'تم تقديم الطلب بنجاح!', en: 'Application submitted successfully!' }));
      await loadCase();
    } catch (err) {
      setError(err.response?.data?.detail || pick({ ar: 'فشل في تقديم الطلب', en: 'Failed to submit case' }));
    } finally {
      setSubmitting(false);
    }
  };

  const isDraft = caseData?.status === 'draft';
  const isNeedInfo = caseData?.status === 'need_info';
  const canEdit = isDraft || isNeedInfo;
  const st = STATUS_MAP[caseData?.status] || { ar: '', en: '', color: 'gray' };

  // Set of document_types the backend flagged for retake on this
  // case. Used to swap a green ✓ for a "Replace" button so the
  // citizen can fix the bad upload — without this they were stuck
  // looking at a checkmark with no way forward.
  const retakeDocTypes = new Set(
    (caseData?.retake_reasons || []).map((r) => r.document_type)
  );

  // All retake / rejection reasons go through the central
  // localizeTimelineMessage util — single source of truth for backend
  // English → Arabic mapping (handles quality strings, classifier
  // verdicts, field-name translation, doc-type slug translation, etc.).
  const localizeReason = localizeTimelineMessage;

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
      setSuccess(pick({ ar: 'تم التحقق من الهوية بنجاح!', en: 'Identity verified successfully!' }));
      setTimeout(() => setSuccess(''), 4000);
    } else {
      setError(pick({
        ar: 'فشل التحقق من الهوية. ' + (result.reasons?.join(', ') || ''),
        en: 'Identity verification failed. ' + (result.reasons?.join(', ') || ''),
      }));
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
      setError(err.response?.data?.detail || pick({ ar: 'فشل في إنشاء جلسة الدفع', en: 'Failed to create payment session' }));
      setPaying(false);
    }
  };

  if (loading) {
    return (
      <div className="dashboard">
        <div className="dashboard-main">
          <SkeletonCard rows={2} />
          <SkeletonCard rows={4} />
          <SkeletonCard rows={3} />
        </div>
      </div>
    );
  }

  if (!caseData) {
    return (
      <div className="dashboard">
        <div className="dashboard-main">
          <div className="empty-state">
            <L>{{ ar: <>الطلب غير موجود</>, en: <>Case not found</> }}</L>
          </div>
        </div>
      </div>
    );
  }

  // Full-screen liveness check mode
  if (showLiveness) {
    return (
      <div className="dashboard">
        <header className="dashboard-header">
          <div className="dashboard-header__brand">
            <img src={flagImg} alt="" className="dashboard-header__flag" />
            <span className="dashboard-header__title">DocFlow <span>Lebanon</span></span>
          </div>
          <div className="dashboard-header__actions">
            <button className="btn btn--ghost" onClick={() => setShowLiveness(false)}>
              <L ar="إلغاء" en="Cancel" />
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
    <div className="dashboard">
      <header className="dashboard-header">
        <div className="dashboard-header__brand">
          <img src={flagImg} alt="" className="dashboard-header__flag" />
          <span className="dashboard-header__title">DocFlow <span>Lebanon</span></span>
        </div>
        <div className="dashboard-header__actions">
          <button className="btn btn--ghost" onClick={() => navigate('/dashboard')}>
            <L ar="العودة" en="Back" />
          </button>
          <button className="btn btn--ghost" onClick={() => { logout(); navigate('/login'); }}>
            <L ar="خروج" en="Sign Out" />
          </button>
        </div>
      </header>

      <main className="dashboard-main">
        {/* Case Header */}
        <div className="case-header">
          <div>
            <h1>
              <L ar="تفاصيل الطلب" en="Application Details" />
            </h1>
            <p className="case-header__tracking">#{caseData.tracking_id}</p>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.5rem' }}>
            <span className={`status-badge status-badge--${st.color} status-badge--lg`}>
              <L>{{ ar: <>{st.ar}</>, en: <>{st.en}</> }}</L>
            </span>
            {/* Tear-down actions:
                - Draft → "Discard" (hard delete, nothing to preserve)
                - Pre-payment statuses → "Withdraw" (audit trail kept) */}
            {isDraft && (
              <button
                className="btn btn--sm btn--ghost"
                style={{ color: '#b91c1c' }}
                onClick={async () => {
                  const ok = await confirm({
                    destructive: true,
                    ar: { title: 'حذف المسودة', message: 'هل أنت متأكد من حذف هذه المسودة؟ لا يمكن التراجع عن هذا الإجراء.', confirm: 'حذف', cancel: 'إلغاء' },
                    en: { title: 'Discard draft', message: 'Are you sure you want to discard this draft? This cannot be undone.', confirm: 'Discard', cancel: 'Cancel' },
                  });
                  if (!ok) return;
                  try {
                    await casesApi.discard(caseId);
                    toast.success(pick({ ar: 'تم حذف المسودة', en: 'Draft discarded' }));
                    navigate('/dashboard');
                  } catch (err) {
                    toast.error(err.response?.data?.detail || pick({ ar: 'فشل في الحذف', en: 'Failed to discard' }));
                  }
                }}
              >
                <L ar="حذف المسودة" en="Discard draft" />
              </button>
            )}
            {!isDraft && !['closed', 'rejected', 'approved', 'payment_pending',
                             'in_production', 'ready_for_pickup'].includes(caseData.status) && (
              <button
                className="btn btn--sm btn--ghost"
                style={{ color: '#b91c1c' }}
                onClick={async () => {
                  const ok = await confirm({
                    destructive: true,
                    ar: {
                      title: 'سحب الطلب',
                      message: 'سيتم إغلاق هذا الطلب. يمكنك تقديم طلب جديد لاحقاً. هل تريد المتابعة؟',
                      confirm: 'سحب الطلب',
                      cancel: 'إلغاء',
                    },
                    en: {
                      title: 'Withdraw application',
                      message: 'This case will be closed. You can apply again later. Continue?',
                      confirm: 'Withdraw',
                      cancel: 'Cancel',
                    },
                  });
                  if (!ok) return;
                  try {
                    await casesApi.withdraw(caseId);
                    toast.success('تم سحب الطلب');
                    navigate('/dashboard');
                  } catch (err) {
                    toast.error(err.response?.data?.detail || 'فشل في السحب');
                  }
                }}
              >
                <L ar="سحب الطلب" en="Withdraw application" />
              </button>
            )}
          </div>
        </div>

        {/* Per-page success/error banners replaced by the global toast
             stack — see ToastProvider in App.jsx. The retake banner
             below is structural (lives on the page until status changes)
             and stays inline. */}

        {/* Retake reasons (quality gate failed — citizen must re-upload) */}
        {isNeedInfo && caseData.retake_reasons?.length > 0 && (
          <div className="alert alert--warning">
            <L>{{ ar: <>صور غير واضحة — يرجى إعادة الرفع:</>, en: <>Some uploads couldn't be read. Please retake and re-submit:</> }}</L>
            <ul style={{ marginTop: '0.5rem', paddingInlineStart: '1.25rem' }}>
              {caseData.retake_reasons.map((finding, i) => {
                const docLabel = DOC_LABELS[finding.document_type];
                return (
                  <li key={i} style={{ marginBottom: '0.5rem' }}>
                    <strong>
                      {docLabel ? (
                        <>
                          <L>{{ ar: <>{docLabel.ar}</>, en: <>· {docLabel.en}</> }}</L>
                        </>
                      ) : (
                        finding.document_type
                      )}
                    </strong>
                    {finding.reasons?.length > 0 && (
                      <ul style={{ marginTop: '0.25rem', paddingInlineStart: '1rem', fontSize: '0.85rem' }}>
                        {finding.reasons.map((r, j) => {
                          const loc = localizeReason(r);
                          return (
                            <li key={j}>
                              <L ar={loc.ar} en={loc.en} />
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
            <p style={{ marginTop: '0.5rem', fontSize: '0.8rem', opacity: 0.85 }}>
              <L ar="نصائح: استخدم إضاءة جيدة، ضع المستند على سطح داكن، تجنب الانعكاسات والظل." en="Tip: bright even lighting, dark flat surface, avoid glare and shadows." />
            </p>
          </div>
        )}

        {/* Rejection reasons — backend stores in English; the
            localizer maps the canonical phrases to Arabic and falls
            back to verbatim English for anything new. */}
        {caseData.rejection_reasons?.length > 0 && (
          <div className="alert alert--error">
            <L ar="أسباب الرفض:" en="Rejection Reasons:" />
            <ul style={{ marginTop: '0.5rem', paddingInlineStart: '1.25rem' }}>
              {caseData.rejection_reasons.map((r, i) => {
                const m = localizeTimelineMessage(r);
                return (
                  <li key={i}>
                    <L ar={m.ar} en={m.en} />
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {/* Notes */}
        {caseData.notes && (
          <div className="alert alert--info">
            <L>{{ ar: <>ملاحظات:</>, en: <>Notes:</> }}</L>
            <p style={{ marginTop: '0.25rem' }}>{caseData.notes}</p>
          </div>
        )}

        {/* Documents Section */}
        <section className="detail-section">
          <h2>
            <L ar="المستندات المطلوبة" en="Required Documents" />
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
                            alt={pick({ ar: `${label.ar} مرفوع`, en: `Uploaded ${label.en}` })}
                            className="doc-card__thumb"
                          />
                        )}
                        <span className="doc-card__filename">{uploaded.original_filename}</span>
                      </>
                    )}
                  </div>
                  <div className="doc-card__action">
                    {uploaded && !retakeDocTypes.has(docType) ? (
                      <span className="doc-card__check">&#10003;</span>
                    ) : canEdit ? (
                      isCaptureRequired(docType) ? (
                        // Identity documents must come from a live
                        // capture so the cross-doc face match has a
                        // clean reference image and the user can't
                        // upload someone else's pre-existing photo.
                        <button
                          type="button"
                          className={`btn btn--sm ${retakeDocTypes.has(docType) ? 'btn--primary' : 'btn--outline'} ${isUploading || checkingFile ? 'btn--loading' : ''}`}
                          onClick={() => setCaptureFor(docType)}
                          disabled={isUploading || checkingFile}
                        >
                          {isUploading ? (
                            <L ar="جارٍ الرفع..." en="Uploading..." />
                          ) : checkingFile ? (
                            <L ar="جاري الفحص..." en="Checking..." />
                          ) : retakeDocTypes.has(docType) ? (
                            <L ar="إعادة الالتقاط" en="Recapture" />
                          ) : (
                            <L ar="التقاط" en="Capture" />
                          )}
                        </button>
                      ) : (
                        <label className={`btn btn--sm ${retakeDocTypes.has(docType) ? 'btn--primary' : 'btn--outline'} ${isUploading || checkingFile ? 'btn--loading' : ''}`}>
                          {isUploading ? (
                            <L ar="جارٍ الرفع..." en="Uploading..." />
                          ) : checkingFile ? (
                            <L ar="جاري الفحص..." en="Checking..." />
                          ) : retakeDocTypes.has(docType) ? (
                            <L ar="إعادة الرفع" en="Replace" />
                          ) : (
                            <L ar="رفع" en="Upload" />
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
                      )
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
                  <span className="doc-card__label">
                    <L ar="التحقق من الهوية (كاميرا)" en="Identity Verification (Camera)" />
                  </span>
                  {livenessCompleted && (
                    <span className="doc-card__filename" style={{ color: '#16a34a' }}>
                      <L ar="تم التحقق بنجاح" en="Verified successfully" />
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
                      <L ar="ابدأ التحقق" en="Start Verification" />
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
              <L ar="البيانات الشخصية" en="Personal Information" />
            </h2>
            <div className="fields-grid">
              {requiredFields.map((field) => {
                const label = FIELD_LABELS[field] || { ar: field, en: field };
                return (
                  <div key={field} className="field-group">
                    <label>
                      <L>{{ ar: <>{label.ar}</>, en: <>{label.en}</> }}</L>
                      {' '}<span aria-hidden style={{ color: '#dc2626' }}>*</span>
                    </label>
                    {field === 'gender' ? (
                      <select
                        required
                        value={declaredFields[field] || ''}
                        onChange={(e) => setDeclaredFields({ ...declaredFields, [field]: e.target.value })}
                      >
                        <option value="">-- اختر --</option>
                        <option value="male">ذكر / Male</option>
                        <option value="female">أنثى / Female</option>
                      </select>
                    ) : field === 'renewal_reason' || field === 'reason_for_renewal' ? (
                      <select
                        required
                        value={declaredFields[field] || ''}
                        onChange={async (e) => {
                          const value = e.target.value;
                          const next = { ...declaredFields, [field]: value };
                          setDeclaredFields(next);
                          // Persist server-side so the next required-
                          // documents fetch picks up the reason-specific
                          // extra docs (police report, court ruling, etc).
                          if (!value) return;
                          try {
                            await casesApi.patchDeclaredFields(caseId, { [field]: value });
                            const reqDocsRes = await casesApi.getRequiredDocuments(caseId);
                            setRequiredDocs(reqDocsRes.data.required_documents || []);
                            const compRes = await casesApi.getCompleteness(caseId);
                            setCompleteness(compRes.data);
                          } catch {
                            setError('فشل في حفظ سبب التجديد');
                          }
                        }}
                      >
                        <option value="">-- اختر / Select --</option>
                        {renewalReasons.map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.ar} / {r.en}
                            {r.extra_docs?.length ? ` — ${r.extra_docs.join(', ')}` : ''}
                          </option>
                        ))}
                      </select>
                    ) : field === 'passport_validity_years' ? (
                      <select
                        required
                        value={declaredFields[field] ?? ''}
                        onChange={async (e) => {
                          const raw = e.target.value;
                          const value = raw === '' ? '' : Number(raw);
                          setDeclaredFields({ ...declaredFields, [field]: value });
                          if (raw === '') return;
                          try {
                            await casesApi.patchDeclaredFields(caseId, { [field]: value });
                          } catch {
                            setError('فشل في حفظ مدة الصلاحية');
                          }
                        }}
                      >
                        <option value="">-- اختر / Select --</option>
                        {validityOptions.map((o) => (
                          <option key={o.years} value={o.years}>
                            {o.years === 1 ? 'سنة واحدة' : `${o.years} سنوات`} / {o.years} {o.years === 1 ? 'year' : 'years'}
                            {' — $'}{(o.fee_cents / 100).toFixed(0)}
                          </option>
                        ))}
                      </select>
                    ) : field === 'marital_status' ? (
                      <select
                        required
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
                        required
                        type="date"
                        value={declaredFields[field] || ''}
                        onChange={(e) => setDeclaredFields({ ...declaredFields, [field]: e.target.value })}
                      />
                    ) : (
                      <input
                        required
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
              <L ar="البيانات المقدمة" en="Submitted Information" />
            </h2>
            <div className="fields-display">
              {Object.entries(caseData.declared_fields).map(([key, val]) => {
                const label = FIELD_LABELS[key] || { ar: key, en: key };
                return (
                  <div key={key} className="field-display-item">
                    <span className="field-display-item__label">
                      <L>{{ ar: <>{label.ar}</>, en: <>{label.en}</> }}</L>
                    </span>
                    <span className="field-display-item__value">{val}</span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Submit Button — gated on docs + declared fields together so
            the citizen can't tap and bounce off a 400 from the backend.
            Mirrors the same checks the backend enforces; treat this
            block as UX, not security. */}
        {canEdit && (() => {
          const docsReady = !!completeness?.complete;
          const missingDeclared = (requiredFields || []).filter((f) => {
            const v = declaredFields[f];
            if (typeof v === 'string') return v.trim() === '';
            return v === undefined || v === null || v === '';
          });
          const declaredReady = missingDeclared.length === 0;
          const ready = docsReady && declaredReady;
          return (
            <div className="submit-section">
              <button
                className={`btn btn--primary btn--lg ${submitting ? 'btn--loading' : ''}`}
                onClick={handleSubmit}
                disabled={submitting || !ready}
              >
                {submitting ? (
                  <L ar="جارٍ التقديم..." en="Submitting..." />
                ) : (
                  <L ar="تقديم الطلب" en="Submit Application" />
                )}
              </button>
              {!docsReady && completeness?.missing_documents?.length > 0 && (
                <p className="submit-hint">
                  <L ar="يرجى رفع جميع المستندات المطلوبة قبل التقديم" en="Please upload all required documents before submitting" />
                </p>
              )}
              {docsReady && !declaredReady && (
                <p className="submit-hint">
                  <L
                    ar={`يرجى تعبئة جميع البيانات الشخصية: ${missingDeclared.map((f) => FIELD_LABELS[f]?.ar || f).join('، ')}`}
                    en={`Please fill all personal info fields: ${missingDeclared.map((f) => FIELD_LABELS[f]?.en || f).join(', ')}`}
                  />
                </p>
              )}
            </div>
          );
        })()}

        {/* Biometric appointment CTA — passport flow gates here. */}
        {caseData?.status === 'biometric_appointment_required' && (
          <section className="detail-section">
            <h2>
              <L ar="حجز موعد البصمات" en="Book your biometric appointment" />
            </h2>
            <p>
              <L ar="مطلوب زيارة أحد مراكز الأمن العام لأخذ البصمات والتوقيع." en="A visit to a GDGS centre is required for fingerprint + signature capture." />
            </p>
            <button
              className="btn btn--primary btn--lg"
              onClick={() => navigate(`/case/${caseId}/appointment`)}
            >
              <L ar="احجز موعدك" en="· Book a slot" />
            </button>
          </section>
        )}

        {/* Payment Section */}
        {(caseData?.status === 'payment_pending' || caseData?.status === 'payment_failed') && (
          <section className="detail-section">
            <h2>
              <L ar="الدفع" en="Payment" />
            </h2>
            <div className="payment-section">
              <p>
                <L ar="طلبك تمت الموافقة عليه. يرجى إتمام الدفع للمتابعة." en="Your application has been approved. Please complete payment to proceed." />
              </p>
              <button
                className={`btn btn--primary btn--lg ${paying ? 'btn--loading' : ''}`}
                onClick={handlePayment}
                disabled={paying}
              >
                {paying ? (
                  <L ar="جارٍ التحويل..." en="Redirecting..." />
                ) : (
                  <>
                    <L ar="ادفع الآن" en="Pay Now" />
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

      {captureFor && (
        <DocumentCapture
          docType={captureFor}
          onCancel={() => setCaptureFor(null)}
          onCapture={(file) => {
            // Camera modal closes immediately; the file flows into
            // the same quality-check + preview-confirm pipeline an
            // upload would, so blurry/skewed captures still get
            // bounced back before they hit the gateway.
            const docType = captureFor;
            setCaptureFor(null);
            handleFileSelected(docType, file);
          }}
        />
      )}
    </div>
  );
}

function TrackingTimeline({ caseId }) {
  const [tracking, setTracking] = useState(null);
  const { i18n } = useTranslation();

  useEffect(() => {
    casesApi.getTracking(caseId).then(({ data }) => setTracking(data)).catch(() => {});
  }, [caseId]);

  if (!tracking || !tracking.events?.length) return null;

  // Backend stores status_history.message and next_action in
  // English. Map to the active locale, format timestamps in
  // Asia/Beirut so the citizen sees their own clock regardless
  // of where the server lives.
  const dateLocale = i18n.resolvedLanguage === 'en' ? 'en-GB' : 'ar-LB';
  const next = tracking.next_action ? localizeTimelineMessage(tracking.next_action) : null;

  return (
    <section className="detail-section">
      <h2>
        <L ar="مسار الطلب" en="Application Timeline" />
      </h2>
      <div className="timeline">
        {tracking.events.map((ev, i) => {
          const m = localizeTimelineMessage(ev.message);
          return (
            <div key={i} className={`timeline__item ${i === 0 ? 'timeline__item--active' : ''}`}>
              <div className="timeline__dot" />
              <div className="timeline__content">
                <p className="timeline__message">
                  <L ar={m.ar} en={m.en} />
                </p>
                <span className="timeline__date">
                  {formatBeirutDateTime(ev.timestamp, dateLocale)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      {next && (
        <div className="next-action">
          <L ar="الخطوة التالية:" en="Next Step:" />{' '}
          <strong>
            <L ar={next.ar} en={next.en} />
          </strong>
        </div>
      )}
    </section>
  );
}
