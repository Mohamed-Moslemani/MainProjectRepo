import { useState, useEffect } from 'react';
import { useAuth } from '../context/useAuth';
import { useNavigate } from 'react-router-dom';
import { casesApi } from '../api/cases';
import flagImg from '../assets/Figure_1.png';
import '../styles/dashboard.css';

const SERVICE_TYPES = [
  { value: 'id_new', ar: 'بطاقة هوية جديدة', en: 'New ID Card' },
  { value: 'id_renewal', ar: 'تجديد بطاقة الهوية', en: 'ID Card Renewal' },
  { value: 'passport_new', ar: 'جواز سفر جديد', en: 'New Passport' },
  { value: 'passport_renewal', ar: 'تجديد جواز السفر', en: 'Passport Renewal' },
];

const STATUS_MAP = {
  draft: { ar: 'مسودة', en: 'Draft', color: 'gray' },
  submitted: { ar: 'قيد المراجعة', en: 'Submitted', color: 'blue' },
  validated: { ar: 'تم التحقق', en: 'Validated', color: 'blue' },
  risk_evaluated: { ar: 'تم تقييم المخاطر', en: 'Risk Evaluated', color: 'orange' },
  approved: { ar: 'موافق عليه', en: 'Approved', color: 'green' },
  rejected: { ar: 'مرفوض', en: 'Rejected', color: 'red' },
  need_info: { ar: 'بحاجة لمعلومات', en: 'Needs Info', color: 'orange' },
  in_production: { ar: 'قيد الإنتاج', en: 'In Production', color: 'blue' },
  ready_for_pickup: { ar: 'جاهز للاستلام', en: 'Ready for Pickup', color: 'green' },
  closed: { ar: 'مغلق', en: 'Closed', color: 'gray' },
};

export default function Dashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showNewCase, setShowNewCase] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    loadCases();
  }, []);

  const loadCases = async () => {
    try {
      const { data } = await casesApi.list();
      setCases(data.cases || []);
    } catch {
      setError('فشل في تحميل الطلبات');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateCase = async (serviceType) => {
    setCreating(true);
    setError('');
    try {
      const { data } = await casesApi.create(serviceType);
      navigate(`/case/${data.id}`);
    } catch (err) {
      setError(err.response?.data?.detail || 'فشل في إنشاء الطلب');
    } finally {
      setCreating(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const getServiceLabel = (type) => {
    const svc = SERVICE_TYPES.find((s) => s.value === type);
    return svc || { ar: type, en: type };
  };

  const getStatus = (status) => {
    return STATUS_MAP[status] || { ar: status, en: status, color: 'gray' };
  };

  const activeCases = cases.filter((c) => !['closed', 'rejected'].includes(c.status));
  const pastCases = cases.filter((c) => ['closed', 'rejected'].includes(c.status));

  return (
    <div className="dashboard" dir="rtl">
      <header className="dashboard-header">
        <div className="dashboard-header__brand">
          <img src={flagImg} alt="" className="dashboard-header__flag" />
          <span className="dashboard-header__title">DocFlow <span>Lebanon</span></span>
        </div>
        <div className="dashboard-header__actions">
          <span className="dashboard-header__role">{user?.role}</span>
          <button className="btn btn--ghost" onClick={handleLogout}>
            <span className="ar">خروج</span>
            <span className="en">Sign Out</span>
          </button>
        </div>
      </header>

      <main className="dashboard-main">
        <div className="dashboard-welcome">
          <h1>
            <span className="ar">مرحباً بك في دوك فلو</span>
            <span className="en">Welcome to DocFlow</span>
          </h1>
          <p className="dashboard-subtitle">
            <span className="ar">إدارة طلبات الهوية وجواز السفر الخاصة بك</span>
            <span className="en">Manage your ID and passport applications</span>
          </p>
        </div>

        {error && <div className="alert alert--error">{error}</div>}

        {/* Quick Actions */}
        <div className="dashboard-cards">
          <div className="dashboard-card" onClick={() => setShowNewCase(true)}>
            <div className="dashboard-card__icon dashboard-card__icon--green">+</div>
            <h3 className="ar">طلب جديد</h3>
            <p className="en">New Application</p>
          </div>
          <div className="dashboard-card" onClick={() => document.getElementById('active-section')?.scrollIntoView({ behavior: 'smooth' })}>
            <div className="dashboard-card__icon dashboard-card__icon--red">&#8635;</div>
            <h3 className="ar">تتبع الطلبات</h3>
            <p className="en">Track Applications</p>
          </div>
          <div className="dashboard-card" onClick={() => document.getElementById('past-section')?.scrollIntoView({ behavior: 'smooth' })}>
            <div className="dashboard-card__icon dashboard-card__icon--gray">&#9776;</div>
            <h3 className="ar">السجل</h3>
            <p className="en">History</p>
          </div>
        </div>

        {/* New Case Modal */}
        {showNewCase && (
          <div className="modal-overlay" onClick={() => setShowNewCase(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal__header">
                <h2>
                  <span className="ar">اختر نوع الخدمة</span>
                  <span className="en">Select Service Type</span>
                </h2>
                <button className="modal__close" onClick={() => setShowNewCase(false)}>&times;</button>
              </div>
              <div className="modal__body">
                <div className="service-grid">
                  {SERVICE_TYPES.map((svc) => (
                    <button
                      key={svc.value}
                      className="service-option"
                      disabled={creating}
                      onClick={() => handleCreateCase(svc.value)}
                    >
                      <span className="service-option__icon">
                        {svc.value.includes('passport') ? '📘' : '🪪'}
                      </span>
                      <span className="service-option__label ar">{svc.ar}</span>
                      <span className="service-option__label en">{svc.en}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Active Cases */}
        <section id="active-section" className="dashboard-section">
          <h2>
            <span className="ar">الطلبات النشطة</span>
            <span className="en">Active Applications</span>
          </h2>
          {loading ? (
            <div className="loading-spinner" />
          ) : activeCases.length === 0 ? (
            <div className="empty-state">
              <p className="ar">لا توجد طلبات نشطة</p>
              <p className="en">No active applications</p>
            </div>
          ) : (
            <div className="case-list">
              {activeCases.map((c) => {
                const svc = getServiceLabel(c.service_type);
                const st = getStatus(c.status);
                return (
                  <div key={c.id} className="case-card" onClick={() => navigate(`/case/${c.id}`)}>
                    <div className="case-card__top">
                      <div className="case-card__type">
                        <span className="ar">{svc.ar}</span>
                        <span className="en">{svc.en}</span>
                      </div>
                      <span className={`status-badge status-badge--${st.color}`}>
                        <span className="ar">{st.ar}</span>
                        <span className="en">{st.en}</span>
                      </span>
                    </div>
                    <div className="case-card__bottom">
                      <span className="case-card__tracking">
                        #{c.tracking_id}
                      </span>
                      <span className="case-card__date">
                        {new Date(c.created_at).toLocaleDateString('ar-LB')}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Past Cases */}
        <section id="past-section" className="dashboard-section">
          <h2>
            <span className="ar">الطلبات السابقة</span>
            <span className="en">Past Applications</span>
          </h2>
          {loading ? (
            <div className="loading-spinner" />
          ) : pastCases.length === 0 ? (
            <div className="empty-state">
              <p className="ar">لا توجد طلبات سابقة</p>
              <p className="en">No past applications</p>
            </div>
          ) : (
            <div className="case-list">
              {pastCases.map((c) => {
                const svc = getServiceLabel(c.service_type);
                const st = getStatus(c.status);
                return (
                  <div key={c.id} className="case-card case-card--past" onClick={() => navigate(`/case/${c.id}`)}>
                    <div className="case-card__top">
                      <div className="case-card__type">
                        <span className="ar">{svc.ar}</span>
                        <span className="en">{svc.en}</span>
                      </div>
                      <span className={`status-badge status-badge--${st.color}`}>
                        <span className="ar">{st.ar}</span>
                        <span className="en">{st.en}</span>
                      </span>
                    </div>
                    <div className="case-card__bottom">
                      <span className="case-card__tracking">#{c.tracking_id}</span>
                      <span className="case-card__date">
                        {new Date(c.created_at).toLocaleDateString('ar-LB')}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
