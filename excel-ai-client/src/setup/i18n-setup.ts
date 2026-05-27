import { createI18n } from 'vue-i18n';

// Import translation files
import en from '@/lang/en.json';
import mr from '@/lang/mr.json';
import hi from '@/lang/hi.json';
import dv from '@/lang/dv.json';

const messages = {
  en,
  mr,
  hi,
  dv,
};

const i18n = createI18n({
  locale: 'en',
  fallbackLocale: 'en',
  messages,
});

export default i18n;
