import { Link } from 'react-router-dom';
import flagImg from '../assets/Figure_1.png';
import '../styles/dashboard.css';

export default function NotFound() {
  return (
    <div className="dashboard" dir="rtl" style={{ minHeight: '100vh', background: '#fafbfc' }}>
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
            <span className="ar">الصفحة غير موجودة</span>
          </h1>
          <p style={{ margin: '0 0 4px', fontSize: '1rem', color: '#9ca3af' }}>
            <span className="en">Page Not Found</span>
          </p>

          <p style={{ margin: '24px 0', color: '#6b7280', lineHeight: 1.6 }}>
            <span className="ar">عذراً، الصفحة التي تبحث عنها غير موجودة أو تم نقلها.</span>
            <br />
            <span className="en" style={{ fontSize: '0.85rem', color: '#9ca3af' }}>
              Sorry, the page you're looking for doesn't exist or has been moved.
            </span>
          </p>

          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 32 }}>
            <Link to="/dashboard" className="btn btn--primary">
              <span className="ar">لوحة التحكم</span>
              <span className="en">Dashboard</span>
            </Link>
            <Link to="/login" className="btn btn--outline">
              <span className="ar">تسجيل الدخول</span>
              <span className="en">Sign In</span>
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}