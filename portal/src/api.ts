/**
 * Client for /api/portal/*. There is no organization parameter anywhere:
 * the server derives the customer from the signed-in account.
 */
import { clearTokens, getRefreshToken, getToken, setTokens } from './auth'

const API = '/api/portal'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// ── Sign-in flow ─────────────────────────────────────────────────────

export interface Tokens {
  id_token: string
  access_token: string
  refresh_token?: string
}

interface ChallengeBase {
  session: string
  username: string
}
export interface NewPasswordChallenge extends ChallengeBase {
  challenge: 'NEW_PASSWORD_REQUIRED'
}
export interface MfaSetupChallenge extends ChallengeBase {
  challenge: 'MFA_SETUP'
  secret_code: string
  otpauth_uri: string
}
export interface MfaChallenge extends ChallengeBase {
  challenge: 'SOFTWARE_TOKEN_MFA'
}
export type Challenge = NewPasswordChallenge | MfaSetupChallenge | MfaChallenge
export type AuthStep = Tokens | Challenge

export function isChallenge(step: AuthStep): step is Challenge {
  return 'challenge' in step
}

async function parse<T>(r: Response): Promise<T> {
  if (r.status === 204) return undefined as T
  let body: unknown = null
  try {
    body = await r.json()
  } catch {
    // non-JSON error page
  }
  if (!r.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string'
        ? body.detail
        : 'Something went wrong. Please try again.'
    throw new ApiError(r.status, detail)
  }
  return body as T
}

function post<T>(path: string, body: unknown): Promise<T> {
  return fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => parse<T>(r))
}

export const login = (email: string, password: string) =>
  post<AuthStep>('/auth/login', { email, password })

export const submitNewPassword = (c: ChallengeBase, email: string, newPassword: string) =>
  post<AuthStep>('/auth/new-password', {
    session: c.session,
    username: c.username,
    email,
    new_password: newPassword,
  })

export const confirmMfaSetup = (c: ChallengeBase, code: string) =>
  post<AuthStep>('/auth/mfa/setup', { session: c.session, username: c.username, code })

export const verifyMfa = (c: ChallengeBase, code: string) =>
  post<AuthStep>('/auth/mfa/verify', { session: c.session, username: c.username, code })

export async function signOut(): Promise<void> {
  const refresh_token = getRefreshToken()
  clearTokens()
  if (refresh_token) {
    // Best effort: revoke server-side so the refresh token is dead too.
    await post<void>('/auth/logout', { refresh_token }).catch(() => undefined)
  }
}

// ── Authenticated reads ──────────────────────────────────────────────

let refreshing: Promise<string | null> | null = null

function tryRefresh(): Promise<string | null> {
  if (refreshing) return refreshing
  const refresh_token = getRefreshToken()
  if (!refresh_token) return Promise.resolve(null)
  refreshing = post<Tokens>('/auth/refresh', { refresh_token })
    .then((t) => {
      setTokens(t.id_token)
      return t.id_token
    })
    .catch(() => null)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

function authedFetch(path: string, token: string | null, accept: string): Promise<Response> {
  return fetch(`${API}${path}`, {
    headers: { Accept: accept, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  })
}

/** GET with the bearer token, one silent refresh, then back to sign-in. */
async function authed(path: string, accept: string): Promise<Response> {
  let r = await authedFetch(path, getToken(), accept)
  if (r.status === 401) {
    const fresh = await tryRefresh()
    if (fresh) r = await authedFetch(path, fresh, accept)
    if (r.status === 401) {
      clearTokens()
      window.location.replace('/login')
      throw new ApiError(401, 'Your session has ended. Please sign in again.')
    }
  }
  return r
}

async function get<T>(path: string): Promise<T> {
  return parse<T>(await authed(path, 'application/json'))
}

export interface Me {
  email: string
  display_name: string | null
  role: string | null
  last_login_at: string | null
  organization: { id: string; name: string }
}

export interface Home {
  organization: {
    id: string
    name: string
    ams_level: 'Essential' | 'Enhanced' | 'Expert' | null
    help_desk_phone: string | null
    country: string | null
  }
  environments: { name: string; server_count: number }[]
}

export interface PortalDocument {
  id: string
  title: string
  /** "2026-10" */
  period: string
  /** "October 2026" */
  period_label: string
  published_at: string
  size: number | null
  filename: string
}

export const getMe = () => get<Me>('/me')
export const getHome = () => get<Home>('/home')
export const getDocuments = () => get<PortalDocument[]>('/documents')

/** Fetch a document's PDF. It is requested with the bearer token like any
 *  other call — there is no link that works without being signed in. */
export async function getDocumentPdf(id: string): Promise<Blob> {
  const r = await authed(`/documents/${encodeURIComponent(id)}/download`, 'application/pdf')
  if (!r.ok) {
    throw new ApiError(
      r.status,
      r.status === 404
        ? 'This document is no longer available.'
        : 'The document could not be opened. Please try again.',
    )
  }
  return r.blob()
}
