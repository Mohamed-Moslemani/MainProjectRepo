import { useState, useCallback, useEffect, useRef } from 'react';
import { FaceLivenessDetectorCore } from '@aws-amplify/ui-react-liveness';
import '@aws-amplify/ui-react/styles.css';
import { livenessApi } from '@shared/api/liveness';
import L from '@shared/components/L';
import '@shared/styles/liveness.css';

/**
 * LivenessCheck component — runs AWS Rekognition Face Liveness challenge.
 *
 * Props:
 *   caseId       — the case to attach the liveness session to
 *   onComplete   — callback({ liveness_passed, confidence, similarity_score, ... })
 *   onError      — callback(errorMessage)
 *   onCancel     — callback when user cancels
 */
// AWS Rekognition's FaceLivenessDetectorCore refuses to start when
// the viewport is mobile-sized AND wider-than-tall, but it ALSO mounts
// its own UI and opens the WebSocket before deciding to bail — leaving
// the user staring at "Connecting…" for several seconds before the
// final MOBILE_LANDSCAPE_ERROR. We pre-empt that decision client-side
// using the same heuristic AWS's SDK uses (window width < 769 px AND
// width > height). When the heuristic matches, render a rotate-device
// screen instead of mounting the SDK at all.
const SDK_MOBILE_BREAKPOINT_PX = 769;
function detectAwsLandscapeReject() {
  if (typeof window === 'undefined') return false;
  const w = window.innerWidth;
  const h = window.innerHeight;
  return w < SDK_MOBILE_BREAKPOINT_PX && w > h;
}

export default function LivenessCheck({ caseId, onComplete, onError, onCancel }) {
  const [sessionId, setSessionId] = useState(null);
  const [region, setRegion] = useState(null);
  const [credentials, setCredentials] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [awsLandscapeReject, setAwsLandscapeReject] = useState(detectAwsLandscapeReject);

  // Track viewport rotations so the user can recover by simply
  // rotating their device — no remount, no reload.
  useEffect(() => {
    const onResize = () => setAwsLandscapeReject(detectAwsLandscapeReject());
    window.addEventListener('resize', onResize);
    window.addEventListener('orientationchange', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('orientationchange', onResize);
    };
  }, []);

  // Latest callback refs. The init effect MUST NOT redeclare these as
  // dependencies — every parent re-render hands in a fresh function
  // reference, which would re-fire init(), create a brand new AWS
  // Rekognition session, and overwrite case.liveness_session_id on the
  // backend. The Amplify SDK is already mounted with the FIRST sessionId
  // so its onAnalysisComplete fires get-results with the stale id →
  // gateway returns 400 "Session ID mismatch". Stash the callbacks in a
  // ref instead so callers can pass inline functions safely.
  const onErrorRef = useRef(onError);
  const onCompleteRef = useRef(onComplete);
  const onCancelRef = useRef(onCancel);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);
  useEffect(() => { onCompleteRef.current = onComplete; }, [onComplete]);
  useEffect(() => { onCancelRef.current = onCancel; }, [onCancel]);

  // Guard against React 18 StrictMode double-mount in dev: a second
  // effect run would create a duplicate Rekognition session and bring
  // back the same Session-ID-mismatch race. Inflight ref short-circuits
  // the second invocation when the first is already in flight or done.
  const initStartedRef = useRef(false);

  // Create session + fetch credentials on mount. Only re-runs when the
  // caseId actually changes — callbacks are read via refs above.
  useEffect(() => {
    if (initStartedRef.current) return;
    initStartedRef.current = true;
    let cancelled = false;

    async function init() {
      try {
        const [sessionRes, credsRes] = await Promise.all([
          livenessApi.createSession(caseId),
          livenessApi.getCredentials(),
        ]);

        if (cancelled) return;

        setSessionId(sessionRes.data.session_id);
        setRegion(sessionRes.data.region);
        // Amplify Liveness expects `expiration` as a Date for its
        // refresh logic. Without it the SDK considers creds expired
        // and gets stuck retrying the WSS handshake → permanent
        // "Connecting…" in the UI. Backend returns ISO-8601, parse
        // here.
        setCredentials({
          accessKeyId: credsRes.data.access_key_id,
          secretAccessKey: credsRes.data.secret_access_key,
          sessionToken: credsRes.data.session_token,
          expiration: credsRes.data.expiration
            ? new Date(credsRes.data.expiration)
            : new Date(Date.now() + 15 * 60 * 1000),
        });
      } catch (err) {
        if (!cancelled) {
          const msg = err.response?.data?.detail || 'فشل في بدء جلسة التحقق من الهوية. Failed to initialize liveness session.';
          setError(msg);
          onErrorRef.current?.(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    init();
    return () => { cancelled = true; };
  }, [caseId]);

  // Amplify can fire onAnalysisComplete more than once on flaky
  // connections, AND can fire it back-to-back with onError when the
  // session ends in a failure state (MOBILE_LANDSCAPE_ERROR,
  // CAMERA_ACCESS_ERROR, …). De-dupe via the ref guard, plus an
  // AbortController so we can actively cancel an in-flight call when
  // an error fires — without it, the React state update on error
  // unmounts the SDK widget, the browser tears the request down
  // mid-flight, and the console shows a misleading CORS error
  // (the request actually died as ERR_FAILED before any response).
  const resultsFetchedRef = useRef(false);
  const inflightAbortRef = useRef(null);
  const handleAnalysisComplete = useCallback(async () => {
    if (resultsFetchedRef.current) return;
    resultsFetchedRef.current = true;
    const ctrl = new AbortController();
    inflightAbortRef.current = ctrl;
    try {
      const res = await livenessApi.getResults(caseId, sessionId, { signal: ctrl.signal });
      onCompleteRef.current?.(res.data);
    } catch (err) {
      // Cancellation by handleError or unmount — silent. The error
      // path was/will be reported through onErrorRef there.
      if (err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED' || ctrl.signal.aborted) {
        return;
      }
      // Allow a retry on transient failure — only one *successful*
      // fetch should be one-shot.
      resultsFetchedRef.current = false;
      const msg = err.response?.data?.detail || 'تعذّر استرداد نتائج التحقق. Failed to get liveness results.';
      onErrorRef.current?.(msg);
    } finally {
      if (inflightAbortRef.current === ctrl) inflightAbortRef.current = null;
    }
  }, [caseId, sessionId]);

  // Abort any in-flight get-results on unmount (component leaves the
  // tree e.g. on route change) so we don't end up with an orphaned
  // request the browser tears down later.
  useEffect(() => () => {
    inflightAbortRef.current?.abort();
  }, []);

  const handleError = useCallback((livenessError) => {
    // Suppress the spurious onAnalysisComplete the SDK may fire after
    // onError, AND cancel any get-results that's already in flight.
    resultsFetchedRef.current = true;
    inflightAbortRef.current?.abort();

    // Amplify wraps the underlying SDK error in different shapes
    // depending on what failed. Translate the well-known states
    // into something a citizen can act on; everything else falls
    // back to the SDK's raw message + the state code.
    console.error('[Liveness] error payload:', livenessError);
    const e = livenessError || {};
    const inner = e.error || {};

    // Known SDK states. The strings come straight out of
    // @aws-amplify/ui-react-liveness; what's in here are the ones
    // a citizen can recover from without help.
    const STATE_HINTS = {
      MOBILE_LANDSCAPE_ERROR: "يرجى تدوير الجهاز عمودياً (وضع الشاشة الطولي). Please rotate your device to portrait orientation.",
      CAMERA_ACCESS_ERROR: "السماح بالوصول للكاميرا مطلوب. Camera access is required.",
      CAMERA_FRAMERATE_ERROR: "كاميرا بطيئة جداً — جرّب جهازاً آخر أو متصفحاً مختلفاً. Camera is too slow; try another device or browser.",
      CHECK_SUCCEEDED: null, // not an error
      FRESHNESS_TIMEOUT: "انتهى الوقت — أعد المحاولة. Timed out — please try again.",
      CONNECTION_TIMEOUT: "انقطع الاتصال — تحقق من الإنترنت. Connection lost — check your internet.",
      RUNTIME_ERROR: "خطأ غير متوقع — جرّب مرة أخرى. Unexpected error — please try again.",
      SERVER_ERROR: "تعذّر الاتصال بالخادم. Could not reach the server.",
    };

    let msg;
    if (e.state && STATE_HINTS[e.state]) {
      msg = STATE_HINTS[e.state];
    } else {
      msg =
        inner.message
        || e.message
        || (e.state ? `state=${e.state}` : null)
        || (typeof e === 'string' ? e : null)
        || 'حدث خطأ أثناء التحقق من الهوية. Liveness check encountered an error.';
    }
    setError(msg);
    onErrorRef.current?.(msg);
  }, []);

  if (loading) {
    return (
      <div className="liveness-container">
        <div className="liveness-loading">
          <div className="loading-spinner" />
          <L>{{ ar: <>جارٍ تحضير التحقق من الهوية...</>, en: <>Preparing identity verification...</> }}</L>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="liveness-container">
        <div className="alert alert--error">
          <L>{{ ar: <>خطأ في التحقق من الهوية</>, en: <>Liveness verification error</> }}</L>
          <p style={{ marginTop: '0.5rem', fontSize: '0.875rem' }}>{error}</p>
          <button className="btn btn--sm btn--outline" style={{ marginTop: '1rem' }} onClick={onCancel}>
            <L ar="رجوع" en="Go Back" />
          </button>
        </div>
      </div>
    );
  }

  // Pre-empt AWS's MOBILE_LANDSCAPE_ERROR. If we render the SDK in a
  // viewport AWS will reject, the user spends several seconds staring
  // at "Connecting…" before the SDK finally errors out. We catch it
  // first and show a clear actionable message immediately.
  if (awsLandscapeReject) {
    return (
      <div className="liveness-container">
        <div className="alert alert--warning" style={{ textAlign: 'center', padding: '2rem 1rem' }}>
          <div style={{ fontSize: '2.5rem', marginBottom: '0.5rem' }} aria-hidden>
            ↻
          </div>
          <h3 style={{ marginTop: 0 }}>
            <L
              ar="يرجى تدوير الجهاز عمودياً"
              en="Please rotate your device to portrait"
            />
          </h3>
          <p style={{ fontSize: '0.9rem', color: 'var(--gray-600)', marginTop: '0.75rem' }}>
            <L
              ar="التحقق من الهوية يعمل في الوضع العمودي فقط. إذا كنت على حاسوب، صغّر نافذة المتصفّح حتى تصبح أطول من عرضها."
              en="The identity check only works in portrait orientation. If you're on a desktop, resize the browser window so it's taller than it is wide."
            />
          </p>
          <button
            className="btn btn--sm btn--outline"
            style={{ marginTop: '1.5rem' }}
            onClick={onCancel}
          >
            <L ar="إلغاء" en="Cancel" />
          </button>
        </div>
      </div>
    );
  }

  if (!sessionId || !credentials) return null;

  // Bilingual instruction list. Renders ABOVE the SDK widget so the
  // citizen reads what to do before the camera flashes the oval. Each
  // step has an Arabic primary line + a smaller English secondary line
  // — RTL/LTR is handled by the parent <html dir>.
  const INSTRUCTIONS = [
    {
      ar: 'كن في غرفة مضاءة جيداً، ووجّه وجهك مباشرةً نحو الكاميرا.',
      en: 'Stand in a well-lit room, facing the camera directly.',
    },
    {
      ar: 'انزع النظّارات الشمسية والقبعة وأي قناع يغطّي الوجه.',
      en: 'Remove sunglasses, hats, and anything covering your face.',
    },
    {
      ar: 'أبقِ الجهاز ثابتاً، ووجهك داخل الإطار البيضاوي على الشاشة.',
      en: 'Hold the device steady and keep your face inside the on-screen oval.',
    },
    {
      ar: 'اتبع التعليمات الصوتية والمرئية: قد يُطلب منك الاقتراب أو الابتعاد قليلاً.',
      en: 'Follow the audio + visual cues: you may be asked to move closer or further.',
    },
    {
      ar: 'لا تستخدم صورة فوتوغرافية أو شاشة أخرى — لن يقبل النظام إلا وجهاً حياً حقيقياً.',
      en: 'Do not use a photo or another screen — the system only accepts a real, live face.',
    },
  ];

  // Mock-mode bypass. The Amplify FaceLivenessDetectorCore SDK opens
  // a WebSocket directly to AWS Rekognition Streaming using a real
  // session ID minted by AWS. In mock mode the gateway returns a
  // fake "mock-<uuid>" session ID and synthetic credentials — neither
  // is recognised by AWS, so the SDK fails with SERVER_ERROR and a
  // "Deserialization error" the moment it tries to connect. Skip the
  // SDK entirely and render a one-click "complete" button that calls
  // get-results directly. The backend's mock_get_liveness_session_results
  // returns SUCCEEDED + similarity_score=95 unconditionally.
  const isMock = sessionId.startsWith("mock-");
  if (isMock) {
    return (
      <div className="liveness-container">
        <div className="liveness-header">
          <h3>
            <L ar="التحقق من الهوية (وضع تجريبي)" en="Identity Verification (Mock Mode)" />
          </h3>
          <p className="liveness-instructions">
            <L
              ar="الخادم في وضع تجريبي — يتم تخطي كاميرا AWS Rekognition. اضغط للمتابعة بنتيجة ناجحة محاكاة."
              en="The server is in mock mode — the AWS Rekognition camera step is skipped. Click to complete with a simulated success."
            />
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.75rem", marginTop: "1.5rem", justifyContent: "center" }}>
          <button className="btn btn--primary" onClick={handleAnalysisComplete}>
            <L ar="إكمال التحقق (محاكاة)" en="Complete verification (mock)" />
          </button>
          <button className="btn btn--outline" onClick={onCancel}>
            <L ar="إلغاء" en="Cancel" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="liveness-container">
      <div className="liveness-header">
        <h3>
          <L ar="التحقق من الهوية بالكاميرا" en="Identity Verification (Liveness Check)" />
        </h3>
        <p className="liveness-lead">
          <L
            ar="نتحقّق من أنك أنت فعلاً وليس صورة أو فيديو. تستغرق العملية أقل من دقيقة."
            en="We verify you are a real, live person — not a photo or recording. The check takes under a minute."
          />
        </p>
      </div>

      <ol className="liveness-steps">
        {INSTRUCTIONS.map((step, i) => (
          <li className="liveness-step" key={i}>
            <span className="liveness-step__num">{i + 1}</span>
            <span className="liveness-step__body">
              <span className="liveness-step__ar">{step.ar}</span>
              <span className="liveness-step__en">{step.en}</span>
            </span>
          </li>
        ))}
      </ol>

      <div className="liveness-tip">
        <L
          ar="نصيحة: ضع الجهاز على ارتفاع العين، وتأكد من أن الكاميرا الأمامية نظيفة."
          en="Tip: hold the device at eye level and make sure the front camera lens is clean."
        />
      </div>

      <div className="liveness-widget">
        <FaceLivenessDetectorCore
          sessionId={sessionId}
          region={region}
          onAnalysisComplete={handleAnalysisComplete}
          onError={handleError}
          onUserCancel={onCancel}
          config={{
            credentialProvider: async () => credentials,
          }}
        />
      </div>
    </div>
  );
}