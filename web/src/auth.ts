/**
 * Auth token store: holds the Cognito id_token (used as the Bearer for API
 * calls) plus the refresh_token (used to silently mint a new id_token when
 * the old one expires).
 *
 * Storage is sessionStorage — cleared when the browser tab closes, but
 * persisted across page reloads within a session. Combined with refresh-
 * token rotation, users effectively never get logged out during active use:
 * the access token expires every 60 min, but request() catches the 401,
 * silently refreshes, and retries the original call before the user notices.
 *
 * Refresh-token expiry (30 days by default in our Cognito app client) is the
 * only thing that ends a session — and only if the tab is closed for that
 * long, since on next open we'd refresh on the first 401.
 */

const ID_KEY = 'ams-dashboard-id-token'
const REFRESH_KEY = 'ams-dashboard-refresh-token'

let cachedId: string | null = sessionStorage.getItem(ID_KEY)
let cachedRefresh: string | null = sessionStorage.getItem(REFRESH_KEY)

/** Dedupe concurrent refresh attempts — many API calls may 401 at once. */
let refreshInFlight: Promise<string | null> | null = null

export function getToken(): string | null {
  return cachedId
}

/** Update both tokens at login / after a challenge. Pass refreshToken=null
 *  to clear only the refresh token; omit it to leave the existing one alone
 *  (e.g. after a /api/auth/refresh, which doesn't return a new refresh). */
export function setTokens(idToken: string, refreshToken?: string | null): void {
  cachedId = idToken
  sessionStorage.setItem(ID_KEY, idToken)
  if (refreshToken !== undefined) {
    cachedRefresh = refreshToken
    if (refreshToken) {
      sessionStorage.setItem(REFRESH_KEY, refreshToken)
    } else {
      sessionStorage.removeItem(REFRESH_KEY)
    }
  }
}

export function clearTokens(): void {
  cachedId = null
  cachedRefresh = null
  sessionStorage.removeItem(ID_KEY)
  sessionStorage.removeItem(REFRESH_KEY)
}

/** Try to mint a new id_token using the stored refresh_token.
 *  Returns the new id_token on success, or null if refresh isn't possible
 *  (no refresh token stored, or Cognito rejected it). Multiple concurrent
 *  callers share a single in-flight fetch.
 */
export function tryRefresh(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight
  if (!cachedRefresh) return Promise.resolve(null)

  refreshInFlight = (async () => {
    try {
      const r = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({ refresh_token: cachedRefresh }),
      })
      if (!r.ok) return null
      const data = (await r.json()) as { id_token: string }
      // Don't touch the refresh token — Cognito's refresh flow doesn't
      // issue a new one. The old one stays valid until its 30-day TTL.
      setTokens(data.id_token)
      return data.id_token
    } catch {
      return null
    } finally {
      refreshInFlight = null
    }
  })()
  return refreshInFlight
}

export function clearTokenAndRedirectToLogin(): void {
  clearTokens()
  if (window.location.pathname !== '/login') {
    window.location.replace('/login')
  }
}
