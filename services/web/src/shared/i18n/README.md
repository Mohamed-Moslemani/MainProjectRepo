# `shared/i18n` — Arabic-only catalogue

Single i18next init locked to `ar`. Loaded once from
[`main.jsx`](../../main.jsx); pages call `useTranslation()` and use
`t('key.path')`.

The English bundle, language detector, and `<LanguageSwitcher />` were
removed — the SPA is Arabic-only by product decision. Translation keys
still live under namespaces (below) so a second locale could be added
back later by re-introducing a JSON file and re-enabling the detector.

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

The `status` and `service` namespaces deliberately use the backend's
exact enum strings as keys, so calling `t('status.' + case.status)`
always resolves and you don't have to maintain a separate JS map.

## Legacy shim: `<L ar="..." en="..." />` and `pick({ ar, en })`

Some pages still use the migration shim that takes both an `ar` and
`en` value. With the locale locked to `ar`, both helpers always
return the `ar` branch. Newer code should prefer `t('key')` against
[`ar.json`](./ar.json).

## Direction (RTL)

[`index.js`](./index.js) hard-sets `<html dir="rtl" lang="ar">` at
init. Form inputs that must accept Latin text (email, phone,
tracking IDs) explicitly set `dir="ltr"` on the `<input>`.
