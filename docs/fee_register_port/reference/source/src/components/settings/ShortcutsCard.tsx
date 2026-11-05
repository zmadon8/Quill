import { Card } from '@/components/ui/Card'

/** Every keyboard shortcut in the program (⌘ on Mac = Ctrl on Windows). */
export const SHORTCUTS: Array<{ keys: string; action: string; where: string }> = [
  { keys: '⌘ Z', action: 'Undo the last change', where: 'Anywhere (not inside a text box)' },
  { keys: '⇧ ⌘ Z', action: 'Redo', where: 'Anywhere (not inside a text box)' },
  { keys: '⌘ Enter', action: 'Save the memo', where: 'Memo form' },
  { keys: '⌘ F', action: 'Find on this page', where: 'Anywhere' },
  { keys: 'Enter / ⇧ Enter', action: 'Next / previous find match', where: 'Find bar' },
  { keys: 'Esc', action: 'Close the find bar, search results, or cancel an edit', where: 'Find bar, search, partner edit' },
  { keys: '⌘ 1 … ⌘ 7', action: 'Go to Dashboard, Statistics, Memos, Firms, Feebook, Outstanding, Settings', where: 'Anywhere' },
  { keys: '⌘ [', action: 'Go back to the previous screen', where: 'Anywhere' },
  { keys: '⌘ +  /  ⌘ −  /  ⌘ 0', action: 'Zoom in / zoom out / reset zoom', where: 'Anywhere' },
  { keys: 'Enter', action: 'Run the global search; add a firm, partner or bank account', where: 'Search box, add boxes' },
]

export function ShortcutsCard() {
  return (
    <Card className="space-y-2 p-4">
      <h3 className="text-lg font-medium">Keyboard Shortcuts</h3>
      <p className="text-xs text-gray-500">On Windows, use Ctrl in place of ⌘.</p>
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase text-gray-500">
          <tr><th className="w-48 py-1">Keys</th><th>Action</th><th>Where</th></tr>
        </thead>
        <tbody className="divide-y">
          {SHORTCUTS.map((s) => (
            <tr key={s.keys + s.action}>
              <td className="py-1.5 font-mono text-xs">{s.keys}</td>
              <td className="py-1.5">{s.action}</td>
              <td className="py-1.5 text-gray-500">{s.where}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}
