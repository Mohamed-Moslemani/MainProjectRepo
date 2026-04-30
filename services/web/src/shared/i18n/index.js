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
// Why these enum buckets exist instead of being scattered: the
// backend already speaks these enums, and they appear in many
// places (Dashboard, CaseDetail, AdminCases, emails). Centralising
// keeps one source of truth per enum and avoids "ID Card" /
// "ID card" / "National ID" drift.
//
// Direction:
//   Arabic is RTL, English is LTR. We toggle <html dir="..."> on
//   language change so individual pages don't have to scatter
//   dir="rtl" everywhere.

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import en from './en.json';
import ar from './ar.json';

const STORAGE_KEY = 'docflow-lang';

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      ar: { translation: ar },
    },
    fallbackLng: 'ar',
    supportedLngs: ['ar', 'en'],
    interpolation: { escapeValue: false }, // React handles XSS
    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: STORAGE_KEY,
      caches: ['localStorage'],
    },
  });

const applyDirection = (lng) => {
  const dir = lng === 'ar' ? 'rtl' : 'ltr';
  document.documentElement.setAttribute('dir', dir);
  document.documentElement.setAttribute('lang', lng);
};

applyDirection(i18n.resolvedLanguage || 'ar');
i18n.on('languageChanged', applyDirection);

export default i18n;
