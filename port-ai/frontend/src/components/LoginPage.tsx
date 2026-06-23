import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { LanguageSwitcher } from './LanguageSwitcher'
import './LoginPage.css'

type AuthMode = 'login' | 'register'

export function LoginPage() {
  const { t } = useTranslation('auth')
  const { login, register } = useAuth()
  const [mode, setMode] = useState<AuthMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [phone, setPhone] = useState('')
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setErrorCode(null)
    setIsSubmitting(true)
    try {
      if (mode === 'login') {
        await login(email.trim(), password)
      } else {
        await register(email.trim(), password, phone.trim(), fullName.trim() || undefined)
      }
      window.location.hash = ''
    } catch (err) {
      const code = err instanceof Error ? err.message : 'unknown'
      setErrorCode(code)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-page__toolbar">
        <LanguageSwitcher />
      </div>

      <div className="login-card">
        <header className="login-card__header">
          <h1>{t('login.title')}</h1>
          <p>{t('login.subtitle')}</p>
        </header>

        <div className="login-card__tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'login'}
            className={mode === 'login' ? 'is-active' : ''}
            onClick={() => {
              setMode('login')
              setErrorCode(null)
            }}
          >
            {t('login.tabLogin')}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'register'}
            className={mode === 'register' ? 'is-active' : ''}
            onClick={() => {
              setMode('register')
              setErrorCode(null)
            }}
          >
            {t('login.tabRegister')}
          </button>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          {mode === 'register' && (
            <>
              <label className="login-field">
                <span>{t('login.fullName')}</span>
                <input
                  type="text"
                  autoComplete="name"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                />
              </label>

              <label className="login-field">
                <span>{t('login.phone')}</span>
                <input
                  type="tel"
                  required
                  autoComplete="tel"
                  placeholder="+48123456789"
                  value={phone}
                  onChange={(event) => setPhone(event.target.value)}
                />
              </label>
            </>
          )}

          <label className="login-field">
            <span>{t('login.email')}</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>

          <label className="login-field">
            <span>{t('login.password')}</span>
            <input
              type="password"
              required
              minLength={8}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          {errorCode && (
            <p className="login-form__error" role="alert">
              {t(`login.errors.${errorCode}`, { defaultValue: t('login.errors.unknown') })}
            </p>
          )}

          <button type="submit" className="login-form__submit" disabled={isSubmitting}>
            {isSubmitting
              ? t('login.loading')
              : mode === 'login'
                ? t('login.submitLogin')
                : t('login.submitRegister')}
          </button>
        </form>

        <p className="login-card__footer">{t('login.footerHint')}</p>
      </div>
    </div>
  )
}
