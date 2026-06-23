const TOKEN_KEY = 'port_ai_access_token'
const USER_KEY = 'port_ai_user'

import type { AuthUser } from '../types/auth'

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getStoredUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) {
    return null
  }
  try {
    return JSON.parse(raw) as AuthUser
  } catch {
    return null
  }
}

export function persistAuth(accessToken: string, user: AuthUser): void {
  localStorage.setItem(TOKEN_KEY, accessToken)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}
