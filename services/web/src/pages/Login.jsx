import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import AuthLayout from '../components/AuthLayout';
import { useAuth } from '../context/AuthContext';

export default function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();

  const [form, setForm] = useState({ email: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
    setError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      await login(form.email, form.password);
      navigate('/dashboard');
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (err.response?.status === 403) {
        setError(detail || 'البريد الإلكتروني غير مُفعّل. تحقق من بريدك.');
      } else if (err.response?.status === 429) {
        setError(detail || 'محاولات كثيرة. يرجى الانتظار.');
      } else {
        setError(detail || 'بريد إلكتروني أو كلمة مرور غير صحيحة.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout>
      <h2 className="auth-card__heading">
        <span className="ar">مرحباً بعودتك</span>
        <span className="en">Welcome back</span>
      </h2>
      <p className="auth-card__subheading">
        <span className="ar">سجّل الدخول إلى حسابك في دوك فلو</span>
        <span className="en">Sign in to your DocFlow account</span>
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
            name="email"
            type="email"
            className="form-input"
            placeholder="you@example.com"
            value={form.email}
            onChange={handleChange}
            required
            autoFocus
            dir="ltr"
          />
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="password">
            <span className="ar">كلمة المرور</span>
            <span className="en">Password</span>
          </label>
          <input
            id="password"
            name="password"
            type="password"
            className="form-input"
            placeholder="أدخل كلمة المرور"
            value={form.password}
            onChange={handleChange}
            required
            dir="ltr"
          />
        </div>

        <div className="auth-extras">
          <span />
          <Link to="/forgot-password" className="btn btn--ghost">
            <span className="ar">نسيت كلمة المرور؟</span>
            <span className="en">Forgot password?</span>
          </Link>
        </div>

        <button type="submit" className="btn btn--primary" disabled={loading}>
          {loading ? <span className="spinner" /> : (
            <>
              <span className="ar">تسجيل الدخول</span>
              <span className="en">Sign In</span>
            </>
          )}
        </button>
      </form>

      <p className="auth-footer">
        <span className="ar">ليس لديك حساب؟ <Link to="/register">أنشئ حساباً</Link></span>
        <span className="en">Don&apos;t have an account? <Link to="/register">Create one</Link></span>
      </p>
    </AuthLayout>
  );
}
