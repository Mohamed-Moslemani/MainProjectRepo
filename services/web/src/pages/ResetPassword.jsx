import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import AuthLayout from '../components/AuthLayout';
import { authApi } from '../api/auth';

function getPasswordStrength(pw) {
  let score = 0;
  if (pw.length >= 8) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[a-z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  return score;
}

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (password !== confirm) {
      setError('كلمات المرور غير متطابقة.');
      return;
    }

    if (getPasswordStrength(password) < 5) {
      setError('كلمة المرور يجب أن تحتوي على ٨ أحرف على الأقل، حرف كبير وصغير، رقم، ورمز خاص.');
      return;
    }

    setLoading(true);
    try {
      await authApi.resetPassword(token, password);
      setSuccess(true);
    } catch (err) {
      setError(err.response?.data?.detail || 'رابط غير صالح أو منتهي الصلاحية.');
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <AuthLayout>
        <div className="verify-container">
          <div className="verify-icon" style={{ color: 'var(--error)' }}>&#10007;</div>
          <h2 className="auth-card__heading">
            <span className="ar">رابط غير صالح</span>
            <span className="en">Invalid Link</span>
          </h2>
          <p>
            <span className="ar">هذا الرابط غير صالح. يرجى طلب رابط جديد.</span>
            <span className="en">This reset link is invalid. Please request a new one.</span>
          </p>
          <Link to="/forgot-password" className="btn btn--primary" style={{ maxWidth: 280, margin: '1rem auto 0' }}>
            <span className="ar">طلب رابط جديد</span>
            <span className="en">Request New Link</span>
          </Link>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      {!success ? (
        <>
          <h2 className="auth-card__heading">
            <span className="ar">تعيين كلمة مرور جديدة</span>
            <span className="en">Set new password</span>
          </h2>
          <p className="auth-card__subheading">
            <span className="ar">اختر كلمة مرور قوية لحسابك</span>
            <span className="en">Choose a strong password for your account</span>
          </p>

          {error && <div className="alert alert--error">{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label" htmlFor="password">
                <span className="ar">كلمة المرور الجديدة</span>
                <span className="en">New Password</span>
              </label>
              <input
                id="password"
                type="password"
                className="form-input"
                placeholder="أدخل كلمة المرور الجديدة"
                value={password}
                onChange={(e) => { setPassword(e.target.value); setError(''); }}
                required
                autoFocus
                dir="ltr"
              />
              <p className="password-hint">
                <span className="ar">٨ أحرف على الأقل، حرف كبير وصغير، رقم، ورمز خاص</span>
                <span className="en">Min 8 chars, uppercase, lowercase, number, and special character</span>
              </p>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="confirm">
                <span className="ar">تأكيد كلمة المرور</span>
                <span className="en">Confirm Password</span>
              </label>
              <input
                id="confirm"
                type="password"
                className="form-input"
                placeholder="أعد إدخال كلمة المرور"
                value={confirm}
                onChange={(e) => { setConfirm(e.target.value); setError(''); }}
                required
                dir="ltr"
              />
            </div>

            <button type="submit" className="btn btn--primary" disabled={loading}>
              {loading ? <span className="spinner" /> : (
                <>
                  <span className="ar">إعادة تعيين كلمة المرور</span>
                  <span className="en">Reset Password</span>
                </>
              )}
            </button>
          </form>
        </>
      ) : (
        <div className="verify-container">
          <div className="verify-icon" style={{ color: 'var(--success)' }}>&#10003;</div>
          <h2 className="auth-card__heading">
            <span className="ar">تم إعادة تعيين كلمة المرور!</span>
            <span className="en">Password Reset!</span>
          </h2>
          <div className="alert alert--success">
            <span className="ar">تم تغيير كلمة المرور بنجاح.</span>
            <span className="en">Your password has been changed successfully.</span>
          </div>
          <Link to="/login" className="btn btn--primary" style={{ maxWidth: 280, margin: '0 auto' }}>
            <span className="ar">المتابعة لتسجيل الدخول</span>
            <span className="en">Continue to Sign In</span>
          </Link>
        </div>
      )}
    </AuthLayout>
  );
}
