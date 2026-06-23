import { useTranslation } from 'react-i18next'

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation()

  return (
    <div className="language-switcher">
      <span>{t('language.label')}</span>
      <button
        type="button"
        className={i18n.language === 'pl' ? 'active' : ''}
        onClick={() => void i18n.changeLanguage('pl')}
      >
        {t('language.pl')}
      </button>
      <button
        type="button"
        className={i18n.language === 'en' ? 'active' : ''}
        onClick={() => void i18n.changeLanguage('en')}
      >
        {t('language.en')}
      </button>
    </div>
  )
}
