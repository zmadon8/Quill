import { useConfirmStore } from '@/stores/useConfirmStore'
import { Button } from '@/components/ui/Button'

/**
 * App-wide styled confirmation dialog. Rendered once near the root; opened
 * imperatively via confirmDialog(...) / useConfirmStore. Replaces native
 * window.confirm so destructive actions can emphasise "cannot be undone".
 */
export function ConfirmModal() {
  const open = useConfirmStore((s) => s.open)
  const options = useConfirmStore((s) => s.options)
  const respond = useConfirmStore((s) => s.respond)

  if (!open || !options) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div
        className="w-full max-w-md rounded-sm border border-gray-900 bg-gray-50 p-5 shadow-[0_6px_24px_rgba(28,27,25,0.18)]"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-xl font-medium text-gray-900">{options.title}</h3>
        <p className="mt-2 text-sm text-gray-600">{options.message}</p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => respond(false)}>
            {options.cancelLabel ?? 'Cancel'}
          </Button>
          <Button
            variant={options.destructive ? 'danger' : 'primary'}
            onClick={() => respond(true)}
            autoFocus
          >
            {options.confirmLabel ?? 'Confirm'}
          </Button>
        </div>
      </div>
    </div>
  )
}
