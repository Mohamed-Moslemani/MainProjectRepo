import { useSearchParams, Link } from 'react-router-dom';
import '@shared/styles/dashboard.css';
import L from '@shared/components/L';

export default function PaymentCancelled() {
  const [params] = useSearchParams();
  const caseId = params.get('case_id');

  return (
    <div className="dashboard-page">
      <div className="payment-callback">
        <div className="info-cross" aria-hidden>✕</div>
        <h1>
          <L ar="تم إلغاء الدفع" en="Payment cancelled" />
        </h1>
        <p>
          <L
            ar={<>لقد ألغيت عملية الدفع قبل تأكيدها. لم يتم خصم أي مبلغ. لا يزال طلبك في حالة <strong>بانتظار الدفع</strong> — يمكنك المحاولة من جديد في أي وقت.</>}
            en={<>You cancelled the checkout before the payment was captured. No charge was made. Your case is still in <strong>payment pending</strong> — you can try again whenever you're ready.</>}
          />
        </p>
        <div className="callback-actions">
          {caseId ? (
            <Link to={`/case/${caseId}`} className="primary-button">
              <L ar="العودة إلى طلبي" en="Return to my case" />
            </Link>
          ) : (
            <Link to="/dashboard" className="primary-button">
              <L ar="العودة إلى لوحة التحكم" en="Back to dashboard" />
            </Link>
          )}
          <Link to="/dashboard" className="ghost-button">
            <L ar="لوحة التحكم" en="Dashboard" />
          </Link>
        </div>
      </div>
    </div>
  );
}
