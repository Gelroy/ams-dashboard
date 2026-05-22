/**
 * Minimal auth store: holds the Cognito access token in sessionStorage
 * (so it's cleared when the user closes the browser) and exposes
 * synchronous getter/setter helpers for the api client and route guard
 * to consume.
 *
 * Refresh-token flow is deliberately not implemented yet — when the
 * access token expires (1 hour default), the next API call returns 401,
 * which clears the token and bounces the user back to /login. Good
 * enough for an internal app; revisit if 1-hour re-logins get annoying.
 */
const TOKEN_KEY = 'ams-dashboard-access-token'

let cachedToken: string | null = sessionStorage.getItem(TOKEN_KEY)

export function getToken(): string | null {
  return cachedToken
}

export function setToken(token: string | null): void {
  cachedToken = token
  if (token) {
    sessionStorage.setItem(TOKEN_KEY, token)
  } else {
    sessionStorage.removeItem(TOKEN_KEY)
  }
}

export function clearTokenAndRedirectToLogin(): void {
  setToken(null)
  // Use location.replace so the protected page isn't in history.
  if (window.location.pathname !== '/login') {
    window.location.replace('/login')
  }
}
