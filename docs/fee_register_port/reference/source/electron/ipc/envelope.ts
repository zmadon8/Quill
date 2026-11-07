/**
 * envelope.ts — shared IPC response wrappers.
 *
 * Every IPC handler returns the same { ok, data } | { ok:false, error } shape
 * and maps AppError codes consistently. `wrap` is for synchronous handlers and
 * `wrapAsync` for async ones. Previously these were copy-pasted into each
 * handler file; centralising them removes ~12 near-identical copies and keeps
 * error handling uniform.
 */
import { AppError } from '@/types/ipc'
import type { IPCResponse } from '@/types/ipc'

export function wrap<T>(fn: () => T): IPCResponse<T> {
  try {
    return { ok: true, data: fn() }
  } catch (err) {
    if (err instanceof AppError) return { ok: false, error: err.code, details: err.message }
    return { ok: false, error: 'UNKNOWN', details: (err as Error).message }
  }
}

export async function wrapAsync<T>(fn: () => Promise<T>): Promise<IPCResponse<T>> {
  try {
    return { ok: true, data: await fn() }
  } catch (err) {
    if (err instanceof AppError) return { ok: false, error: err.code, details: err.message }
    return { ok: false, error: 'UNKNOWN', details: (err as Error).message }
  }
}
