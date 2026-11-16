/**
 * Token store for the portal session.
 *
 * sessionStorage on purpose: the session ends when the tab closes, and
 * nothing is left behind on a shared computer. The id_token is the Bearer
 * for /api/portal/*; the refresh_token (valid for one day) silently mints
 * a new id_token when the hourly one expires.
 */
const ID_KEY = 'ams-portal-id-token'
const REFRESH_KEY = 'ams-portal-refresh-token'

let idToken: string | null = sessionStorage.getItem(ID_KEY)
let refreshToken: string | null = sessionStorage.getItem(REFRESH_KEY)

export function getToken(): string | null {
  return idToken
}

export function getRefreshToken(): string | null {
  return refreshToken
}

/** Omit `refresh` to keep the current refresh token (a refresh response
 *  carries no new one). */
export function setTokens(id: string, refresh?: string | null): void {
  idToken = id
  sessionStorage.setItem(ID_KEY, id)
  if (refresh !== undefined) {
    refreshToken = refresh
    if (refresh) sessionStorage.setItem(REFRESH_KEY, refresh)
    else sessionStorage.removeItem(REFRESH_KEY)
  }
}

export function clearTokens(): void {
  idToken = null
  refreshToken = null
  sessionStorage.removeItem(ID_KEY)
  sessionStorage.removeItem(REFRESH_KEY)
}
