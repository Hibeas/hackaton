import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import type { AuthUser } from '../types/auth'
import { fetchCurrentUser, loginUser, logoutUser, registerUser } from '../services/authApi'
import { getStoredToken, getStoredUser } from '../services/authStorage'

interface AuthContextValue {
  user: AuthUser | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, phoneE164: string, fullName?: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => getStoredUser())
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const token = getStoredToken()
    if (!token) {
      setIsLoading(false)
      return
    }
    fetchCurrentUser()
      .then((current) => setUser(current))
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const result = await loginUser({ email, password })
    setUser(result.user)
  }, [])

  const register = useCallback(async (email: string, password: string, phoneE164: string, fullName?: string) => {
    const result = await registerUser({
      email,
      password,
      phone_e164: phoneE164,
      full_name: fullName?.trim() || undefined,
    })
    setUser(result.user)
  }, [])

  const logout = useCallback(() => {
    logoutUser()
    setUser(null)
    window.location.hash = '#/login'
  }, [])

  const value = useMemo(
    () => ({
      user,
      isAuthenticated: user !== null,
      isLoading,
      login,
      register,
      logout,
    }),
    [user, isLoading, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
