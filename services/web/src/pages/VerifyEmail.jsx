import { useState, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import AuthLayout from '../components/AuthLayout';
import { authApi } from '../api/auth';
import '../styles/verify.css';

export default function VerifyEmail() {
  const location = useLocation();
  const emailFromState = location.state?.email;

  const [code, setCode] = useState(['', '', '', '', '', '']);
  const [status, setStatus] = useState('pending');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [resendLoading, setResendLoading] = useState(false);
  const [resendEmail, setResendEmail] = useState(emailFromState || '');
  const [resendDone, setResendDone] = useState(false);

  const inputRefs = useRef([]);

  const handleChange = (index, value) => {
    if (value && !/^\d$/.test(value)) return;

    const newCode = [...code];
    newCode[index] = value;
    setCode(newCode);

    if (value && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }

    if (value && index === 5 && newCode.every((d) => d !== '')) {
      handleSubmit(newCode.join(''));
    }
  };

  const handleKeyDown = (index, e) => {
    if (e.key === 'Backspace' && !code[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handlePaste = (e) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
    if (!pasted) return;

    const newCode = [...code];
    for (let i = 0; i < 6; i++) {
      newCode[i] = pasted[i] || '';
    }
    setCode(newCode);

    const lastIndex = Math.min(pasted.length, 6) - 1;
    inputRefs.current[lastIndex]?.focus();

    if (pasted.length === 6) {
      handleSubmit(pasted);
    }
  };

  const handleSubmit = async (codeStr) => {
    if (!codeStr || codeStr.length !== 6) return;
    setLoading(true);
    setMessage('');

    try {
      await authApi.verifyEmail(codeStr);
      setStatus('success');
      setMessage('تم التحقق من بريدك الإلكتروني بنجاح!');
    } catch (err) {
      setStatus('error');
      setMessage(err.response?.data?.detail || 'رمز غير صالح أو منتهي الصلاحية.');
    } finally {
      setLoading(false);
    }
  };

  const handleFormSubmit = (e) => {
    e.preventDefault();
    handleSubmit(code.join(''));
  };

  const handleResend = async (e) => {
    e.preventDefault();
    if (!resendEmail) return;
    setResendLoading(true);
    try {
      await authApi.resendVerification(resendEmail);
      setResendDone(true);
      setCode(['', '', '', '', '', '']);
      setStatus('pending');
      setMessage('');
      setTimeout(() => setResendDone(false), 5000);
    } catch {
      setMessage('فشل في إعادة الإرسال. يرجى المحاولة مرة أخرى.');
    } finally {
      setResendLoading(false);
    }
  };

  const handleRetry = () => {
    setCode(['', '', '', '', '', '']);
    setStatus('pending');
    setMessage('');
    inputRefs.current[0]?.focus();
  };

  return (
    <AuthLayout>
      <div className="verify-container">
        {status === 'success' ? (
          <>
            <div className="verify-icon" style={{ color: 'var(--success)' }}>&#10003;</div>
            <h2 className="auth-card__heading">
              <span className="ar">تم التحقق من البريد!</span>
              <span className="en">Email Verified!</span>
            </h2>
            <div className="alert alert--success">{message}</div>
            <Link to="/login" className="btn btn--primary" style={{ maxWidth: 280, margin: '0 auto' }}>
              <span className="ar">المتابعة لتسجيل الدخول</span>
              <span className="en">Continue to Sign In</span>
            </Link>
          </>
        ) : (
          <>
            <div className="verify-icon">&#9993;</div>
            <h2 className="auth-card__heading">
              <span className="ar">أدخل رمز التحقق</span>
              <span className="en">Enter verification code</span>
            </h2>
            <p>
              <span className="ar">
                أرسلنا رمزاً مكوّناً من ٦ أرقام إلى{' '}
                {emailFromState ? <strong>{emailFromState}</strong> : 'بريدك الإلكتروني'}
              </span>
              <span className="en" style={{ fontSize: '0.8rem', color: 'var(--gray-400)' }}>
                We sent a 6-digit code to{' '}
                {emailFromState ? <strong>{emailFromState}</strong> : 'your email'}
              </span>
            </p>

            {status === 'error' && (
              <div className="alert alert--error">{message}</div>
            )}

            {resendDone && (
              <div className="alert alert--success" style={{ justifyContent: 'center' }}>
                <span className="ar">تم إرسال رمز جديد! تحقق من بريدك.</span>
                <span className="en">New code sent! Check your inbox.</span>
              </div>
            )}

            <form onSubmit={handleFormSubmit} className="code-form">
              <div className="code-inputs" onPaste={handlePaste}>
                {code.map((digit, i) => (
                  <input
                    key={i}
                    ref={(el) => (inputRefs.current[i] = el)}
                    type="text"
                    inputMode="numeric"
                    maxLength={1}
                    className={`code-input ${status === 'error' ? 'code-input--error' : ''}`}
                    value={digit}
                    onChange={(e) => handleChange(i, e.target.value)}
                    onKeyDown={(e) => handleKeyDown(i, e)}
                    autoFocus={i === 0}
                    disabled={loading}
                    dir="ltr"
                  />
                ))}
              </div>

              <button
                type="submit"
                className="btn btn--primary"
                disabled={loading || code.some((d) => d === '')}
                style={{ maxWidth: 280, margin: '0 auto' }}
              >
                {loading ? <span className="spinner" /> : (
                  <>
                    <span className="ar">تحقق</span>
                    <span className="en">Verify</span>
                  </>
                )}
              </button>
            </form>

            {status === 'error' && (
              <button className="btn btn--ghost" onClick={handleRetry} style={{ marginTop: '0.5rem' }}>
                <span className="ar">حاول مجدداً</span>
                <span className="en">Try again</span>
              </button>
            )}

            <div className="verify-resend">
              <p>
                <span className="ar">لم تستلم الرمز؟</span>
                <span className="en">Didn&apos;t receive the code?</span>
              </p>
              {!emailFromState && (
                <div className="form-group" style={{ marginTop: '0.5rem' }}>
                  <input
                    type="email"
                    className="form-input"
                    placeholder="أدخل بريدك الإلكتروني"
                    value={resendEmail}
                    onChange={(e) => setResendEmail(e.target.value)}
                    style={{ maxWidth: 280, margin: '0 auto', textAlign: 'center' }}
                    dir="ltr"
                  />
                </div>
              )}
              <button
                className="btn btn--ghost"
                onClick={handleResend}
                disabled={resendLoading || !resendEmail}
              >
                {resendLoading ? (
                  <span className="ar">جارٍ الإرسال...</span>
                ) : (
                  <>
                    <span className="ar">إعادة إرسال الرمز</span>
                    <span className="en">Resend Code</span>
                  </>
                )}
              </button>
            </div>
          </>
        )}

        <p className="auth-footer">
          <span className="ar"><Link to="/login">العودة لتسجيل الدخول</Link></span>
          <span className="en"><Link to="/login">Back to Sign In</Link></span>
        </p>
      </div>
    </AuthLayout>
  );
}
