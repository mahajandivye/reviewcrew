import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'reviewpilot-theme'

function initialTheme() {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'dark' || stored === 'light') return stored
  } catch {
    /* private mode / storage disabled - fall through to the OS preference */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/**
 * Dark mode via a `dark` class on <html>, persisted to localStorage.
 * The class is what Tailwind's `dark:` variants look for.
 */
export function useTheme() {
  const [theme, setTheme] = useState(initialTheme)

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', theme === 'dark')
    root.style.colorScheme = theme
    try {
      window.localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      /* ignore */
    }
  }, [theme])

  const toggle = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'))
  }, [])

  return { theme, toggle }
}
