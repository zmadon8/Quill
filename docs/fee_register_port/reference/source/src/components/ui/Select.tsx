import { cn } from '@/lib/cn'
import type { SelectHTMLAttributes } from 'react'
export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'rounded-sm border border-gray-300 bg-white px-2 py-1.5 text-sm',
        'focus:border-gray-900 focus:outline-none focus:ring-1 focus:ring-gray-900',
        'disabled:bg-gray-100 disabled:text-gray-500',
        className,
      )}
      {...props}
    >
      {children}
    </select>
  )
}
