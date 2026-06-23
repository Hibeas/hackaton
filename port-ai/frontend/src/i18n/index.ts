import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import enDashboard from '../locales/en/dashboard.json'
import enAuth from '../locales/en/auth.json'
import plDashboard from '../locales/pl/dashboard.json'
import plAuth from '../locales/pl/auth.json'

void i18n.use(initReactI18next).init({
  resources: {
    en: { dashboard: enDashboard, auth: enAuth },
    pl: { dashboard: plDashboard, auth: plAuth },
  },
  lng: 'pl',
  fallbackLng: 'en',
  defaultNS: 'dashboard',
  interpolation: {
    escapeValue: false,
  },
})

export default i18n
