# Fee Register port package

This folder holds what's needed to rebuild the Fee Register desktop app as a sub-program of the host Python web app.

| Path | Contents |
|---|---|
| `PORTING_BRIEF.md` | **The specification.** Read it fully first. |
| `reference/source/` | The complete original TypeScript code: services, DB schema, IPC handlers, React UI and tests |
| `reference/USER_MANUAL.md` | The user-facing description of every feature |
| `reference/PROJECT_STATUS.md` | Implementation notes and the smoke-test flow |
| `reference/original_spec/` | The original requirements, design and tasks (historical; partly outdated) |
| `templates/` | The Word memo template in use, plus the tag reference document |
| `samples/` | An empty backup file showing the backup/restore format |

## Where to put it
Copy this whole folder into the host project, for example as `docs/fee_register_port/`. Keep it out of the deployed package: add it to the build or Docker ignore list if the host has one.

## Prompt to give Kiro in the host project
Paste only the text inside the box below. The rest of this file is notes for you.

```
Read docs/fee_register_port/START_HERE.md and docs/fee_register_port/PORTING_BRIEF.md in full. We are adding the Fee Register as a new sub-program of this app.

Do not write any code yet. Follow Phase 0 in §0 of the brief: study this app's existing sub-programs and the handoff package (the brief plus the full original code in reference/source/), then report back with how you will convert and integrate it, a UI comparison of the two apps, efficiency proposals, your recommendations on the open decisions in §2, and any suggestions.

Do not change existing sub-programs. Do not deploy or push without my go-ahead.
```

Once you approve the analysis, tell Kiro to go ahead. For a large build, ask it to start a **Spec** session so it writes requirements, a design and tasks before coding.

If you put the folder somewhere else, change the two `docs/fee_register_port/` paths at the start of the prompt.
