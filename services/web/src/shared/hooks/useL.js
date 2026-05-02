import { useTranslation } from 'react-i18next';

// Hook for places that need the resolved string at render time —
// option labels, button text inside a ternary, aria-labels,
// document.title, toast messages. Returns a `pick({ ar, en })`
// helper plus the active lang so callers can branch directly when
// it reads cleaner than calling pick.
//
// Lives in its own file (not next to <L />) because Vite's react-refresh
// rule "react-refresh/only-export-components" only allows component
// exports from files that contain components. Sharing a hook from L.jsx
// breaks fast-refresh.
export function useL() {
  const { i18n } = useTranslation();
  const lang = i18n.resolvedLanguage === 'en' ? 'en' : 'ar';
  const pick = (pair) => (pair?.[lang] ?? pair?.ar ?? pair?.en ?? '');
  return { lang, pick, isAr: lang === 'ar' };
}
