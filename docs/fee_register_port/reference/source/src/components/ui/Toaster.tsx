import { useToastStore } from '@/stores/useToastStore'
import { cn } from '@/lib/cn'

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts)
  const dismiss = useToastStore((s) => s.dismiss)
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={cn(
            'flex min-w-[240px] items-center gap-3 border border-gray-300 border-l-[3px] bg-white px-4 py-2 text-sm text-gray-900 shadow-[0_1px_0_#CFC9BA]',
            t.variant === 'error' && 'border-l-red-700',
            t.variant === 'success' && 'border-l-green-700',
            t.variant === 'info' && 'border-l-gray-500',
          )}
        >
          <span className="flex-1">{t.message}</span>
          {t.action ? (
            <button
              className="border border-gray-300 px-2 py-0.5 text-xs font-semibold text-blue-700 hover:border-blue-700"
              onClick={() => {
                void t.action!.run()
                dismiss(t.id)
              }}
            >
              {t.action.label}
            </button>
          ) : (
            <button
              className="text-gray-400 hover:text-gray-900"
              aria-label="Dismiss"
              onClick={() => dismiss(t.id)}
            >
              ×
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
