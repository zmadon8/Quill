import type { PivotResult } from '@/types/ipc'
import { formatMoney } from '@/lib/formatMoney'

/**
 * Inline SVG chart for a pivot result. No chart library, so the bundle stays
 * small and there is no native dependency.
 *   bar     grouped bars (one per column within each row)
 *   stacked bars stacked per row
 *   line    one line per column
 *   area    one filled area per column
 *   pie     one slice per row (row totals)
 * An optional trailing moving average is drawn dashed over bar / line / area.
 */
export type ChartType = 'bar' | 'stacked' | 'line' | 'area' | 'pie'

const COLORS = ['#4f46e5', '#0d9488', '#d97706', '#dc2626', '#2563eb', '#7c3aed', '#059669', '#db2777']

/** Trailing moving average with a window of `n` points (shorter at the start). */
export function movingAverage(values: number[], n: number): number[] {
  if (n <= 1) return values.slice()
  return values.map((_, i) => {
    const from = Math.max(0, i - n + 1)
    const slice = values.slice(from, i + 1)
    return slice.reduce((a, v) => a + v, 0) / slice.length
  })
}

export function PivotChart({
  data,
  type = 'bar',
  maWindow = 0,
}: {
  data: PivotResult
  type?: ChartType
  /** Moving-average window (0 = off). */
  maWindow?: number
}) {
  const rows = data.rows
  const cols = data.columns
  if (rows.length === 0) return null

  const fmt = (v: number) => (data.money ? '₹ ' + formatMoney(v) : String(Math.round(v * 100) / 100))
  const width = 820
  const height = 300

  if (type === 'pie') {
    const slices = rows.map((r) => ({ label: r.label, v: Math.max(0, r.total) }))
    const sum = slices.reduce((a, s) => a + s.v, 0)
    if (sum <= 0) return <p className="text-sm text-gray-500">Nothing to chart.</p>
    const cx = 150
    const cy = 150
    const R = 120
    let angle = -Math.PI / 2
    return (
      <div className="flex flex-wrap items-center gap-6">
        <svg width={300} height={300} role="img" aria-label="Pie chart">
          {slices.map((s, i) => {
            const frac = s.v / sum
            const a2 = angle + frac * Math.PI * 2
            const large = frac > 0.5 ? 1 : 0
            const x1 = cx + R * Math.cos(angle)
            const y1 = cy + R * Math.sin(angle)
            const x2 = cx + R * Math.cos(a2)
            const y2 = cy + R * Math.sin(a2)
            const d =
              frac >= 0.9999
                ? `M ${cx - R} ${cy} a ${R} ${R} 0 1 0 ${2 * R} 0 a ${R} ${R} 0 1 0 ${-2 * R} 0`
                : `M ${cx} ${cy} L ${x1} ${y1} A ${R} ${R} 0 ${large} 1 ${x2} ${y2} Z`
            angle = a2
            return (
              <path key={i} d={d} fill={COLORS[i % COLORS.length]} stroke="#fff">
                <title>{`${s.label}: ${fmt(s.v)} (${(frac * 100).toFixed(1)}%)`}</title>
              </path>
            )
          })}
        </svg>
        <ul className="max-h-72 space-y-1 overflow-y-auto text-xs text-gray-700">
          {slices.map((s, i) => (
            <li key={i} className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
              {s.label} · {fmt(s.v)} ({((s.v / sum) * 100).toFixed(1)}%)
            </li>
          ))}
        </ul>
      </div>
    )
  }

  const padL = 56
  const padR = 12
  const padT = 12
  const padB = 54
  const plotW = width - padL - padR
  const plotH = height - padT - padB

  // Series: one per column, values across rows.
  const series = cols.map((c) => rows.map((r) => r.cells[c.key] ?? 0))
  const stacked = type === 'stacked'
  const maxVal = Math.max(
    1,
    ...(stacked
      ? rows.map((_, ri) => series.reduce((a, s) => a + s[ri], 0))
      : series.flatMap((s) => s)),
  )
  const yFor = (v: number) => padT + plotH - (v / maxVal) * plotH
  const groupW = plotW / rows.length
  const xCenter = (ri: number) => padL + ri * groupW + groupW / 2
  const ticks = 4

  const barW = stacked
    ? Math.max(4, groupW - 10)
    : Math.max(2, (groupW - 8) / cols.length - 2)

  const linePath = (vals: number[]) => vals.map((v, i) => `${i === 0 ? 'M' : 'L'} ${xCenter(i)} ${yFor(v)}`).join(' ')
  const areaPath = (vals: number[]) =>
    `${linePath(vals)} L ${xCenter(vals.length - 1)} ${yFor(0)} L ${xCenter(0)} ${yFor(0)} Z`

  return (
    <div className="overflow-x-auto">
      <svg width={width} height={height} className="min-w-[640px]" role="img" aria-label={`${type} chart`}>
        {Array.from({ length: ticks + 1 }, (_, i) => {
          const v = (maxVal / ticks) * i
          const y = yFor(v)
          return (
            <g key={i}>
              <line x1={padL} y1={y} x2={width - padR} y2={y} stroke="#eee" />
              <text x={padL - 6} y={y + 3} textAnchor="end" fontSize="9" fill="#888">
                {data.money ? formatMoney(v) : Math.round(v * 10) / 10}
              </text>
            </g>
          )
        })}

        {/* Bars */}
        {(type === 'bar' || type === 'stacked') &&
          rows.map((r, ri) => {
            let stackTop = 0
            return (
              <g key={r.key}>
                {cols.map((c, ci) => {
                  const v = series[ci][ri]
                  const h = (v / maxVal) * plotH
                  const x = stacked
                    ? xCenter(ri) - barW / 2
                    : padL + ri * groupW + 4 + ci * (barW + 2)
                  const y = stacked ? yFor(stackTop + v) : padT + plotH - h
                  if (stacked) stackTop += v
                  return (
                    <rect key={c.key} x={x} y={y} width={barW} height={h} fill={COLORS[ci % COLORS.length]}>
                      <title>{`${r.label} · ${c.label}: ${fmt(v)}`}</title>
                    </rect>
                  )
                })}
              </g>
            )
          })}

        {/* Areas + lines */}
        {type === 'area' &&
          series.map((vals, ci) => (
            <path key={`a${ci}`} d={areaPath(vals)} fill={COLORS[ci % COLORS.length]} opacity={0.25} />
          ))}
        {(type === 'line' || type === 'area') &&
          series.map((vals, ci) => (
            <g key={`l${ci}`}>
              <path d={linePath(vals)} fill="none" stroke={COLORS[ci % COLORS.length]} strokeWidth={2} />
              {vals.map((v, i) => (
                <circle key={i} cx={xCenter(i)} cy={yFor(v)} r={3} fill={COLORS[ci % COLORS.length]}>
                  <title>{`${rows[i].label} · ${cols[ci].label}: ${fmt(v)}`}</title>
                </circle>
              ))}
            </g>
          ))}

        {/* Moving average overlay */}
        {maWindow > 1 &&
          type !== 'stacked' &&
          series.map((vals, ci) => (
            <path
              key={`ma${ci}`}
              d={linePath(movingAverage(vals, maWindow))}
              fill="none"
              stroke={cols.length === 1 ? '#111827' : COLORS[ci % COLORS.length]}
              strokeWidth={2}
              strokeDasharray="6 4"
            >
              <title>{`${maWindow}-period moving average`}</title>
            </path>
          ))}

        {/* X labels */}
        {rows.map((r, ri) => (
          <text key={r.key} x={xCenter(ri)} y={height - padB + 14} textAnchor="middle" fontSize="9" fill="#555">
            {r.label.length > 10 ? r.label.slice(0, 9) + '…' : r.label}
          </text>
        ))}
      </svg>

      <div className="mt-2 flex flex-wrap gap-3 px-2 text-xs text-gray-600">
        {cols.length > 1 &&
          cols.map((c, ci) => (
            <span key={c.key} className="inline-flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: COLORS[ci % COLORS.length] }} />
              {c.label}
            </span>
          ))}
        {maWindow > 1 && type !== 'stacked' && (
          <span className="inline-flex items-center gap-1">
            <span className="inline-block h-0 w-5 border-t-2 border-dashed border-gray-900" />
            {maWindow}-period moving average
          </span>
        )}
      </div>
    </div>
  )
}
