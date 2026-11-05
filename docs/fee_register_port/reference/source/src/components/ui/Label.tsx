import { cn } from '@/lib/cn'
import type { LabelHTMLAttributes } from 'react'
export function Label({ className, ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn('mb-1 block text-[11px] font-semibold uppercase tracking-[0.07em] text-gray-500', className)}
      {...props}
    />
  )
}
