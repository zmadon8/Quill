/**
 * electron/ipc/payments.ts — IPC handlers for Payments.
 */
import { ipcMain } from 'electron'
import { db } from '@/db/client'
import type { PaymentInput } from '@/types/ipc'
import {
  addPaymentToMemo,
  addPayment,
  addUnaccountedPayment,
  assignPaymentToMemo,
  updatePayment,
  deletePayment,
  listPaymentsForMemo,
  getPayment,
  listPayeesForMatters,
} from '@/services/paymentService'
import { wrap } from './envelope'
import { mutate } from './withHistory'

export function registerPaymentHandlers(): void {
  ipcMain.handle('payments:addToMemo', (_e, memoId: number, input: PaymentInput) =>
    mutate('Add payment', () => addPaymentToMemo(db, memoId, input)),
  )
  ipcMain.handle('payments:add', (_e, input: PaymentInput) =>
    mutate('Add payment', () => addPayment(db, input)),
  )
  ipcMain.handle('payments:addUnaccounted', (_e, input: PaymentInput) =>
    mutate('Add payment', () => addUnaccountedPayment(db, input)),
  )
  ipcMain.handle('payments:assignToMemo', (_e, paymentId: number, memoId: number) =>
    mutate('Reassign payment', () => assignPaymentToMemo(db, paymentId, memoId)),
  )
  ipcMain.handle('payments:update', (_e, id: number, input: PaymentInput) =>
    mutate('Edit payment', () => updatePayment(db, id, input)),
  )
  ipcMain.handle('payments:delete', (_e, id: number) =>
    mutate('Delete payment', () => deletePayment(db, id)),
  )
  ipcMain.handle('payments:get', (_e, id: number) => wrap(() => getPayment(db, id)))
  ipcMain.handle('payments:payeesForMatters', (_e, matterIds: number[]) =>
    wrap(() => listPayeesForMatters(db, matterIds)),
  )
  ipcMain.handle('payments:listForMemo', (_e, memoId: number) =>
    wrap(() => listPaymentsForMemo(db, memoId)),
  )
}
