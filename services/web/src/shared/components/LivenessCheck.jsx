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
        setCredentials({
          accessKeyId: credsRes.data.access_key_id,
          secretAccessKey: credsRes.data.secret_access_key,
          sessionToken: credsRes.data.session_token,
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
    const msg = livenessError?.error?.message || 'Liveness check encountered an error';
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