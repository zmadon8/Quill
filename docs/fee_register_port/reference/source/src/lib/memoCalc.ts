/** Renderer-side mirror of the backend's memo fee computations (for live preview). */
function round2(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100
}
export function feesAppearances(numAppearances: number, feesPerAppearance: number): number {
  return round2((numAppearances || 0) * (feesPerAppearance || 0))
}
export function feesConferences(numConferences: number, feesPerConference: number): number {
  return round2((numConferences || 0) * (feesPerConference || 0))
}
export function totalFees(fApp: number, fConf: number, misc: number): number {
  return round2(fApp + fConf + (misc || 0))
}
