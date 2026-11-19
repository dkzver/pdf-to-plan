import type { Config } from 'tailwindcss'

/**
 * Маппинг токенов в Tailwind. Компоненты используют роли (bg-surface, text-muted),
 * а не сырые hex — тогда шаг brand меняет значения в одном месте.
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--color-bg)',
        surface: 'var(--color-surface)',
        'surface-2': 'var(--color-surface-2)',
        border: 'var(--color-border)',
        'border-input': 'var(--color-border-input)',
        text: 'var(--color-text)',
        'text-muted': 'var(--color-text-muted)',
        accent: 'var(--color-accent)',
        'on-accent': 'var(--color-on-accent)',
        'accent-soft': 'var(--color-accent-soft)',
        danger: 'var(--color-danger)',
        success: 'var(--color-success)',
        warning: 'var(--color-warning)',
      },
      fontFamily: {
        sans: 'var(--font-sans)',
        mono: 'var(--font-mono)',
      },
      fontSize: {
        xs: ['11px', '15px'],
        sm: ['12px', '16px'],
        base: ['13px', '18px'],
        md: ['15px', '22px'],
        lg: ['18px', '26px'],
        xl: ['24px', '30px'],
      },
      spacing: {
        1: '2px',
        2: '4px',
        3: '6px',
        4: '8px',
        5: '12px',
        6: '16px',
        7: '24px',
        8: '32px',
      },
      borderRadius: {
        sm: '3px',
        md: '5px',
        lg: '8px',
        pill: '999px',
      },
      boxShadow: {
        panel: 'var(--shadow-panel)',
        pop: 'var(--shadow-pop)',
      },
      transitionDuration: {
        fast: '100ms',
        base: '160ms',
      },
      transitionTimingFunction: {
        base: 'cubic-bezier(.2,.8,.2,1)',
      },
      screens: {
        tablet: '768px',
        desktop: '1024px',
      },
    },
  },
  plugins: [],
}

export default config
