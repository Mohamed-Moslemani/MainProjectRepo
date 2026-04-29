import { useState } from 'react';
import { Link } from 'react-router-dom';
import AuthLayout from '@shared/components/AuthLayout';
import { authApi } from '@shared/api/auth';

export default function ForgotPassword() {
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
        setError(err.response.data.detail || 'محاولات كثيرة. يرجى الانتظار.');
      } else {
        setError('حدث خطأ. يرجى المحاولة مرة أخرى.');
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
            <span className="ar">نسيت كلمة المرور؟</span>
            <span className="en">Forgot password?</span>
          </h2>
          <p className="auth-card__subheading">
            <span className="ar">أدخل بريدك الإلكتروني وسنرسل لك رابط إعادة تعيين كلمة المرور</span>
            <span className="en">Enter your email and we&apos;ll send you a reset link</span>
          </p>

          {error && <div className="alert alert--error">{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label" htmlFor="email">
                <span className="ar">البريد الإلكتروني</span>
                <span className="en">Email</span>
              </label>
              <input
                id="email"
                type="email"
                className="form-input"
                placeholder="you@example.com"
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
                  <span className="ar">إرسال رابط إعادة التعيين</span>
                  <span className="en">Send Reset Link</span>
                </>
              )}
            </button>
          </form>
        </>
      ) : (
        <div className="verify-container">
          <div className="verify-icon">&#9993;</div>
          <h2 className="auth-card__heading">
            <span className="ar">تحقق من بريدك الإلكتروني</span>
            <span className="en">Check your email</span>
          </h2>
          <p>
            <span className="ar">
              إذا كان هناك حساب مسجّل بـ <strong>{email}</strong>، فقد أرسلنا رابط إعادة تعيين كلمة المرور. ينتهي خلال ١٥ دقيقة.
            </span>
            <span className="en" style={{ fontSize: '0.8rem', color: 'var(--gray-400)' }}>
              If an account exists for <strong>{email}</strong>, we&apos;ve sent a reset link. It expires in 15 minutes.
            </span>
          </p>
        </div>
      )}

      <p className="auth-footer">
        <span className="ar"><Link to="/login">العودة لتسجيل الدخول</Link></span>
        <span className="en"><Link to="/login">Back to Sign In</Link></span>
      </p>
    </AuthLayout>
  );
}
