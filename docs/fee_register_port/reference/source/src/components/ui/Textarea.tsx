import { cn } from '@/lib/cn'
import type { TextareaHTMLAttributes } from 'react'
export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        'w-full rounded-sm border border-gray-300 bg-white px-2.5 py-1.5 text-sm',
        'placeholder:text-gray-400 focus:border-gray-900 focus:outline-none focus:ring-1 focus:ring-gray-900',
        className,
      )}
      {...props}
    />
  )
}
