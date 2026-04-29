# `services/web/src` — layout

```
src/
├─ App.jsx, main.jsx                    Single SPA entry; one router, one auth context.
├─ apps/
│  ├─ citizen/                          Routes the citizen sees post-login.
│  │   └─ pages/                        Dashboard, CaseDetail, BookAppointment, …
│  ├─ clerk/                            /admin routes (admin + clerk roles).
│  │   ├─ pages/                        AdminDashboard, AdminReviewQueue, AdminCases, …
│  │   └─ components/                   AdminLayout (sidebar + outlet for /admin/*).
│  └─ mukhtar/                          /mukhtar routes (mukhtar role).
│      ├─ pages/                        MukhtarDashboard, MukhtarCases.
│      └─ components/                   MukhtarLayout.
└─ shared/                              Cross-role infrastructure.
   ├─ api/                              Single axios client + per-resource modules.
   ├─ assets/                           Logo, icons.
   ├─ components/                       AuthImage, ProtectedRoute, RoleRoute,
   │                                    UploadPreview, Skeleton, etc.
   ├─ constants/, hooks/, utils/        Cross-cutting helpers.
   ├─ context/                          AuthContext, ToastContext.
   ├─ pages/
   │   ├─ auth/                         Login, Register, ForgotPassword, ResetPassword,
   │   │                                VerifyEmail (pre-role).
   │   └─ NotFound.jsx                  404 fallback.
   └─ styles/                           Global CSS.
```

## Path aliases

`vite.config.js` + `jsconfig.json` set up four aliases — use them
instead of `../../shared/...`:

| Alias       | Resolves to              |
| ----------- | ------------------------ |
| `@shared/*` | `src/shared/*`           |
| `@citizen/*`| `src/apps/citizen/*`     |
| `@clerk/*`  | `src/apps/clerk/*`       |
| `@mukhtar/*`| `src/apps/mukhtar/*`     |

Example:

```js
import { casesApi }   from '@shared/api/cases';
import RoleRoute      from '@shared/components/RoleRoute';
import AdminLayout    from '@clerk/components/AdminLayout';
```

## Dependency rule (intentional)

- `apps/<role>/*` may import from `@shared/*` and from itself.
- `apps/<role>/*` should **not** import from another role's `apps/`
  folder — if you find yourself wanting to, the thing you need is
  shared infrastructure and belongs in `shared/`.
- `shared/*` may not import from any `apps/<role>/*` — same reason.

There's no lint rule enforcing this yet; the boundary is by
convention. If it gets violated repeatedly, add an
`eslint-plugin-boundaries` rule.

## Why one app, not three

We considered three separate Vite projects (citizen / clerk /
mukhtar) and decided against it: the three views share a single
backend, a single auth token, a single design system, and most
shared components. Three builds + three deploys + three nginx
configs + cross-origin cookies for SSO would have been all cost
and no benefit. The folder-level split here gives the same
ownership boundaries without the build-time cost.
