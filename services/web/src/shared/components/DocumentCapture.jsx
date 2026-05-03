import { useEffect, useRef, useState } from 'react';

import { CAPTURE_SPECS } from '@shared/constants/captureSpec';
import L from '@shared/components/L';
import '@shared/styles/capture.css';

// Document-capture modal. Opens the device's rear camera, draws a
// paper-shaped guide overlay, and on shutter crops the live frame
// to the guide rectangle before handing the resulting JPEG Blob
// back to the caller. Replaces the file-picker upload path for
// identity documents (IDs, passports, civil registry extracts).
//
// The guide-crop alone is a large UX win: the resulting image is
// cleanly framed with minimal background, which makes Google Cloud
// Vision OCR + downstream face detection significantly more reliable
// than uncontrolled gallery uploads. A future commit can layer in
// OpenCV.js perspective warp on top — the integration point is the
// `cropToGuide` function below.
//
// Hard-block by product requirement: if `getUserMedia` is unavailable
// or denied, the modal renders an explainer telling the user the
// service requires a phone camera. We do NOT fall back to a file
// picker — that defeats the anti-fraud rationale for forcing capture.

const FRAME_INSET_RATIO = 0.86;  // guide rectangle takes 86% of the
                                 // shorter viewport dimension; rest is
                                 // dark mask so the user knows where to
                                 // align the doc.

// Output image cap so we don't ship huge files over mobile data. GCV
// OCR works fine at 2000px on the long edge; bigger just costs upload
// time without improving extraction.
const OUTPUT_LONG_EDGE_PX = 2000;

export default function DocumentCapture({ docType, onCapture, onCancel }) {
  const spec = CAPTURE_SPECS[docType];

  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const overlayRef = useRef(null);
  const [phase, setPhase] = useState('requesting');  // requesting | streaming | denied | unavailable | confirming
  const [previewUrl, setPreviewUrl] = useState(null);
  const previewBlobRef = useRef(null);
  const [previewing, setPreviewing] = useState(false);

  // ── Camera lifecycle ──────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setPhase('unavailable');
        return;
      }

      try {
        // Prefer the rear ("environment") camera and request a high
        // enough resolution that the cropped guide region still has
        // ~1500px on its long edge after we cut away the mask.
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: 'environment' },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
        setPhase('streaming');
      } catch (err) {
        // Distinguish "user said no" from "no camera at all" so the
        // hard-block message can be specific. NotAllowedError =
        // permission denied. Anything else = device unsupported,
        // already-in-use, hardware error, etc.
        if (err && (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError')) {
          setPhase('denied');
        } else {
          setPhase('unavailable');
        }
      }
    }

    start();

    return () => {
      cancelled = true;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
      if (previewBlobRef.current) {
        URL.revokeObjectURL(previewUrl);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Guide rectangle geometry ──────────────────────────────────────
  // We compute the guide rectangle in *viewport* coordinates for the
  // SVG overlay AND store the same rectangle as a fraction of the
  // video frame so we can crop the captured frame correctly even when
  // the video's natural resolution differs from the rendered size.
  function computeGuide() {
    if (!videoRef.current || !overlayRef.current) return null;
    const w = overlayRef.current.clientWidth;
    const h = overlayRef.current.clientHeight;
    const aspect = spec.aspect;
    const isPortrait = spec.orientation === 'portrait';
    // In portrait the doc's long edge is vertical, so the rectangle
    // is taller than wide: width/height = 1/aspect.
    const ratio = isPortrait ? 1 / aspect : aspect;

    // Fit the guide inside the viewport with FRAME_INSET_RATIO padding
    // on the binding dimension.
    let gw = w * FRAME_INSET_RATIO;
    let gh = gw / ratio;
    if (gh > h * FRAME_INSET_RATIO) {
      gh = h * FRAME_INSET_RATIO;
      gw = gh * ratio;
    }
    const gx = (w - gw) / 2;
    const gy = (h - gh) / 2;

    return {
      x: gx, y: gy, w: gw, h: gh,
      vw: w, vh: h,
      // Fractional coords (0..1) to apply to the captured frame
      // regardless of its natural resolution.
      frac: { x: gx / w, y: gy / h, w: gw / w, h: gh / h },
    };
  }

  // ── Capture + crop ────────────────────────────────────────────────
  async function shoot() {
    const video = videoRef.current;
    if (!video) return;
    const guide = computeGuide();
    if (!guide) return;

    // The displayed video uses object-fit: cover, so the visible area
    // crops a fraction off the natural frame. Map the guide fraction
    // (which is in viewport coords) onto the natural frame, accounting
    // for the cover-crop on the limiting axis.
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (!vw || !vh) return;

    const overlayAspect = guide.vw / guide.vh;
    const frameAspect = vw / vh;

    let visibleW = vw, visibleH = vh, offsetX = 0, offsetY = 0;
    if (frameAspect > overlayAspect) {
      // Frame is wider than viewport — left/right got cropped by cover
      visibleW = vh * overlayAspect;
      offsetX = (vw - visibleW) / 2;
    } else {
      visibleH = vw / overlayAspect;
      offsetY = (vh - visibleH) / 2;
    }

    const cropX = offsetX + guide.frac.x * visibleW;
    const cropY = offsetY + guide.frac.y * visibleH;
    const cropW = guide.frac.w * visibleW;
    const cropH = guide.frac.h * visibleH;

    // Cap output size to avoid 8MB+ uploads on a 4K phone camera.
    const longEdge = Math.max(cropW, cropH);
    const scale = longEdge > OUTPUT_LONG_EDGE_PX ? OUTPUT_LONG_EDGE_PX / longEdge : 1;
    const outW = Math.round(cropW * scale);
    const outH = Math.round(cropH * scale);

    const canvas = document.createElement('canvas');
    canvas.width = outW;
    canvas.height = outH;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, cropX, cropY, cropW, cropH, 0, 0, outW, outH);

    const blob = await new Promise((resolve) => {
      canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.92);
    });
    if (!blob) return;

    if (previewBlobRef.current && previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    previewBlobRef.current = blob;
    setPreviewUrl(URL.createObjectURL(blob));
    setPhase('confirming');
  }

  function retake() {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl(null);
    }
    previewBlobRef.current = null;
    setPhase('streaming');
  }

  function confirm() {
    if (!previewBlobRef.current || previewing) return;
    setPreviewing(true);
    const file = new File(
      [previewBlobRef.current],
      `${docType}_${Date.now()}.jpg`,
      { type: 'image/jpeg' },
    );
    onCapture(file);
  }

  // ── Render branches ───────────────────────────────────────────────
  if (phase === 'denied') {
    return (
      <div className="capture-modal" role="dialog" aria-modal="true">
        <div className="capture-header">
          <span className="capture-title">
            <L ar={spec?.labelAr} en={spec?.labelEn} />
          </span>
          <button type="button" className="capture-close" onClick={onCancel} aria-label="close">×</button>
        </div>
        <div className="capture-block">
          <div>
            <div className="capture-block__icon" aria-hidden>📷</div>
            <h3 className="capture-block__title">
              <L ar="نحتاج إذنك للوصول إلى الكاميرا" en="Camera permission required" />
            </h3>
            <p className="capture-block__body">
              <L
                ar="لا يمكن إرسال هذه الخدمة إلا عبر التقاط حيّ للمستندات. يرجى السماح بالوصول إلى الكاميرا من إعدادات المتصفح وإعادة المحاولة."
                en="This service requires live document capture. Please allow camera access in your browser settings and try again."
              />
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (phase === 'unavailable') {
    return (
      <div className="capture-modal" role="dialog" aria-modal="true">
        <div className="capture-header">
          <span className="capture-title">
            <L ar={spec?.labelAr} en={spec?.labelEn} />
          </span>
          <button type="button" className="capture-close" onClick={onCancel} aria-label="close">×</button>
        </div>
        <div className="capture-block">
          <div>
            <div className="capture-block__icon" aria-hidden>📱</div>
            <h3 className="capture-block__title">
              <L ar="هذه الخدمة تتطلب هاتفاً" en="A phone is required" />
            </h3>
            <p className="capture-block__body">
              <L
                ar="لم نتمكن من العثور على كاميرا. يرجى فتح الموقع من هاتف ذكي يحتوي على كاميرا خلفية وإعادة المحاولة."
                en="No camera was detected. Please open this site on a smartphone with a rear camera and try again."
              />
            </p>
          </div>
        </div>
      </div>
    );
  }

  // streaming + confirming + requesting all share the camera shell
  const guide = phase === 'streaming' ? computeGuide() : null;

  return (
    <div className="capture-modal" role="dialog" aria-modal="true">
      <div className="capture-header">
        <span className="capture-title">
          <L ar={spec?.labelAr} en={spec?.labelEn} />
        </span>
        <button type="button" className="capture-close" onClick={onCancel} aria-label="close">×</button>
      </div>

      <div className="capture-stage" ref={overlayRef}>
        <video
          ref={videoRef}
          className="capture-video"
          autoPlay
          playsInline
          muted
        />

        {phase === 'streaming' && guide && (
          <svg
            className="capture-overlay"
            viewBox={`0 0 ${guide.vw} ${guide.vh}`}
            preserveAspectRatio="none"
          >
            {/* Dark mask everywhere except the guide rectangle. We use
                a path with the outer rect minus the inner rect (even-odd
                fill) so SVG renders the cutout correctly. */}
            <path
              d={`M0,0 H${guide.vw} V${guide.vh} H0 Z M${guide.x},${guide.y} h${guide.w} v${guide.h} h-${guide.w} Z`}
              fillRule="evenodd"
              className="capture-frame"
            />
            {/* Dashed border on the guide rectangle */}
            <rect
              x={guide.x} y={guide.y} width={guide.w} height={guide.h}
              className="capture-frame-stroke"
            />
            {/* Solid corner brackets — give the eye something to lock
                onto when aligning the document. Each bracket = ~10% of
                the guide's longer side. */}
            {(() => {
              const brk = Math.min(guide.w, guide.h) * 0.12;
              const mk = (x1, y1, x2, y2, x3, y3) =>
                `M${x1},${y1} L${x2},${y2} L${x3},${y3}`;
              return (
                <>
                  <path d={mk(guide.x, guide.y + brk, guide.x, guide.y, guide.x + brk, guide.y)} className="capture-frame-corner" />
                  <path d={mk(guide.x + guide.w - brk, guide.y, guide.x + guide.w, guide.y, guide.x + guide.w, guide.y + brk)} className="capture-frame-corner" />
                  <path d={mk(guide.x, guide.y + guide.h - brk, guide.x, guide.y + guide.h, guide.x + brk, guide.y + guide.h)} className="capture-frame-corner" />
                  <path d={mk(guide.x + guide.w - brk, guide.y + guide.h, guide.x + guide.w, guide.y + guide.h, guide.x + guide.w, guide.y + guide.h - brk)} className="capture-frame-corner" />
                </>
              );
            })()}
          </svg>
        )}

        {phase === 'streaming' && (
          <div className="capture-hint">
            <L
              ar="ضع المستند داخل الإطار، ثم اضغط زر الالتقاط"
              en="Align the document inside the frame, then tap the shutter"
            />
          </div>
        )}

        {phase === 'confirming' && previewUrl && (
          <div className="capture-confirm">
            <div className="capture-preview">
              <img src={previewUrl} alt="captured" />
            </div>
            <div className="capture-confirm__actions">
              <button
                type="button"
                className="capture-confirm__btn capture-confirm__btn--secondary"
                onClick={retake}
                disabled={previewing}
              >
                <L ar="إعادة الالتقاط" en="Retake" />
              </button>
              <button
                type="button"
                className="capture-confirm__btn capture-confirm__btn--primary"
                onClick={confirm}
                disabled={previewing}
              >
                <L ar="استخدام هذه الصورة" en="Use this photo" />
              </button>
            </div>
          </div>
        )}
      </div>

      {phase === 'streaming' && (
        <div className="capture-controls">
          <button
            type="button"
            className="capture-controls__secondary"
            onClick={onCancel}
          >
            <L ar="إلغاء" en="Cancel" />
          </button>
          <button
            type="button"
            className="capture-shutter"
            onClick={shoot}
            aria-label="shutter"
          />
          <span className="capture-controls__secondary" style={{ visibility: 'hidden' }}>
            placeholder
          </span>
        </div>
      )}
    </div>
  );
}
