import { useEffect } from 'react';
import { QUALITY_THRESHOLDS } from '../utils/imageQuality';

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

  const isPdf = file.type === 'application/pdf';
  const info = verdict.info || {};

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal modal--lg upload-preview">
        <header className="modal__header">
          <h2>
            <span className="ar">معاينة قبل الرفع</span>
            <span className="en"> · Preview before upload</span>
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
            <span className="ar">{docLabel.ar}</span>
            <span className="en"> · {docLabel.en}</span>
          </div>

          <div className="upload-preview__media">
            {isPdf ? (
              <div className="upload-preview__pdf-placeholder">
                <span className="upload-preview__pdf-icon">📄</span>
                <p>
                  <strong>{file.name}</strong>
                </p>
                <p className="upload-preview__hint">
                  <span className="ar">
                    معاينة PDF غير متاحة. سيتم التحقق من المحتوى بعد الرفع.
                  </span>
                  <span className="en" style={{ display: 'block' }}>
                    PDF preview not available. Content is verified after upload.
                  </span>
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
                <span className="ar">الحجم</span>
                <span className="en"> · Size</span>
              </dt>
              <dd>{info.sizeMB} MB</dd>
            </div>
            {info.width ? (
              <div>
                <dt>
                  <span className="ar">الدقة</span>
                  <span className="en"> · Resolution</span>
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
                  <span className="ar">حدّة الصورة</span>
                  <span className="en"> · Sharpness</span>
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
                  <span className="ar">الانعكاس</span>
                  <span className="en"> · Glare</span>
                </dt>
                <dd>{info.glareRatio}%</dd>
              </div>
            ) : null}
          </dl>

          {verdict.ok ? (
            <div className="alert alert--success" style={{ marginTop: '1rem' }}>
              <strong>
                <span className="ar">الصورة جاهزة للرفع</span>
                <span className="en" style={{ display: 'block', fontSize: '0.75rem' }}>
                  Image looks good — ready to upload
                </span>
              </strong>
            </div>
          ) : (
            <div className="alert alert--warning" style={{ marginTop: '1rem' }}>
              <strong>
                <span className="ar">يُنصح بإعادة الالتقاط:</span>
                <span className="en" style={{ display: 'block', fontSize: '0.75rem' }}>
                  We recommend retaking this photo:
                </span>
              </strong>
              <ul style={{ marginTop: '0.5rem', paddingInlineStart: '1.25rem' }}>
                {verdict.issues.map((issue) => (
                  <li key={issue.code} style={{ marginBottom: '0.4rem' }}>
                    <span className="ar">{issue.ar}</span>
                    <span className="en" style={{ display: 'block', fontSize: '0.85rem', opacity: 0.85 }}>
                      {issue.en}
                      {issue.hint ? ` (${issue.hint})` : ''}
                    </span>
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
            <span className="ar">إلغاء</span>
            <span className="en"> · Cancel</span>
          </button>
          <button
            type="button"
            className="btn btn--outline"
            onClick={onRetake}
          >
            <span className="ar">اختيار صورة أخرى</span>
            <span className="en"> · Choose different photo</span>
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
            <span className="ar">رفع الصورة</span>
            <span className="en"> · Upload</span>
          </button>
        </footer>
      </div>
    </div>
  );
}
