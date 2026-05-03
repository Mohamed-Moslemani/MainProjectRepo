import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import AuthLayout from '@shared/components/AuthLayout';
import PasswordInput from '@shared/components/PasswordInput';
import { useAuth } from '@shared/context/useAuth';

export default function Login() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { login } = useAuth();
  const [searchParams] = useSearchParams();

  const [form, setForm] = useState({ email: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // Honour ?reason=idle from the auto-logout flow so the citizen knows
  // *why* they're back at the login screen.
  const idleReason = searchParams.get('reason') === 'idle';

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
      const status = err.response?.status;
      // Unverified accounts get bounced here with a 401 + a detail
      // mentioning "not verified" — without a redirect they end up
      // stuck (the verification PIN is sitting in their inbox but
      // there's no link from /login to /verify-email). Send them
      // straight to the verify page with the email pre-filled.
      if (status === 401 && /not verified|not been verified/i.test(detail || '')) {
        navigate('/verify-email', { state: { email: form.email } });
        return;
      }
      if (status === 429) {
        setError(detail || t('auth.login.errorGeneric'));
      } else {
        setError(detail || t('auth.login.errorInvalid'));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout>
      <h2 className="auth-card__heading">{t('auth.login.title')}</h2>
      <p className="auth-card__subheading">{t('auth.login.subtitle')}</p>

      {idleReason && !error && (
        <div className="alert alert--info">
          {t('auth.login.errorGeneric')}
        </div>
      )}
      {error && <div className="alert alert--error">{error}</div>}

      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label className="form-label" htmlFor="email">{t('common.email')}</label>
          <input
            id="email"
            name="email"
            type="email"
            className="form-input"
            value={form.email}
            onChange={handleChange}
            required
            autoFocus
            dir="ltr"
          />
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="password">{t('common.password')}</label>
          <PasswordInput
            id="password"
            name="password"
            value={form.password}
            onChange={handleChange}
            required
          />
        </div>

        <div className="auth-extras">
          <span />
          <Link to="/forgot-password" className="btn btn--ghost">
            {t('auth.login.forgotPassword')}
          </Link>
        </div>

        <button type="submit" className="btn btn--primary" disabled={loading}>
          {loading ? <span className="spinner" /> : t('auth.login.submit')}
        </button>
      </form>

      <p className="auth-footer">
        {t('auth.login.noAccount')}{' '}
        <Link to="/register">{t('auth.login.createOne')}</Link>
      </p>
    </AuthLayout>
  );
}
