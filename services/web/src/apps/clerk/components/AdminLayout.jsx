import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '@shared/context/useAuth';
import flagImg from '@shared/assets/Figure_1.png';
import '@shared/styles/admin.css';
import L from '@shared/components/L';
import { useL } from '@shared/hooks/useL';

const ROLE_LABELS = {
  admin: { ar: 'مسؤول', en: 'Admin' },
  clerk: { ar: 'موظف', en: 'Clerk' },
  mukhtar: { ar: 'مختار', en: 'Mukhtar' },
};

export default function AdminLayout() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pick } = useL();
  const roleLabel = user?.role ? (ROLE_LABELS[user.role] || { ar: user.role, en: user.role }) : null;

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="admin">
      <aside className="admin-sidebar">
        <div className="admin-sidebar__brand">
          <img src={flagImg} alt="" className="admin-sidebar__flag" />
          <div>
            <span className="admin-sidebar__title">DocFlow</span>
            <span className="admin-sidebar__badge">
              <L ar="إدارة" en="Admin" />
            </span>
          </div>
        </div>

        <nav className="admin-sidebar__nav">
          <NavLink to="/admin" end className="admin-nav-item">
            <svg className="admin-nav-item__icon" viewBox="0 0 20 20" fill="currentColor">
              <path d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zm0 6a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1v-2zm0 6a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1v-2z"/>
            </svg>
            <L ar="لوحة التحكم" en="Dashboard" />
          </NavLink>
          <NavLink to="/admin/review" className="admin-nav-item">
            <svg className="admin-nav-item__icon" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd"/>
            </svg>
            <L ar="المراجعة" en="Review" />
          </NavLink>
          <NavLink to="/admin/cases" className="admin-nav-item">
            <svg className="admin-nav-item__icon" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd"/>
            </svg>
            <L ar="الطلبات" en="Cases" />
          </NavLink>
          <NavLink to="/admin/audit-logs" className="admin-nav-item">
            <svg className="admin-nav-item__icon" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd"/>
            </svg>
            <L ar="سجل التدقيق" en="Audit Logs" />
          </NavLink>
          <NavLink to="/admin/stripe-events" className="admin-nav-item">
            <svg className="admin-nav-item__icon" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4 4a2 2 0 00-2 2v1h16V6a2 2 0 00-2-2H4zm14 5H2v5a2 2 0 002 2h12a2 2 0 002-2V9zM4 13a1 1 0 011-1h1a1 1 0 110 2H5a1 1 0 01-1-1zm5-1a1 1 0 100 2h1a1 1 0 100-2H9z" clipRule="evenodd"/>
            </svg>
            <L ar="أحداث سترايب" en="Stripe Events" />
          </NavLink>
        </nav>

        <div className="admin-sidebar__footer">
          <div className="admin-sidebar__user">
            <div className="admin-sidebar__avatar">
              {user?.role?.[0]?.toUpperCase() || 'A'}
            </div>
            <div className="admin-sidebar__user-info">
              <span className="admin-sidebar__role">{roleLabel ? pick(roleLabel) : ''}</span>
            </div>
          </div>
          <button className="admin-sidebar__logout" onClick={handleLogout}>
            {t('common.signOut')}
          </button>
        </div>
      </aside>

      <main className="admin-main">
        <Outlet />
      </main>
    </div>
  );
}
