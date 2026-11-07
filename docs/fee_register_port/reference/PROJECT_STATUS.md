# Fee Register — Project Status & Handoff Notes

_Last updated: during the smoke-test / native-module troubleshooting session._

## Current state

- **All 28 spec tasks are complete** (see `.kiro/specs/fee-register/tasks.md`).
  Only optional sub-task 18.4 (a renderer DOM unit test) is deferred.
- The full app is built: SQLite data layer, service layer, Electron IPC,
  and the complete React UI.
- **The app launches successfully** in Electron (verified — no crash, DB schema
  is created on startup via `src/db/schemaDdl.ts`).
- **110 automated tests pass** when run under the correct Node ABI.

## The one open issue: native-module ABI (better-sqlite3)

`better-sqlite3` is a native module and must be compiled for a specific ABI:

- **The app** runs on Electron (Node ABI 130) → needs the module built for Electron.
- **The test suite** runs on plain Node → needs it built for Node's ABI.

One compiled binary can't serve both, so the project uses auto-switching scripts:

- `npm run dev`   → rebuilds for **Electron**, then launches (use this to run the app)
- `npm run start` → rebuilds for **Electron**, then previews the production build
- `npm run test`  → rebuilds for **Node**, then runs Vitest

**Version pinned to `better-sqlite3@11`** because v11 rebuilds cleanly for
Electron (v13 ships prebuilds that bypass electron-rebuild and segfault the app).

### Node version recommendation

Node **22 LTS** is recommended for development. On Node 23/24 the Vitest runner
can abort at teardown with `Assertion failed: (env) != nullptr` (a better-sqlite3
finalizer bug on newer Node). On Node 22 LTS this does not occur and the suite is
fully clean. The app itself is unaffected by the dev Node version.

## Next step: manual smoke test

With the module built for Electron (`npm run dev`), click through:
1. Firms tab → add a firm (shows Archived until it has a matter)
2. Open firm → add a partner → create a matter (firm becomes Active)
3. Open matter → New Memo → fill fields, watch live totals → Save
4. Memos tab → Payment → record a payment (status moves to Paid)
5. Settings → Upload Word Template (.docx) → then export a memo to Word

## Key implementation notes

- Computed memo fields (fees, total, words, TDS, amount paid, status) are derived
  at read time, never stored.
- `payment_details` is internal — excluded from exports, Feebook, and backups.
- Memo numbers: `YYYY-YY/N`, reset each financial year (1 Apr–31 Mar), never reused.
- Exports are Word and Excel only. There is no PDF export.
- The project folder was renamed from "Fee Register" to "Fee_Register" to fix a
  native-build failure caused by the space in the path.
