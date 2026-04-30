import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '@shared/context/useAuth';
import LanguageSwitcher from '@shared/components/LanguageSwitcher';
import flagImg from '@shared/assets/Figure_1.png';
import '@shared/styles/admin.css';

export default function MukhtarLayout() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="admin" dir="rtl">
      <aside className="admin-sidebar">
        <div className="admin-sidebar__brand">
          <img src={flagImg} alt="" className="admin-sidebar__flag" />
          <div>
            <span className="admin-sidebar__title">DocFlow</span>
            <span className="admin-sidebar__badge">
              <span className="ar">مختار</span>
              <span className="en" style={{ fontSize: '0.6rem' }}>Mukhtar</span>
            </span>
          </div>
        </div>

        <nav className="admin-sidebar__nav">
          <NavLink to="/mukhtar" end className="admin-nav-item">
            <svg className="admin-nav-item__icon" viewBox="0 0 20 20" fill="currentColor">
              <path d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zm0 6a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1v-2zm0 6a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1v-2z"/>
            </svg>
            <span className="ar">لوحة التحكم</span>
            <span className="en">Dashboard</span>
          </NavLink>
          <NavLink to="/mukhtar/cases" className="admin-nav-item">
            <svg className="admin-nav-item__icon" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd"/>
            </svg>
            <span className="ar">الطلبات</span>
            <span className="en">Cases</span>
          </NavLink>
        </nav>

        <div className="admin-sidebar__footer">
          <div className="admin-sidebar__user">
            <div className="admin-sidebar__avatar">M</div>
            <div className="admin-sidebar__user-info">
              <span className="admin-sidebar__role">{user?.full_name || 'Mukhtar'}</span>
            </div>
          </div>
          <LanguageSwitcher />
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