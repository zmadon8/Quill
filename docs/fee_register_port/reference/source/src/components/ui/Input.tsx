import { cn } from '@/lib/cn'
import type { InputHTMLAttributes } from 'react'
export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'w-full rounded-sm border border-gray-300 bg-white px-2.5 py-1.5 text-sm',
        'placeholder:text-gray-400 focus:border-gray-900 focus:outline-none focus:ring-1 focus:ring-gray-900',
        'disabled:bg-gray-100 disabled:text-gray-500',
        className,
      )}
      {...props}
    />
  )
}
