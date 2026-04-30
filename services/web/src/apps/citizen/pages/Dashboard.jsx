import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '@shared/context/useAuth';
import { useNavigate, Link } from 'react-router-dom';
import { casesApi } from '@shared/api/cases';
import { useToast } from '@shared/context/useToast';
import { SkeletonCard } from '@shared/components/Skeleton';
import LanguageSwitcher from '@shared/components/LanguageSwitcher';
import flagImg from '@shared/assets/Figure_1.png';
import '@shared/styles/dashboard.css';

// Status enum the backend speaks. Both "color" (visual class) and
// the i18n key live here so the dashboard never invents copy.
const STATUS_COLOR = {
  draft: 'gray',
  submitted: 'blue',
  validated: 'blue',
  risk_evaluated: 'orange',
  approved: 'green',
  rejected: 'red',
  need_info: 'orange',
  in_production: 'blue',
  ready_for_pickup: 'green',
  closed: 'gray',
  payment_pending: 'orange',
  payment_failed: 'red',
  biometric_appointment_required: 'orange',
  pending_mukhtar: 'orange',
};

const SERVICE_TYPES = ['id_new', 'id_renewal', 'passport_new', 'passport_renewal'];

export default function Dashboard() {
  const { t, i18n } = useTranslation();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showNewCase, setShowNewCase] = useState(false);
  const [creating, setCreating] = useState(false);

  // Errors are surfaced via the global toast stack now; the kept
  // signature avoids churning every call site.
  const setError = (msg) => msg && toast.error(msg);

  useEffect(() => {
    loadCases();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadCases = async () => {
    try {
      const { data } = await casesApi.list();
      setCases(data.cases || []);
    } catch {
      setError(t('common.loading'));
    } finally {
      setLoading(false);
    }
  };

  const handleCreateCase = async (serviceType) => {
    setCreating(true);
    try {
      const { data } = await casesApi.create(serviceType);
      navigate(`/case/${data.id}`);
    } catch (err) {
      setError(err.response?.data?.detail || t('common.retry'));
    } finally {
      setCreating(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const dateLocale = i18n.resolvedLanguage === 'ar' ? 'ar-LB' : 'en-GB';
  const activeCases = cases.filter((c) => !['closed', 'rejected'].includes(c.status));
  const pastCases = cases.filter((c) => ['closed', 'rejected'].includes(c.status));

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div className="dashboard-header__brand">
          <img src={flagImg} alt="" className="dashboard-header__flag" />
          <span className="dashboard-header__title">{t('common.appName')}</span>
        </div>
        <div className="dashboard-header__actions">
          <span className="dashboard-header__role">{user?.role}</span>
          <LanguageSwitcher />
          <Link to="/help" className="btn btn--ghost btn--sm">
            {t('common.help')}
          </Link>
          <Link to="/account" className="btn btn--ghost btn--sm">
            {t('common.account')}
          </Link>
          <button className="btn btn--ghost" onClick={handleLogout}>
            {t('common.signOut')}
          </button>
        </div>
      </header>

      <main className="dashboard-main">
        <div className="dashboard-welcome">
          <h1>{t('dashboard.welcome')}</h1>
          <p className="dashboard-subtitle">{t('dashboard.subtitle')}</p>
        </div>

        <div className="dashboard-cards">
          <div className="dashboard-card" onClick={() => setShowNewCase(true)}>
            <div className="dashboard-card__icon dashboard-card__icon--green">+</div>
            <h3>{t('dashboard.newApplication')}</h3>
          </div>
          <div className="dashboard-card" onClick={() => document.getElementById('active-section')?.scrollIntoView({ behavior: 'smooth' })}>
            <div className="dashboard-card__icon dashboard-card__icon--red">&#8635;</div>
            <h3>{t('dashboard.trackApplications')}</h3>
          </div>
          <div className="dashboard-card" onClick={() => document.getElementById('past-section')?.scrollIntoView({ behavior: 'smooth' })}>
            <div className="dashboard-card__icon dashboard-card__icon--gray">&#9776;</div>
            <h3>{t('dashboard.history')}</h3>
          </div>
        </div>

        {showNewCase && (
          <div className="modal-overlay" onClick={() => setShowNewCase(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal__header">
                <h2>{t('dashboard.selectService')}</h2>
                <button className="modal__close" onClick={() => setShowNewCase(false)}>&times;</button>
              </div>
              <div className="modal__body">
                <div className="service-grid">
                  {SERVICE_TYPES.map((sv) => (
                    <button
                      key={sv}
                      className="service-option"
                      disabled={creating}
                      onClick={() => handleCreateCase(sv)}
                    >
                      <span className="service-option__icon">
                        {sv.includes('passport') ? '📘' : '🪪'}
                      </span>
                      <span className="service-option__label">{t(`service.${sv}`)}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        <section id="active-section" className="dashboard-section">
          <h2>{t('dashboard.active')}</h2>
          {loading ? (
            <SkeletonCard rows={3} />
          ) : activeCases.length === 0 ? (
            <div className="empty-state"><p>{t('dashboard.noActive')}</p></div>
          ) : (
            <div className="case-list">
              {activeCases.map((c) => (
                <div key={c.id} className="case-card" onClick={() => navigate(`/case/${c.id}`)}>
                  <div className="case-card__top">
                    <div className="case-card__type">{t(`service.${c.service_type}`, c.service_type)}</div>
                    <span className={`status-badge status-badge--${STATUS_COLOR[c.status] || 'gray'}`}>
                      {t(`status.${c.status}`, c.status)}
                    </span>
                  </div>
                  <div className="case-card__bottom">
                    <span className="case-card__tracking">#{c.tracking_id}</span>
                    <span className="case-card__date">
                      {new Date(c.created_at).toLocaleDateString(dateLocale)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section id="past-section" className="dashboard-section">
          <h2>{t('dashboard.past')}</h2>
          {loading ? (
            <SkeletonCard rows={3} />
          ) : pastCases.length === 0 ? (
            <div className="empty-state"><p>{t('dashboard.noPast')}</p></div>
          ) : (
            <div className="case-list">
              {pastCases.map((c) => (
                <div key={c.id} className="case-card case-card--past" onClick={() => navigate(`/case/${c.id}`)}>
                  <div className="case-card__top">
                    <div className="case-card__type">{t(`service.${c.service_type}`, c.service_type)}</div>
                    <span className={`status-badge status-badge--${STATUS_COLOR[c.status] || 'gray'}`}>
                      {t(`status.${c.status}`, c.status)}
                    </span>
                  </div>
                  <div className="case-card__bottom">
                    <span className="case-card__tracking">#{c.tracking_id}</span>
                    <span className="case-card__date">
                      {new Date(c.created_at).toLocaleDateString(dateLocale)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
