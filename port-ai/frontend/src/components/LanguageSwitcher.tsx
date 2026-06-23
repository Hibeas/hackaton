import { useTranslation } from 'react-i18next'

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation()

  return (
    <div className="language-switcher" aria-label={t('language.label')}>
      <button
        type="button"
        className={i18n.language === 'pl' ? 'active' : ''}
        onClick={() => void i18n.changeLanguage('pl')}
      >
        PL
      </button>
      <button
        type="button"
        className={i18n.language === 'en' ? 'active' : ''}
        onClick={() => void i18n.changeLanguage('en')}
      >
        EN
      </button>
    </div>
  )
}
