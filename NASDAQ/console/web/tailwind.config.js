import containerQueries from '@tailwindcss/container-queries';

/**
 * NAFA Console — Tailwind config.
 * Colours resolve to the CSS variables in nafa-tokens.css, so a single class
 * (bg-bg-1, text-fg-2, text-pos, border-line-1 …) is correct in both themes
 * without dark: variants. Switch theme with data-theme="light" on the app root.
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}', './.storybook/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: { 0: 'var(--bg-0)', 1: 'var(--bg-1)', 2: 'var(--bg-2)', 3: 'var(--bg-3)', 4: 'var(--bg-4)' },
        line: { 1: 'var(--line-1)', 2: 'var(--line-2)', 3: 'var(--line-3)' },
        fg: { 1: 'var(--fg-1)', 2: 'var(--fg-2)', 3: 'var(--fg-3)', inv: 'var(--fg-inv)' },
        // P&L sign — money only, always paired with + / −
        pos: { DEFAULT: 'var(--pos)', bg: 'var(--pos-bg)', line: 'var(--pos-line)' },
        neg: { DEFAULT: 'var(--neg)', bg: 'var(--neg-bg)', line: 'var(--neg-line)' },
        // severity
        warn: { DEFAULT: 'var(--warn)', bg: 'var(--warn-bg)', line: 'var(--warn-line)' },
        danger: { DEFAULT: 'var(--danger)', bg: 'var(--danger-bg)', line: 'var(--danger-line)', solid: 'var(--danger-solid)', 'solid-hover': 'var(--danger-solid-h)' },
        info: { DEFAULT: 'var(--info)', bg: 'var(--info-bg)', line: 'var(--info-line)' },
        // books and chart series
        acct: { DEFAULT: 'var(--acct)', bg: 'var(--acct-bg)', line: 'var(--acct-line)' },
        series: { model: 'var(--s-model)', acct: 'var(--s-acct)', bench: 'var(--s-bench)' },
        // environment badge
        env: { ghost: 'var(--env-ghost)', paper: 'var(--env-paper)', live: 'var(--env-live)' },
        // Sharia grade
        grade: {
          a: 'var(--g-a)', 'a-bg': 'var(--g-a-bg)',
          b: 'var(--g-b)', 'b-bg': 'var(--g-b-bg)',
          c: 'var(--g-c)', 'c-bg': 'var(--g-c-bg)',
          f: 'var(--g-f)', 'f-bg': 'var(--g-f-bg)',
        },
        focus: 'var(--focus)',
        scrim: 'var(--scrim)',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      fontSize: {
        '2xs': ['10.5px', { lineHeight: '14px', letterSpacing: '0.08em' }], // caps labels
        xs: ['11px', '15px'],      // captions
        sm: ['12px', '16px'],      // tables
        base: ['13px', '19px'],    // body
        md: ['14px', '20px'],
        lg: ['16px', '22px'],
        xl: ['20px', '26px'],      // page titles
        kpi: ['21px', '25px'],     // KPI values
        '2xl': ['28px', '32px'],   // big P&L
      },
      borderRadius: { sm: '4px', DEFAULT: '6px', md: '8px', lg: '12px' },
      boxShadow: { pop: 'var(--shadow)' },
      width: { nav: '216px', rail: '60px', drawer: '560px', modal: '640px' },
      height: { topbar: '56px', 'topbar-phone': '52px', tabbar: '64px' },
      containers: { phone: '768px', desk: '1280px' },
      keyframes: {
        pulse_ring: { '0%, 100%': { boxShadow: '0 0 0 0 rgba(234,165,62,0)' }, '50%': { boxShadow: '0 0 0 5px rgba(234,165,62,.22)' } },
        shimmer: { '0%': { backgroundPosition: '120% 0' }, '100%': { backgroundPosition: '-120% 0' } },
      },
      animation: {
        'held-pulse': 'pulse_ring 1.8s ease-in-out infinite', // NIGHT HELD pill
        skeleton: 'shimmer 1.3s linear infinite',
      },
    },
  },
  // Layout responds to the app shell's width, not the viewport (mobile-first):
  // <div className="@container/app"> base = phone (<768) · @phone/app: = 768+ (nav rail) · @desk/app: = 1280+ (full nav)
  // nafa.css carries its own reset, so Tailwind's preflight stays off.
  corePlugins: { preflight: false },
  plugins: [containerQueries],
};
