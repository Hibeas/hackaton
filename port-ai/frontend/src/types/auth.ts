export interface AuthUser {
  id: string
  email: string
  full_name: string | null
  phone_e164: string | null
  created_at: string | null
}

export interface AuthResponse {
  access_token: string
  token_type: 'bearer'
  user: AuthUser
}

export type AuthErrorCode =
  | 'email_taken'
  | 'invalid_credentials'
  | 'invalid_phone'
  | 'weak_password'
  | 'invalid_token'
  | 'missing_token'
  | 'user_not_found'
  | 'auth_not_configured'
  | 'auth_login_failed'
  | 'auth_register_failed'
  | 'network_error'
  | 'server_error'
  | 'validation_error'
  | 'unknown'
