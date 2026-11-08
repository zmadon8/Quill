/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  content: [
    './src/**/*.{ts,tsx}',
    './src/index.html',
  ],
  theme: {
    extend: {
      // Deliberately small, square-ish corners (ledger / stationery feel).
      borderRadius: {
        DEFAULT: '2px',
        sm: '2px',
        md: '3px',
        lg: '4px',
        xl: '4px',
        '2xl': '6px',
      },
      fontFamily: {
        sans: ['"Inter Variable"', 'Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        serif: ['"Newsreader Variable"', 'Newsreader', 'Georgia', '"Times New Roman"', 'serif'],
      },
      colors: {
        // The existing utility classes (gray-*, blue-*, indigo-*) are re-pointed
        // at the ledger palette, so every page picks up the new look at once.
        // gray   -> warm paper and ink neutrals
        // blue   -> oxblood (the single accent)
        // indigo -> ink (dark neutrals for secondary emphasis)
        gray: {
          50: '#FAF8F3', 100: '#F3F0E7', 200: '#E4DFD2', 300: '#CFC9BA', 400: '#A8A294',
          500: '#7B7568', 600: '#5E594E', 700: '#3F3C35', 800: '#2A2825', 900: '#1C1B19',
        },
        blue: {
          50: '#F8EEEE', 100: '#F0DCDC', 200: '#E2BDBD', 300: '#CE9393', 400: '#B06666',
          500: '#924242', 600: '#7A2E2E', 700: '#652525', 800: '#511E1E', 900: '#3E1717',
        },
        indigo: {
          50: '#F3F0E8', 100: '#E8E3D6', 200: '#D6CFBE', 300: '#BDB5A1', 400: '#9A917D',
          500: '#7B7568', 600: '#5E594E', 700: '#3F3C35', 800: '#2A2825', 900: '#1C1B19',
        },
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        chart: {
          '1': 'hsl(var(--chart-1))',
          '2': 'hsl(var(--chart-2))',
          '3': 'hsl(var(--chart-3))',
          '4': 'hsl(var(--chart-4))',
          '5': 'hsl(var(--chart-5))',
        },
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
}
