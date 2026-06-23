import type { AuthErrorCode, AuthResponse, AuthUser } from '../types/auth'
import { clearAuth, getStoredToken, persistAuth } from './authStorage'

const AUTH_REQUEST_TIMEOUT_MS = 15000

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

async function parseAuthError(response: Response): Promise<AuthErrorCode> {
  try {
    const body = (await response.json()) as { detail?: string | string[] }
    const detail = Array.isArray(body.detail) ? body.detail[0] : body.detail
    if (typeof detail === 'string') {
      return detail as AuthErrorCode
    }
  } catch {
    // ignore parse errors
  }
  return 'unknown'
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
