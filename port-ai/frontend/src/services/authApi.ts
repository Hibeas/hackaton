import type { AuthErrorCode, AuthResponse, AuthUser } from '../types/auth'
import { clearAuth, getStoredToken, persistAuth } from './authStorage'

const AUTH_REQUEST_TIMEOUT_MS = 15000

const KNOWN_AUTH_ERRORS = new Set<AuthErrorCode>([
  'email_taken',
  'invalid_credentials',
  'invalid_phone',
  'weak_password',
  'invalid_token',
  'missing_token',
  'user_not_found',
  'auth_not_configured',
  'auth_login_failed',
  'auth_register_failed',
  'network_error',
  'server_error',
  'validation_error',
  'unknown',
])

function authHeaders(): HeadersInit {
  const token = getStoredToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  return headers
}

async function fetchAuth(url: string, options: RequestInit = {}): Promise<Response> {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), AUTH_REQUEST_TIMEOUT_MS)
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('network_error')
    }
    throw new Error('network_error')
  } finally {
    window.clearTimeout(timeoutId)
  }
}

function normalizeAuthErrorCode(detail: unknown, status: number): AuthErrorCode {
  if (typeof detail === 'string') {
    if (KNOWN_AUTH_ERRORS.has(detail as AuthErrorCode)) {
      return detail as AuthErrorCode
    }
    if (detail === 'Internal Server Error') {
      return 'server_error'
    }
  }

  if (Array.isArray(detail) && detail.length > 0) {
    return 'validation_error'
  }

  if (status === 401) {
    return 'invalid_credentials'
  }
  if (status >= 500) {
    return 'server_error'
  }

  return 'unknown'
}

async function parseAuthError(response: Response): Promise<AuthErrorCode> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    return normalizeAuthErrorCode(body.detail, response.status)
  } catch {
    return response.status >= 500 ? 'server_error' : 'unknown'
  }
}

export async function registerUser(payload: {
  email: string
  password: string
  phone_e164: string
  full_name?: string
}): Promise<AuthResponse> {
  const response = await fetchAuth('/api/v1/auth/register', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await parseAuthError(response))
  }
  const data = (await response.json()) as AuthResponse
  persistAuth(data.access_token, data.user)
  return data
}

export async function loginUser(payload: {
  email: string
  password: string
}): Promise<AuthResponse> {
  const response = await fetchAuth('/api/v1/auth/login', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await parseAuthError(response))
  }
  const data = (await response.json()) as AuthResponse
  persistAuth(data.access_token, data.user)
  return data
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  const response = await fetchAuth('/api/v1/auth/me', {
    headers: authHeaders(),
  })
  if (!response.ok) {
    clearAuth()
    throw new Error(await parseAuthError(response))
  }
  const user = (await response.json()) as AuthUser
  const token = getStoredToken()
  if (token) {
    persistAuth(token, user)
  }
  return user
}

export function logoutUser(): void {
  clearAuth()
}
