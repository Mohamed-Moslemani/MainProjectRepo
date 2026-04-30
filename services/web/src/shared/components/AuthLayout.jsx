import '@shared/styles/auth.css';
import flagImg from '@shared/assets/Figure_1.png';
import L from '@shared/components/L';

export default function AuthLayout({ children }) {
  return (
    <div className="auth-layout">
      <div className="auth-panel">
        <div className="auth-panel__bg-circle auth-panel__bg-circle--1" />
        <div className="auth-panel__bg-circle auth-panel__bg-circle--2" />
        <div className="auth-panel__bg-circle auth-panel__bg-circle--3" />
        <img src={flagImg} alt="Lebanese flag" className="auth-panel__flag" />
        <h1 className="auth-panel__title">DocFlow Lebanon</h1>
        <div className="auth-panel__divider" />
        <p className="auth-panel__subtitle">
          <L>{{ ar: <>بوابتك للخدمات الحكومية الإلكترونية</>, en: <>Your gateway to hassle-free government document services</> }}</L>
        </p>
        <p className="auth-panel__tagline">
          <L>{{ ar: <>قدّم إلكترونياً، تابع طلبك، استلم بزيارة واحدة</>, en: <>Apply online, track progress, pick up once</> }}</L>
        </p>
      </div>
      <div className="auth-content">
        <div className="auth-card">
          <div className="auth-card__logo">
            <img src={flagImg} alt="" className="auth-card__logo-flag" />
            <span className="auth-card__logo-text">Doc<span>Flow</span></span>
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}
