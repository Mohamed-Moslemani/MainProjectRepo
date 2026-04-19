import { useSearchParams, Link } from 'react-router-dom';
import '../styles/dashboard.css';

export default function PaymentCancelled() {
  const [params] = useSearchParams();
  const caseId = params.get('case_id');

  return (
    <div className="dashboard-page">
      <div className="payment-callback">
        <div className="info-cross" aria-hidden>✕</div>
        <h1>
          <span className="ar">تم إلغاء الدفع</span>
          <span className="en">Payment cancelled</span>
        </h1>
        <p>
          You cancelled the checkout before the payment was captured. No charge was made.
          Your case is still in <strong>payment pending</strong> — you can try again whenever you're ready.
        </p>
        <div className="callback-actions">
          {caseId ? (
            <Link to={`/case/${caseId}`} className="primary-button">
              Return to my case
            </Link>
          ) : (
            <Link to="/dashboard" className="primary-button">
              Back to dashboard
            </Link>
          )}
          <Link to="/dashboard" className="ghost-button">
            Dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}
