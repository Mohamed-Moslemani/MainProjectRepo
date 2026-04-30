import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import AuthLayout from '@shared/components/AuthLayout';
import PasswordInput from '@shared/components/PasswordInput';
import { authApi } from '@shared/api/auth';
import L from '@shared/components/L';

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
            <L ar="رابط غير صالح" en="Invalid Link" />
          </h2>
          <p>
            <L ar="هذا الرابط غير صالح. يرجى طلب رابط جديد." en="This reset link is invalid. Please request a new one." />
          </p>
          <Link to="/forgot-password" className="btn btn--primary" style={{ maxWidth: 280, margin: '1rem auto 0' }}>
            <L ar="طلب رابط جديد" en="Request New Link" />
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
            <L ar="تعيين كلمة مرور جديدة" en="Set new password" />
          </h2>
          <p className="auth-card__subheading">
            <L ar="اختر كلمة مرور قوية لحسابك" en="Choose a strong password for your account" />
          </p>

          {error && <div className="alert alert--error">{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label" htmlFor="password">
                <L ar="كلمة المرور الجديدة" en="New Password" />
              </label>
              <PasswordInput
                id="password"
                placeholder="أدخل كلمة المرور الجديدة"
                value={password}
                onChange={(e) => { setPassword(e.target.value); setError(''); }}
                required
                autoFocus
              />
              <p className="password-hint">
                <L ar="٨ أحرف على الأقل، حرف كبير وصغير، رقم، ورمز خاص" en="Min 8 chars, uppercase, lowercase, number, and special character" />
              </p>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="confirm">
                <L ar="تأكيد كلمة المرور" en="Confirm Password" />
              </label>
              <PasswordInput
                id="confirm"
                placeholder="أعد إدخال كلمة المرور"
                value={confirm}
                onChange={(e) => { setConfirm(e.target.value); setError(''); }}
                required
              />
            </div>

            <button type="submit" className="btn btn--primary" disabled={loading}>
              {loading ? <span className="spinner" /> : (
                <>
                  <L ar="إعادة تعيين كلمة المرور" en="Reset Password" />
                </>
              )}
            </button>
          </form>
        </>
      ) : (
        <div className="verify-container">
          <div className="verify-icon" style={{ color: 'var(--success)' }}>&#10003;</div>
          <h2 className="auth-card__heading">
            <L ar="تم إعادة تعيين كلمة المرور!" en="Password Reset!" />
          </h2>
          <div className="alert alert--success">
            <L ar="تم تغيير كلمة المرور بنجاح." en="Your password has been changed successfully." />
          </div>
          <Link to="/login" className="btn btn--primary" style={{ maxWidth: 280, margin: '0 auto' }}>
            <L ar="المتابعة لتسجيل الدخول" en="Continue to Sign In" />
          </Link>
        </div>
      )}
    </AuthLayout>
  );
}
