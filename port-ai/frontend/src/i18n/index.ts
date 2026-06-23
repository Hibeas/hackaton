import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import enDashboard from '../locales/en/dashboard.json'
import plDashboard from '../locales/pl/dashboard.json'

void i18n.use(initReactI18next).init({
  resources: {
    en: { dashboard: enDashboard },
    pl: { dashboard: plDashboard },
  },
  lng: 'pl',
  fallbackLng: 'en',
  defaultNS: 'dashboard',
  interpolation: {
    escapeValue: false,
  },
})

export default i18n
