/**
 * electron/ipc/withHistory.ts
 *
 * Wraps a data-mutating IPC handler so a full-database snapshot is recorded
 * BEFORE the mutation runs; that snapshot is what Undo restores. The snapshot
 * is only committed to the undo stack if the mutation succeeds, so a failed op
 * leaves no undo entry.
 *
 * (A whole-database snapshot is used deliberately — see historyService.ts for
 * why partial snapshots are avoided.)
 */
import { db } from '@/db/client'
import type { IPCResponse } from '@/types/ipc'
import { wrap, wrapAsync } from './envelope'
import { captureSnapshot, pushRecorded } from '@/services/historyService'

/** Wraps a synchronous mutation: snapshot-before, commit the undo entry after. */
export function mutate<T>(label: string, fn: () => T): IPCResponse<T> {
  const before = captureSnapshot(db)
  const res = wrap(fn)
  if (res.ok) pushRecorded(db, label, before)
  return res
}

/** Wraps an async mutation: snapshot-before, commit the undo entry after. */
export async function mutateAsync<T>(label: string, fn: () => Promise<T>): Promise<IPCResponse<T>> {
  const before = captureSnapshot(db)
  const res = await wrapAsync(fn)
  if (res.ok) pushRecorded(db, label, before)
  return res
}
