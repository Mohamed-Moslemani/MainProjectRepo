import { useTranslation } from 'react-i18next';

// Inline locale picker. The migration shim used by pages that
// haven't been moved to the t() / JSON catalogue yet — replaces the
// old paired <span className="ar"/className="en"> pattern that only
// worked because CSS hid the inactive language.
//
// Two compatible call shapes:
//   <L ar="hello" en="مرحبا" />                  inline strings
//   <L>{{ ar: <strong>X</strong>, en: <em>Y</em> }}</L>   when the
//                                                contents need JSX
//
// Prefer t('key') with the catalogue in `shared/i18n/{en,ar}.json`
// for new code; this is the migration shim, not the destination.
export default function L(props) {
  const { i18n } = useTranslation();
  const lang = i18n.resolvedLanguage === 'en' ? 'en' : 'ar';
  if (props.children && typeof props.children === 'object' &&
      ('ar' in props.children || 'en' in props.children)) {
    return props.children[lang] ?? props.children.ar ?? props.children.en ?? null;
  }
  return props[lang] ?? props.ar ?? props.en ?? null;
}

// Hook for places that need the resolved string at render time —
// option labels, button text inside a ternary, aria-labels,
// document.title, toast messages. Returns a `pick({ ar, en })`
// helper plus the active lang so callers can branch directly when
// it reads cleaner than calling pick.
export function useL() {
  const { i18n } = useTranslation();
  const lang = i18n.resolvedLanguage === 'en' ? 'en' : 'ar';
  const pick = (pair) => (pair?.[lang] ?? pair?.ar ?? pair?.en ?? '');
  return { lang, pick, isAr: lang === 'ar' };
}
