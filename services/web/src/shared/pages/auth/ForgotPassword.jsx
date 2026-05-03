import { useState } from 'react';
import { Link } from 'react-router-dom';
import AuthLayout from '@shared/components/AuthLayout';
import { authApi } from '@shared/api/auth';
import L from '@shared/components/L';
import { useL } from '@shared/hooks/useL';

export default function ForgotPassword() {
  const { pick } = useL();
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      await authApi.forgotPassword(email);
      setSent(true);
    } catch (err) {
      if (err.response?.status === 429) {
        setError(err.response.data.detail || pick({
          ar: 'محاولات كثيرة. يرجى الانتظار.',
          en: 'Too many attempts. Please wait a moment and try again.',
        }));
      } else {
        setError(pick({
          ar: 'حدث خطأ. يرجى المحاولة مرة أخرى.',
          en: 'Something went wrong. Please try again.',
        }));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout>
      {!sent ? (
        <>
          <h2 className="auth-card__heading">
            <L ar="نسيت كلمة المرور؟" en="Forgot password?" />
          </h2>
          <p className="auth-card__subheading">
            <L ar="أدخل بريدك الإلكتروني وسنرسل لك رابط إعادة تعيين كلمة المرور" en="Enter your email and we&apos;ll send you a reset link" />
          </p>

          {error && <div className="alert alert--error">{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label" htmlFor="email">
                <L ar="البريد الإلكتروني" en="Email" />
              </label>
              <input
                id="email"
                type="email"
                className="form-input"
                value={email}
                onChange={(e) => { setEmail(e.target.value); setError(''); }}
                required
                autoFocus
                dir="ltr"
              />
            </div>

            <button type="submit" className="btn btn--primary" disabled={loading}>
              {loading ? <span className="spinner" /> : (
                <>
                  <L ar="إرسال رابط إعادة التعيين" en="Send Reset Link" />
                </>
              )}
            </button>
          </form>
        </>
      ) : (
        <div className="verify-container">
          <div className="verify-icon">&#9993;</div>
          <h2 className="auth-card__heading">
            <L ar="تحقق من بريدك الإلكتروني" en="Check your email" />
          </h2>
          <p>
            <L>{{ ar: <>إذا كان هناك حساب مسجّل بـ <strong>{email}</strong>، فقد أرسلنا رابط إعادة تعيين كلمة المرور. ينتهي خلال ١٥ دقيقة.</>, en: <>If an account exists for <strong>{email}</strong>, we&apos;ve sent a reset link. It expires in 15 minutes.</> }}</L>
          </p>
        </div>
      )}

      <p className="auth-footer">
        <L>{{ ar: <><Link to="/login">العودة لتسجيل الدخول</Link></>, en: <><Link to="/login">Back to Sign In</Link></> }}</L>
      </p>
    </AuthLayout>
  );
}
