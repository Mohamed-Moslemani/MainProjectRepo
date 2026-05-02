import { Link } from 'react-router-dom';
import flagImg from '@shared/assets/Figure_1.png';
import '@shared/styles/dashboard.css';
import L from '@shared/components/L';
import { useAuth } from '@shared/context/useAuth';

export default function NotFound() {
  const { user } = useAuth();
  // Send each role to their valid landing — admin/clerk to /admin,
  // mukhtar to /mukhtar, citizen to /dashboard, anonymous to /login.
  const home = !user ? '/login'
    : (user.role === 'admin' || user.role === 'clerk') ? '/admin'
    : user.role === 'mukhtar' ? '/mukhtar'
    : '/dashboard';
  const homeLabel = !user
    ? { ar: 'تسجيل الدخول', en: 'Sign In' }
    : (user.role === 'admin' || user.role === 'clerk') ? { ar: 'لوحة الإدارة', en: 'Admin' }
    : user.role === 'mukhtar' ? { ar: 'لوحة المختار', en: 'Mukhtar' }
    : { ar: 'لوحة التحكم', en: 'Dashboard' };
  return (
    <div className="dashboard" style={{ minHeight: '100vh', background: '#fafbfc' }}>
      <header className="dashboard-header">
        <div className="dashboard-header__brand">
          <img src={flagImg} alt="" className="dashboard-header__flag" />
          <span className="dashboard-header__title">DocFlow <span>Lebanon</span></span>
        </div>
      </header>

      <main className="dashboard-main" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center', maxWidth: 480, padding: '60px 24px' }}>
          <div style={{
            fontSize: '120px', fontWeight: 800, lineHeight: 1,
            background: 'linear-gradient(135deg, #006633, #00a651)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
            marginBottom: 8,
          }}>
            404
          </div>

          <h1 style={{ margin: '0 0 8px', fontSize: '1.5rem', color: '#1f2937' }}>
            <L ar="الصفحة غير موجودة" en="Page Not Found" />
          </h1>

          <p style={{ margin: '24px 0', color: '#6b7280', lineHeight: 1.6 }}>
            <L
              ar="عذراً، الصفحة التي تبحث عنها غير موجودة أو تم نقلها."
              en="Sorry, the page you're looking for doesn't exist or has been moved."
            />
          </p>

          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 32 }}>
            <Link to={home} className="btn btn--primary">
              <L ar={homeLabel.ar} en={homeLabel.en} />
            </Link>
            <Link to="/" className="btn btn--outline">
              <L ar="الصفحة الرئيسية" en="Home" />
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}