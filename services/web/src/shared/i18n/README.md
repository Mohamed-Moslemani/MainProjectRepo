# `shared/i18n` — internationalisation

Single i18next init, two locales (`ar`, `en`). Loaded once from
[`main.jsx`](../../main.jsx); pages call `useTranslation()` and use
`t('key.path')`.

## Why this exists

Earlier the SPA shipped both languages on every page via paired
`<span className="ar">` / `<span className="en">` elements styled
to show only the active language via CSS. That worked but:

- couldn't be extracted to translators (380+ inline strings)
- doubled DOM size on every page
- wouldn't grow to a third locale
- forced "switch language" to be a CSS-class flip, not a real i18n

This module replaces that pattern with the standard react-i18next
flow: keys live in [`en.json`](./en.json) / [`ar.json`](./ar.json),
the user toggles via [`LanguageSwitcher`](../components/LanguageSwitcher.jsx),
the choice persists in `localStorage`, and `<html dir>` flips to
match.

## Key namespacing

```
common.*       reusable across the app (signIn, save, fullName, …)
auth.<page>.*  Login / Register / Reset / Verify
landing.*      "/" public landing
dashboard.*    /dashboard
case.*         /case/:id
appointment.*  /case/:id/appointment
account.*      /account
status.<enum>  case_status enum from the backend
service.<enum> service_type enum from the backend
```

The `status` and `service` namespaces deliberately use the
backend's exact enum strings as keys, so calling `t('status.' +
case.status)` always resolves and you don't have to maintain a
separate JS map.

## Migration recipe

For any page still on the bilingual `<span className="ar/en">`
pattern, the conversion is mechanical:

```jsx
// before
<span className="ar">تسجيل الدخول</span>
<span className="en">Sign In</span>

// after
import { useTranslation } from 'react-i18next';
const { t } = useTranslation();

{t('common.signIn')}
```

For backend enums, prefer the dotted form so you don't reinvent
the map:

```jsx
{t(`status.${c.status}`)}
{t(`service.${c.service_type}`)}
```

When adding new strings:
1. Add to `en.json` first (the file is your source of truth).
2. Mirror in `ar.json` — never let a key exist in only one locale.
3. Group under the smallest namespace that fits; if it's used in
   2+ pages, lift to `common.*`.

## Direction (RTL)

[`index.js`](./index.js) flips `<html dir="rtl">` for `ar` and
`dir="ltr"` for `en` on language change. Pages don't need to
declare `dir` themselves any more — and any leftover `dir="rtl"`
hardcoded on a page is now a bug, since switching to English
won't release it.
