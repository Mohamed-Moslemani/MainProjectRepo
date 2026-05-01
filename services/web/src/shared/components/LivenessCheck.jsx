import { useState, useCallback, useEffect } from 'react';
import { FaceLivenessDetectorCore } from '@aws-amplify/ui-react-liveness';
import '@aws-amplify/ui-react/styles.css';
import { livenessApi } from '@shared/api/liveness';
import L from '@shared/components/L';

/**
 * LivenessCheck component — runs AWS Rekognition Face Liveness challenge.
 *
 * Props:
 *   caseId       — the case to attach the liveness session to
 *   onComplete   — callback({ liveness_passed, confidence, similarity_score, ... })
 *   onError      — callback(errorMessage)
 *   onCancel     — callback when user cancels
 */
export default function LivenessCheck({ caseId, onComplete, onError, onCancel }) {
  const [sessionId, setSessionId] = useState(null);
  const [region, setRegion] = useState(null);
  const [credentials, setCredentials] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Create session + fetch credentials on mount
  useEffect(() => {
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
          const msg = err.response?.data?.detail || 'Failed to initialize liveness session';
          setError(msg);
          onError?.(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    init();
    return () => { cancelled = true; };
  }, [caseId, onError]);

  const handleAnalysisComplete = useCallback(async () => {
    try {
      const res = await livenessApi.getResults(caseId, sessionId);
      onComplete?.(res.data);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to get liveness results';
      onError?.(msg);
    }
  }, [caseId, sessionId, onComplete, onError]);

  const handleError = useCallback((livenessError) => {
    // Amplify wraps the underlying SDK error in different shapes
    // depending on what failed. Translate the well-known states
    // into something a citizen can act on; everything else falls
    // back to the SDK's raw message + the state code.
    // eslint-disable-next-line no-console
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
        || 'Liveness check encountered an error';
    }
    setError(msg);
    onError?.(msg);
  }, [onError]);

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

  if (!sessionId || !credentials) return null;

  return (
    <div className="liveness-container">
      <div className="liveness-header">
        <h3>
          <L ar="التحقق من الهوية" en="Identity Verification" />
        </h3>
        <p className="liveness-instructions">
          <L ar="يرجى اتباع التعليمات على الشاشة. حرّك وجهك داخل الإطار البيضاوي." en="Follow the on-screen instructions. Move your face into the oval frame." />
        </p>
      </div>
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
  );
}