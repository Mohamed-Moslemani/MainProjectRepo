// i18next setup. One init for the whole SPA.
//
// Storage convention for translation keys:
//
//   <area>.<page>.<element>            // page-scoped strings
//   common.<thing>                     // reused across pages
//   status.<case_status>               // backend status enum
//   service.<service_type>             // backend service enum
//   sect.<id>                          // 18 Lebanese sects
//   doc.<document_type>                // backend doc-type enum
//   reason.<renewal_reason>            // GDGS renewal reasons
//
// The app is Arabic-only. The locale is hard-locked to `ar` at init —
// no detector, no switcher, no English bundle. The `<L ar en />` and
// `pick({ ar, en })` shims still work; they always resolve to `ar`
// because i18n.resolvedLanguage is `ar`.

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import ar from './ar.json';

// Clear any previously-persisted English preference so returning users
// don't get stuck after we removed the toggle.
try {
  if (typeof window !== 'undefined' && window.localStorage) {
    window.localStorage.removeItem('docflow-lang');
  }
} catch {
  // localStorage can throw in private mode — safe to ignore.
}

i18n
  .use(initReactI18next)
  .init({
    resources: {
      ar: { translation: ar },
    },
    lng: 'ar',
    fallbackLng: 'ar',
    supportedLngs: ['ar'],
    interpolation: { escapeValue: false }, // React handles XSS
  });

document.documentElement.setAttribute('dir', 'rtl');
document.documentElement.setAttribute('lang', 'ar');

export default i18n;
