import { cn } from '@/lib/cn'
import type { HTMLAttributes } from 'react'
/** A plain, flat panel: hairline border, no shadow, square-ish corners. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-sm border border-gray-200 bg-card', className)} {...props} />
}
