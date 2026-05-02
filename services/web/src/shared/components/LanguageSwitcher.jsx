import { useTranslation } from 'react-i18next';

// Two variants of the same control:
//
//   <LanguageSwitcher />                ← floating pill, fixed top
//                                          corner, always visible across
//                                          every route. Mounted once in
//                                          App.jsx.
//   <LanguageSwitcher inline />         ← inline button for sidebars /
//                                          forms; styled by the host.
//
// Persistence is in i18next-browser-languagedetector (localStorage),
// so the choice survives reload. The i18n init flips <html dir> on
// change, so RTL/LTR comes for free.
export default function LanguageSwitcher({ inline = false, className = '' }) {
  const { i18n } = useTranslation();
  const current = i18n.resolvedLanguage || 'ar';
  const next = current === 'ar' ? 'en' : 'ar';
  const label = next === 'ar' ? 'العربية' : 'English';
  const aria = current === 'ar'
    ? `التبديل إلى ${label}`
    : `Switch language to ${label}`;

  if (inline) {
    return (
      <button
        type="button"
        className={`btn btn--ghost btn--sm ${className}`}
        onClick={() => i18n.changeLanguage(next)}
        aria-label={aria}
      >
        {label}
      </button>
    );
  }

  // Floating variant. Position is direction-aware: top-right in LTR
  // (English), top-left in RTL (Arabic) so the button doesn't crash
  // into either layout's natural reading flow.
  const isRTL = current === 'ar';
  const style = {
    position: 'fixed',
    top: '0.75rem',
    [isRTL ? 'left' : 'right']: '0.75rem',
    zIndex: 9999,
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.4rem',
    padding: '0.5rem 0.9rem',
    background: '#ffffff',
    color: '#111827',
    border: '1px solid #d1d5db',
    borderRadius: '999px',
    fontSize: '0.85rem',
    fontWeight: 600,
    boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
    cursor: 'pointer',
    direction: 'ltr', // keep label glyph order stable regardless of page
  };

  return (
    <button
      type="button"
      style={style}
      onClick={() => i18n.changeLanguage(next)}
      aria-label={aria}
      title={aria}
    >
      <span aria-hidden="true">🌐</span>
      <span>{label}</span>
    </button>
  );
}
