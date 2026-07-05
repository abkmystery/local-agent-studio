# Contributing

Thank you for helping make useful AI agents approachable for everyone on
Windows, including people without a software-development background.

## Before opening a pull request

1. Keep the UI in plain language and retain secure defaults.
2. Keep cloud providers optional, explicit, and clearly labelled at the point
   where data leaves the computer.
3. Do not expose inference servers beyond `127.0.0.1`.
4. Require approval for writes and mutating network actions. Email must ask by
   default; its explicit per-node automatic option must stay visible, narrow,
   and covered by execution tests.
5. Add or update tests for behavior changes.
6. Run the validation commands in the README.
7. For installer or desktop-interaction changes, run the packaged backend smoke
   test and UI audit after building:

```powershell
.\scripts\smoke_packaged_backend.ps1
.\scripts\audit_packaged_ui.ps1
```

Prefer one focused change per pull request. Include the Windows version,
hardware summary, engine, model, exact reproduction steps, and relevant local
logs in bug reports. Remove prompts or file contents that should remain private.

Model catalog additions must use a publisher-controlled source, record the
license URL, state commercial and redistribution constraints honestly, and
support hash verification.
