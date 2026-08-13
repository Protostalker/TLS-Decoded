import { useEffect, useState } from 'react'

/**
 * Returns true when the viewport width is below `breakpoint` (default 768px).
 * Updates reactively on resize, debounced via the resize event.
 */
export default function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < breakpoint)

  useEffect(() => {
    const handler = () => setIsMobile(window.innerWidth < breakpoint)
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [breakpoint])

  return isMobile
}
