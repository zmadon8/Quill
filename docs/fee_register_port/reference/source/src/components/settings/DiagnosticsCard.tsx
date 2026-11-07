import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import type { SystemMetrics } from '@/types/ipc'

interface Sample {
  at: string
  totalMemoryMb: number
  mainRssMb: number
  mainHeapMb: number
  cpuPercentTotal: number
}

const SAMPLE_EVERY_MS = 5000

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

/**
 * Settings → Diagnostics: measures this app's CPU / RAM / database footprint and
 * the cost of each data call, to help size a web deployment (Render, Railway…).
 * Desktop figures include Chromium (the UI); a web version's server would only
 * carry the "data call" work and the database, so read those rows for hosting.
 */
export function DiagnosticsCard() {
  const [latest, setLatest] = useState<SystemMetrics | null>(null)
  const [samples, setSamples] = useState<Sample[]>([])
  const [recording, setRecording] = useState(false)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const take = async () => {
    const res = await window.api.system.metrics()
    if (!res.ok) return
    const m = res.data
    setLatest(m)
    setSamples((s) =>
      [
        ...s,
        {
          at: m.at,
          totalMemoryMb: m.totalMemoryMb,
          mainRssMb: m.mainRssMb,
          mainHeapMb: m.mainHeapMb,
          cpuPercentTotal: Math.round(m.processes.reduce((a, p) => a + p.cpuPercent, 0) * 10) / 10,
        },
      ].slice(-2000),
    )
  }

  useEffect(() => {
    if (!recording) return
    void take()
    timer.current = setInterval(() => void take(), SAMPLE_EVERY_MS)
    return () => {
      if (timer.current) clearInterval(timer.current)
    }
  }, [recording])

  const peak = (f: (s: Sample) => number) => samples.reduce((a, s) => Math.max(a, f(s)), 0)
  const avg = (f: (s: Sample) => number) =>
    samples.length ? samples.reduce((a, s) => a + f(s), 0) / samples.length : 0

  // A deliberately rough sizing hint: the server would carry the main process
  // and the database, not the browser UI.
  const peakMain = peak((s) => s.mainRssMb) || latest?.mainRssMb || 0
  const suggestedRam = Math.max(512, Math.ceil((peakMain * 2) / 256) * 256)

  const exportSamples = () =>
    download(
      'fee-register-resource-samples.csv',
      ['time,total_memory_mb,main_rss_mb,main_heap_mb,cpu_percent_total']
        .concat(samples.map((s) => `${s.at},${s.totalMemoryMb},${s.mainRssMb},${s.mainHeapMb},${s.cpuPercentTotal}`))
        .join('\n'),
    )
  const exportTimings = () =>
    latest &&
    download(
      'fee-register-call-timings.csv',
      ['channel,calls,total_ms,p50_ms,p95_ms,max_ms']
        .concat(latest.channels.map((c) => `${c.channel},${c.calls},${c.totalMs},${c.p50Ms},${c.p95Ms},${c.maxMs}`))
        .join('\n'),
    )

  return (
    <Card className="space-y-3 p-4">
      <h3 className="text-lg font-medium">Diagnostics &amp; Hosting Estimate</h3>
      <p className="text-sm text-gray-600">
        Measures how much CPU, memory and storage the program uses, and how long each data call takes.
        Start recording, use the app normally for a while (run a few exports and statistics), then read the
        figures below. Desktop numbers include the screen engine (Chromium); on a web host only the
        &ldquo;main process&rdquo;, the data calls and the database would run on the server.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant={recording ? 'danger' : 'primary'} onClick={() => setRecording((r) => !r)}>
          {recording ? 'Stop recording' : 'Start recording'}
        </Button>
        <Button variant="secondary" onClick={() => void take()}>Snapshot now</Button>
        <Button variant="secondary" onClick={exportSamples} disabled={samples.length === 0}>
          Export samples (CSV)
        </Button>
        <Button variant="secondary" onClick={exportTimings} disabled={!latest}>
          Export call timings (CSV)
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            setSamples([])
            setLatest(null)
          }}
        >
          Clear
        </Button>
      </div>

      {latest && (
        <div className="space-y-4 text-sm">
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 md:grid-cols-4">
            <Stat label="Total memory (all processes)" value={`${latest.totalMemoryMb} MB`} />
            <Stat label="Main process memory (RSS)" value={`${latest.mainRssMb} MB`} />
            <Stat label="Main process heap" value={`${latest.mainHeapMb} MB`} />
            <Stat label="Main process CPU time" value={`${latest.mainCpuSeconds} s`} />
            <Stat label="Database size" value={`${latest.dbSizeMb} MB`} />
            <Stat label="Uptime" value={`${Math.round(latest.uptimeSec / 60)} min`} />
            {Object.entries(latest.rowCounts).map(([t, c]) => (
              <Stat key={t} label={`Rows: ${t}`} value={c.toLocaleString('en-IN')} />
            ))}
          </div>

          {samples.length > 1 && (
            <div className="rounded border bg-gray-50 p-3">
              <p className="mb-1 font-medium">
                Recorded {samples.length} samples ({Math.round((samples.length * SAMPLE_EVERY_MS) / 60000)} min)
              </p>
              <p>
                Peak total memory <b>{peak((s) => s.totalMemoryMb).toFixed(0)} MB</b> · peak main process{' '}
                <b>{peak((s) => s.mainRssMb).toFixed(0)} MB</b> · average CPU{' '}
                <b>{avg((s) => s.cpuPercentTotal).toFixed(1)}%</b> · peak CPU{' '}
                <b>{peak((s) => s.cpuPercentTotal).toFixed(1)}%</b>
              </p>
              <p className="mt-1 text-gray-600">
                Rough hosting hint: a server running only the data layer would need about{' '}
                <b>{suggestedRam} MB RAM</b> and a fraction of one CPU core for a single user, plus disk for
                the database ({latest.dbSizeMb} MB now). Multiple simultaneous users, a managed Postgres
                database and backups are what actually drive the monthly bill.
              </p>
            </div>
          )}

          <div>
            <p className="mb-1 font-medium">Processes</p>
            <table className="w-full text-xs">
              <thead className="text-left uppercase text-gray-500">
                <tr><th className="py-1">Type</th><th>PID</th><th className="text-right">CPU %</th><th className="text-right">Memory (MB)</th></tr>
              </thead>
              <tbody className="divide-y">
                {latest.processes.map((p) => (
                  <tr key={p.pid}>
                    <td className="py-1">{p.type}</td><td>{p.pid}</td>
                    <td className="text-right tabular-nums">{p.cpuPercent}</td>
                    <td className="text-right tabular-nums">{p.memoryMb}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <p className="mb-1 font-medium">Data calls by total time (would-be server work)</p>
            <table className="w-full text-xs">
              <thead className="text-left uppercase text-gray-500">
                <tr>
                  <th className="py-1">Call</th><th className="text-right">Count</th><th className="text-right">Total ms</th>
                  <th className="text-right">Median ms</th><th className="text-right">95th % ms</th><th className="text-right">Max ms</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {latest.channels.slice(0, 15).map((c) => (
                  <tr key={c.channel}>
                    <td className="py-1">{c.channel}</td>
                    <td className="text-right tabular-nums">{c.calls}</td>
                    <td className="text-right tabular-nums">{c.totalMs}</td>
                    <td className="text-right tabular-nums">{c.p50Ms}</td>
                    <td className="text-right tabular-nums">{c.p95Ms}</td>
                    <td className="text-right tabular-nums">{c.maxMs}</td>
                  </tr>
                ))}
                {latest.channels.length === 0 && (
                  <tr><td colSpan={6} className="py-2 text-gray-400">No calls recorded yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-gray-500">{label}</div>
      <div className="font-semibold tabular-nums">{value}</div>
    </div>
  )
}
