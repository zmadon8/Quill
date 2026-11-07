import { useState } from 'react'
import { useToastStore, errorMessage } from '@/stores/useToastStore'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Select'
import { Label } from '@/components/ui/Label'
import type { ImportField, ImportInspection, ImportMapping, ImportResult } from '@/types/ipc'

interface Props {
  onClose: () => void
}

/** The app fields the user can map, with labels and whether they are required. */
const FIELDS: { id: ImportField; label: string; required?: boolean; group: string }[] = [
  { id: 'firmName', label: 'Firm name', required: true, group: 'Who' },
  { id: 'partnerName', label: 'Partner', group: 'Who' },
  { id: 'matterName', label: 'Matter / case name', required: true, group: 'Who' },
  { id: 'memoNumber', label: 'Memo number (blank → draft)', group: 'Memo' },
  { id: 'date', label: 'Memo date', group: 'Memo' },
  { id: 'totalFees', label: 'Total fee (overrides breakup)', group: 'Fees' },
  { id: 'numAppearances', label: 'No. of appearances', group: 'Fees breakup' },
  { id: 'feesPerAppearance', label: 'Fee per appearance', group: 'Fees breakup' },
  { id: 'numConferences', label: 'No. of conferences', group: 'Fees breakup' },
  { id: 'feesPerConference', label: 'Fee per conference', group: 'Fees breakup' },
  { id: 'numDrafts', label: 'No. of drafts', group: 'Fees breakup' },
  { id: 'miscDescription', label: 'Misc / drafting description', group: 'Fees breakup' },
  { id: 'feesMisc', label: 'Misc / drafting fee', group: 'Fees breakup' },
  { id: 'amountPaid', label: 'Amount already paid (net)', group: 'Payment' },
  { id: 'paymentTds', label: 'TDS on the payment', group: 'Payment' },
  { id: 'paymentDate', label: 'Payment date', group: 'Payment' },
  { id: 'payee', label: 'Payee', group: 'Payment' },
  { id: 'paymentGroup', label: 'Payment group (same value = paid together)', group: 'Payment' },
  { id: 'courtName', label: 'Court / cause title → Matter', group: 'Matter details' },
  { id: 'matterClient', label: 'Client (role) → Matter', group: 'Matter details' },
  { id: 'partyPlaintiff', label: 'Plaintiff / applicant', group: 'Parties (optional)' },
  { id: 'partyDefendant', label: 'Defendant / respondent', group: 'Parties (optional)' },
]

/** Case-insensitive best-guess match of an app field to a source header. */
function guess(field: ImportField, headers: string[]): string | null {
  // Each needle may be a plain substring or an exact header match prefixed with
  // '=' (used to disambiguate overlapping names like "Date" vs "Payment Date").
  const needles: Record<ImportField, string[]> = {
    firmName: ['=firm', 'firm', 'company'],
    partnerName: ['=partner', 'partner'],
    matterName: ['=matter name', 'matter', 'case', '=title'],
    memoNumber: ['=memo no.', 'memo no', 'memo number', 'bill no', 'invoice'],
    date: ['=date', 'memo date'],
    numAppearances: ['=appearances', 'no. of appearances', 'num appearance', 'appearance'],
    feesPerAppearance: ['per appearance', 'appearance fee', 'rate'],
    numConferences: ['=conferences', 'no. of conferences', 'conference'],
    feesPerConference: ['per conference', 'conference fee'],
    numDrafts: ['=drafts', 'no. of drafts', '=draft', 'drafts', 'draft'],
    miscDescription: ['misc / drafting description', 'description', 'particular', 'narration'],
    feesMisc: ['misc / drafting fee', 'misc', 'drafting'],
    totalFees: ['=total fees', 'total fee', 'amount billed', 'gross', '=fees'],
    amountPaid: ['=amount paid', 'amount paid', 'net paid', '=paid'],
    paymentTds: ['=payment tds', 'payment tds', 'tds on', '=less tds', '=tds'],
    paymentDate: ['=payment date', 'payment date', 'cleared', 'date paid'],
    payee: ['=payee', 'payee', 'received from', 'payment received from'],
    paymentGroup: ['=payment group', 'payment group', 'pmt group', 'group id'],
    partyPlaintiff: ['plaintiff', 'applicant', 'petitioner'],
    partyDefendant: ['defendant', 'respondent'],
    courtName: ['=court / cause title', 'cause title', '=court', 'court', 'tribunal'],
    matterClient: ['=client', 'client', 'party role'],
  }
  const lowered = headers.map((h) => h.toLowerCase().trim())
  for (const n of needles[field]) {
    if (n.startsWith('=')) {
      const exact = n.slice(1)
      const idx = lowered.findIndex((h) => h === exact)
      if (idx >= 0) return headers[idx]
    } else {
      const idx = lowered.findIndex((h) => h.includes(n))
      if (idx >= 0) return headers[idx]
    }
  }
  return null
}

export function ImportMemosDialog({ onClose }: Props) {
  const show = useToastStore((s) => s.show)
  const [inspection, setInspection] = useState<ImportInspection | null>(null)
  const [mapping, setMapping] = useState<ImportMapping>({})
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  // When on, rows with a date but no mapped memo number are auto-numbered
  // (finalised) in file order, rather than imported as drafts.
  const [autoNumber, setAutoNumber] = useState(false)

  const pickFile = async () => {
    const res = await window.api.import.inspect()
    if (!res.ok) {
      show(errorMessage(res.error), 'error')
      return
    }
    if (!res.data) return // cancelled
    setInspection(res.data)
    // Pre-fill the mapping with best guesses.
    const initial: ImportMapping = {}
    for (const f of FIELDS) initial[f.id] = guess(f.id, res.data.headers)
    setMapping(initial)
    setResult(null)
  }

  const runImport = async () => {
    if (!inspection) return
    if (!mapping.firmName || !mapping.matterName) {
      show('Map both Firm name and Matter name before importing.', 'error')
      return
    }
    setRunning(true)
    try {
      const res = await window.api.import.run(inspection.filePath, mapping, autoNumber)
      if (!res.ok) {
        show(errorMessage(res.error), 'error')
        return
      }
      setResult(res.data)
      show(`Imported ${res.data.memosCreated} memos.`, 'success')
    } finally {
      setRunning(false)
    }
  }

  const colIndex = (header: string) => inspection?.headers.indexOf(header) ?? -1

  // Group fields for a tidy layout.
  const groups = Array.from(new Set(FIELDS.map((f) => f.group)))

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-sm border border-gray-900 bg-gray-50 p-5 shadow-[0_6px_24px_rgba(28,27,25,0.18)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-xl font-medium">Import Memos from a Spreadsheet</h3>
          <button className="text-gray-400 hover:text-gray-700" onClick={onClose}>×</button>
        </div>

        {!inspection ? (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              Choose an Excel (.xlsx) or CSV file whose first row is a header. Each remaining row
              should be one memo. Firms and matters are created automatically by name. This adds to
              your existing data (it does not replace anything).
            </p>
            <Button onClick={pickFile}>Choose File…</Button>
          </div>
        ) : result ? (
          <div className="space-y-3">
            <div className="rounded border border-green-200 bg-green-50 p-3 text-sm text-green-800">
              <div className="font-semibold">Import complete</div>
              <ul className="mt-1 list-inside list-disc">
                <li>{result.memosCreated} memos created</li>
                <li>{result.firmsCreated} firms, {result.mattersCreated} matters created</li>
                <li>{result.paymentsCreated} payments recorded</li>
                <li>{result.rowsProcessed} rows processed</li>
              </ul>
            </div>
            {result.warnings.length > 0 && (
              <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                <div className="font-semibold">{result.warnings.length} notice(s):</div>
                <ul className="mt-1 max-h-40 list-inside list-disc overflow-y-auto">
                  {result.warnings.slice(0, 50).map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => { setInspection(null); setResult(null) }}>
                Import Another File
              </Button>
              <Button onClick={onClose}>Done</Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-sm text-gray-600">
              Found <strong>{inspection.rowCount}</strong> rows. Match each app field to one of your
              columns. Required fields are marked •.
            </p>

            <div className="space-y-4">
              {groups.map((g) => (
                <div key={g}>
                  <p className="mb-1 text-xs font-semibold uppercase text-gray-500">{g}</p>
                  <div className="grid grid-cols-2 gap-3">
                    {FIELDS.filter((f) => f.group === g).map((f) => (
                      <div key={f.id}>
                        <Label>
                          {f.label} {f.required && <span className="text-red-600">•</span>}
                        </Label>
                        <Select
                          className="w-full"
                          value={mapping[f.id] ?? ''}
                          onChange={(e) =>
                            setMapping((m) => ({ ...m, [f.id]: e.target.value || null }))
                          }
                        >
                          <option value="">— skip —</option>
                          {inspection.headers.map((h) => (
                            <option key={h} value={h}>{h}</option>
                          ))}
                        </Select>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* Preview of the first rows for the mapped Firm/Matter/Memo/Total. */}
            <div className="rounded border bg-gray-50 p-3">
              <p className="mb-2 text-xs font-semibold uppercase text-gray-500">Preview (first rows)</p>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-gray-500">
                    <th className="py-1 pr-3">Firm</th>
                    <th className="py-1 pr-3">Matter</th>
                    <th className="py-1 pr-3">Memo No.</th>
                    <th className="py-1 pr-3">Date</th>
                    <th className="py-1 pr-3 text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {inspection.sampleRows.map((cells, i) => {
                    const cell = (field: ImportField) => {
                      const h = mapping[field]
                      if (!h) return ''
                      const idx = colIndex(h)
                      return idx >= 0 ? cells[idx] ?? '' : ''
                    }
                    return (
                      <tr key={i} className="border-t">
                        <td className="py-1 pr-3">{cell('firmName')}</td>
                        <td className="py-1 pr-3">{cell('matterName')}</td>
                        <td className="py-1 pr-3">{cell('memoNumber')}</td>
                        <td className="py-1 pr-3">{cell('date')}</td>
                        <td className="py-1 pr-3 text-right">{cell('totalFees')}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            <label className="flex items-start gap-2 rounded border bg-gray-50 p-3 text-sm text-gray-700">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4"
                checked={autoNumber}
                onChange={(e) => setAutoNumber(e.target.checked)}
              />
              <span>
                <strong>Auto-number memos.</strong> Leave the “Memo number” field unmapped above and
                tick this to have the app generate memo numbers (per financial year, in the file’s
                row order) instead of using numbers from the file. Rows are numbered by date’s
                financial year — sort the file so each year’s memos appear in the order you want them
                numbered.
              </span>
            </label>

            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setInspection(null)}>Back</Button>
              <Button onClick={runImport} disabled={running}>
                {running ? 'Importing…' : `Import ${inspection.rowCount} Rows`}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
