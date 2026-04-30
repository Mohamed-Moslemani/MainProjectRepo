import { useEffect } from 'react';
import { QUALITY_THRESHOLDS } from '@shared/utils/imageQuality';
import { useFocusTrap } from '@shared/hooks/useFocusTrap';
import L from '@shared/components/L';

/**
 * Pre-flight upload review modal.
 *
 * Shows the citizen the file they just selected, the client-side
 * quality verdict, and asks them to confirm before we hit the
 * gateway. If the file failed any check, the confirm button is
 * disabled but they can still retake (close + pick another file).
 *
 * Designed to be drop-in: the parent owns selection state and renders
 * <UploadPreview /> only when there's a pending selection. On confirm
 * we hand the original File back unchanged so casesApi.uploadDocument
 * can stream it as multipart.
 *
 * Props:
 *   docLabel    : { ar, en }
 *   file        : File
 *   verdict     : { ok, issues, info, previewUrl } from checkImageQuality
 *   onConfirm   : () => void
 *   onCancel    : () => void
 *   onRetake    : () => void   // open file picker again
 */
export default function UploadPreview({
  docLabel,
  file,
  verdict,
  onConfirm,
  onCancel,
  onRetake,
}) {
  // Esc closes the modal — keyboard users shouldn't be trapped.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);

  const trapRef = useFocusTrap(true);

  const isPdf = file.type === 'application/pdf';
  const info = verdict.info || {};

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div ref={trapRef} className="modal modal--lg upload-preview">
        <header className="modal__header">
          <h2>
            <L ar="معاينة قبل الرفع" en="· Preview before upload" />
          </h2>
          <button
            type="button"
            className="modal__close"
            onClick={onCancel}
            aria-label="Close"
          >
            ×
          </button>
        </header>

        <div className="upload-preview__body">
          <div className="upload-preview__doc-label">
            <L>{{ ar: <>{docLabel.ar}</>, en: <>· {docLabel.en}</> }}</L>
          </div>

          <div className="upload-preview__media">
            {isPdf ? (
              <div className="upload-preview__pdf-placeholder">
                <span className="upload-preview__pdf-icon">📄</span>
                <p>
                  <strong>{file.name}</strong>
                </p>
                <p className="upload-preview__hint">
                  <L>{{ ar: <>معاينة PDF غير متاحة. سيتم التحقق من المحتوى بعد الرفع.</>, en: <>PDF preview not available. Content is verified after upload.</> }}</L>
                </p>
              </div>
            ) : verdict.previewUrl ? (
              <img
                src={verdict.previewUrl}
                alt={`Preview of ${docLabel.en}`}
                className="upload-preview__image"
              />
            ) : null}
          </div>

          <dl className="upload-preview__stats">
            <div>
              <dt>
                <L ar="الحجم" en="· Size" />
              </dt>
              <dd>{info.sizeMB} MB</dd>
            </div>
            {info.width ? (
              <div>
                <dt>
                  <L ar="الدقة" en="· Resolution" />
                </dt>
                <dd>
                  {info.width} × {info.height}
                  <small style={{ opacity: 0.6 }}>
                    {' '}
                    (min {QUALITY_THRESHOLDS.MIN_WIDTH}×
                    {QUALITY_THRESHOLDS.MIN_HEIGHT})
                  </small>
                </dd>
              </div>
            ) : null}
            {info.blurScore != null ? (
              <div>
                <dt>
                  <L ar="حدّة الصورة" en="· Sharpness" />
                </dt>
                <dd>
                  {info.blurScore}
                  <small style={{ opacity: 0.6 }}>
                    {' '}
                    (min {QUALITY_THRESHOLDS.BLUR_THRESHOLD})
                  </small>
                </dd>
              </div>
            ) : null}
            {info.glareRatio != null ? (
              <div>
                <dt>
                  <L ar="الانعكاس" en="· Glare" />
                </dt>
                <dd>{info.glareRatio}%</dd>
              </div>
            ) : null}
          </dl>

          {verdict.ok ? (
            <div className="alert alert--success" style={{ marginTop: '1rem' }}>
              <strong>
                <L>{{ ar: <>الصورة جاهزة للرفع</>, en: <>Image looks good — ready to upload</> }}</L>
              </strong>
            </div>
          ) : (
            <div className="alert alert--warning" style={{ marginTop: '1rem' }}>
              <strong>
                <L>{{ ar: <>يُنصح بإعادة الالتقاط:</>, en: <>We recommend retaking this photo:</> }}</L>
              </strong>
              <ul style={{ marginTop: '0.5rem', paddingInlineStart: '1.25rem' }}>
                {verdict.issues.map((issue) => (
                  <li key={issue.code} style={{ marginBottom: '0.4rem' }}>
                    <L>{{ ar: <>{issue.ar}</>, en: <>{issue.en}
                      {issue.hint ? ` (${issue.hint})` : ''}</> }}</L>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <footer className="modal__footer upload-preview__actions">
          <button
            type="button"
            className="btn btn--outline"
            onClick={onCancel}
          >
            <L ar="إلغاء" en="· Cancel" />
          </button>
          <button
            type="button"
            className="btn btn--outline"
            onClick={onRetake}
          >
            <L ar="اختيار صورة أخرى" en="· Choose different photo" />
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={onConfirm}
            disabled={!verdict.ok}
            title={
              verdict.ok
                ? ''
                : 'Fix the quality issues above or retake the photo'
            }
          >
            <L ar="رفع الصورة" en="· Upload" />
          </button>
        </footer>
      </div>
    </div>
  );
}
