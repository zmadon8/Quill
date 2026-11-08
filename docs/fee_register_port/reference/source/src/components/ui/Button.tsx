import { cn } from '@/lib/cn'
import type { ButtonHTMLAttributes } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success' | 'indigo' | 'amber'
type Size = 'sm' | 'md'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
}

const variants: Record<Variant, string> = {
  // One filled accent (oxblood) for the main action; everything else is an
  // outline or plain text so the page stays calm.
  primary: 'border border-blue-600 bg-blue-600 text-gray-50 hover:bg-blue-700 hover:border-blue-700',
  secondary: 'border border-gray-300 bg-transparent text-gray-900 hover:border-gray-900 hover:bg-gray-100',
  ghost: 'border border-transparent bg-transparent text-gray-700 hover:bg-gray-100 hover:text-gray-900',
  danger: 'border border-red-800 bg-red-800 text-gray-50 hover:bg-red-900',
  success: 'border border-gray-300 bg-transparent text-green-800 hover:border-green-800 hover:bg-green-50',
  indigo: 'border border-gray-900 bg-gray-900 text-gray-50 hover:bg-gray-700',
  amber: 'border border-amber-700 bg-transparent text-amber-800 hover:bg-amber-50',
}
const sizes: Record<Size, string> = {
  sm: 'px-2.5 py-1 text-xs',
  md: 'px-3.5 py-1.5 text-sm',
}

export function Button({ variant = 'primary', size = 'md', className, ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-sm font-medium transition-colors disabled:opacity-45 disabled:cursor-not-allowed',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  )
}
