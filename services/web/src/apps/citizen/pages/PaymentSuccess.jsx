import { useEffect, useState, useRef } from 'react';
import { useSearchParams, useNavigate, Link } from 'react-router-dom';
import { casesApi } from '@shared/api/cases';
import '@shared/styles/dashboard.css';

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 30000;
const REDIRECT_DELAY_MS = 4000;

export default function PaymentSuccess() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const caseId = params.get('case_id');
  const sessionId = params.get('session_id');

  // processing: still waiting for the webhook to flip the case status
  // confirmed : case.status has transitioned to in_production
  // pending_webhook: polling timed out (webhook still may arrive later)
  // missing  : no case_id in URL (shouldn't happen if coming from Stripe)
  const [state, setState] = useState(caseId ? 'processing' : 'missing');
  const [caseData, setCaseData] = useState(null);
  const redirectTimerRef = useRef(null);

  useEffect(() => {
    if (!caseId) return;
    let cancelled = false;
    const deadline = Date.now() + POLL_TIMEOUT_MS;

    async function pollOnce() {
      if (cancelled) return;
      try {
        const { data } = await casesApi.get(caseId);
        if (cancelled) return;
        setCaseData(data);
        // Webhook transitions payment_pending → in_production on success.
        if (data.status === 'in_production' || data.status === 'ready_for_pickup') {
          setState('confirmed');
          redirectTimerRef.current = setTimeout(
            () => navigate(`/case/${caseId}`),
            REDIRECT_DELAY_MS,
          );
          return;
        }
      } catch {
        // 401 / 404 etc — just keep polling; the axios interceptor handles refresh
      }
      if (Date.now() > deadline) {
        setState('pending_webhook');
        return;
      }
      setTimeout(pollOnce, POLL_INTERVAL_MS);
    }

    pollOnce();
    return () => {
      cancelled = true;
      if (redirectTimerRef.current) clearTimeout(redirectTimerRef.current);
    };
  }, [caseId, navigate]);

  if (state === 'missing') {
    return (
      <div className="dashboard-page">
        <div className="payment-callback">
          <h1 className="error-title">Missing case reference</h1>
          <p>We could not read the case you paid for. Head back to your dashboard — your payment status will show there.</p>
          <Link to="/dashboard" className="primary-button">Back to dashboard</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-page">
      <div className="payment-callback">
        {state === 'processing' && (
          <>
            <div className="spinner" aria-label="processing" />
            <h1>
              <span className="ar">جاري تأكيد الدفع…</span>
              <span className="en">Confirming your payment…</span>
            </h1>
            <p>Stripe is notifying our server. This usually takes a few seconds.</p>
          </>
        )}

        {state === 'confirmed' && (
          <>
            <div className="success-check" aria-hidden>✓</div>
            <h1>
              <span className="ar">تم الدفع بنجاح</span>
              <span className="en">Payment confirmed</span>
            </h1>
            <p>
              Your application <strong>{caseData?.tracking_id}</strong> is now being produced. We will email you when it's ready for pickup.
            </p>
            <p className="muted">Redirecting to your case in a few seconds…</p>
            <Link to={`/case/${caseId}`} className="primary-button">Go now</Link>
          </>
        )}

        {state === 'pending_webhook' && (
          <>
            <div className="info-clock" aria-hidden>⏳</div>
            <h1>
              <span className="ar">الدفع قيد المعالجة</span>
              <span className="en">Payment received, still processing</span>
            </h1>
            <p>
              Stripe confirms your payment went through, but our server hasn't finished updating your case yet. This can happen briefly during high traffic — come back to your case in a minute and the status will refresh.
            </p>
            <div className="callback-actions">
              <Link to={`/case/${caseId}`} className="primary-button">Open my case</Link>
              <Link to="/dashboard" className="ghost-button">Back to dashboard</Link>
            </div>
            {sessionId && <p className="muted small">Reference: {sessionId}</p>}
          </>
        )}
      </div>
    </div>
  );
}
