# AMS Customer Portal (SPA)

The customer-facing front end. A separate Vite project from the staff
dashboard (`web/`) because it has a different audience, sign-in flow and
branding. Both are built into the same Docker image; Django serves this
one on the portal hostname (`PORTAL_HOST`).

- API: `/api/portal/*` only (see `api/portal/`).
- Sign-in: email + password, then a mandatory authenticator-app code.
  First sign-in walks new password → MFA enrolment (QR code).
- Tokens live in `sessionStorage` and die with the tab.

```bash
npm install
npm run dev                      # http://localhost:5174, API proxied to localhost:8000
PORTAL_API_TARGET=https://portal.ams-dev.getshaking.live npm run dev   # against the dev stack
npm run build                    # tsc + vite build → dist/
```
