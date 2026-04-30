import { useTranslation } from 'react-i18next';

// Minimal language toggle. Two clicks beats a dropdown when there
// are only two locales. Persisted via i18next-browser-languagedetector
// (localStorage), so the choice survives reloads.
//
// Mount anywhere — the parent layout's RTL/LTR direction follows
// the <html dir="..."> attribute the i18n init flips on change.
export default function LanguageSwitcher({ className = '' }) {
  const { i18n } = useTranslation();
  const current = i18n.resolvedLanguage || 'ar';
  const next = current === 'ar' ? 'en' : 'ar';
  const label = next === 'ar' ? 'العربية' : 'English';

  return (
    <button
      type="button"
      className={`btn btn--ghost btn--sm ${className}`}
      onClick={() => i18n.changeLanguage(next)}
      aria-label={`Switch language to ${label}`}
    >
      {label}
    </button>
  );
}
