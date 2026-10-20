# Verified local behavior — 2026-10-07

Environment: Windows, Python 3.14.3, Node 24.14.0. Application runtime uses only Python's standard library; no third-party dependency installation was needed.

The original package had eight HTTP integration tests. An initial execution produced an intermittent Windows `ConnectionAbortedError` during a POST rejected for missing CSRF; a subsequent baseline run passed. The handler previously answered before consuming that request body. The revised handler consumes bounded JSON before authorization, and the expanded tests exercise the same rejected request.

## Automated checks

```powershell
.\scripts\check.ps1
```

This compiles the Python source, checks JavaScript syntax, runs four frontend tests and runs 22 HTTP integration tests with ResourceWarnings treated as errors. These cover security, lifecycle, storage integrity, migration, pagination and UI behavior. Test databases are temporary and synthetic.

GitHub Actions is configured for Python 3.11/3.14 on Windows/Linux. The [main run for commit `69f2b796`](https://github.com/AlbadawiDev/casepilot/actions/runs/37700806418) completed successfully after publication. The later frontend regression work below is validated separately.

## Async-response regression checks — 2026-10-08

Environment: Linux, Python 3.12.14 and Node 24.19.0. Four new tests first failed against the published frontend: an older ticket detail replaced the latest selection, old detail/dashboard responses repopulated the UI after changing accounts, and a delayed 401 from the previous session cleared the new session.

The frontend now records which sign-in started each read and discards results from superseded sessions. Independent request counters protect ticket details, dashboards and activity lists against responses arriving out of order. A fifth failing regression revealed that a delayed logout response could also clear a newer sign-in; logout now uses the same session guard. Current-session 401 responses still return the user to sign-in.

After the correction, **10 frontend tests and all 22 HTTP integration tests passed**, with ResourceWarnings treated as errors. JavaScript syntax and `git diff --check` also passed. Tests use controlled deferred promises to reproduce these races without timing sleeps. These are automated source-level regression checks; no new browser walkthrough is claimed for this change.

## Browser walkthrough

An actual browser session verified administrator sign-in, dashboard metrics, creation of `CP-0010`, administrative assignment, progression from open to in progress, a persisted internal note and resolution. The request explicitly identifies its content as synthetic. Screenshots were captured from the running app; the audited dashboard is shown in the README.

Desktop and 390×844 mobile layouts were inspected. The mobile page keeps horizontal scrolling within the ticket table; the page itself does not overflow. The hidden mobile sidebar is excluded from keyboard navigation. Dialogs have accessible labels, status controls reflect allowed workflow transitions, and pending submissions disable their buttons.

The starter was executed with `-NoBrowser`, and `/api/health` returned `status: ok`, version `1.1.0`. A separate start/stop test checks the Windows launcher and stop script. Runtime logs and database contents remain local and ignored by Git.

## Remaining validation

Docker CLI is installed, but the Docker daemon was not running; no container build/runtime result is claimed. The original screenshots and original silent MP4 remain in the project for provenance, but the MP4 predates these corrections. Review or re-record it before presenting the current version. This project's video is separate from the UDO thesis-system demonstration.


## CSV import extension — 2026-10-12

Environment: Linux, Python 3.12.14, Node 24.19.0. This extension was developed with coding-assistant support for the local portfolio demo. It does not use customer or university data.

Executed locally:

```bash
CASEPILOT_QUIET=1 python -W error::ResourceWarning -m unittest discover -s tests -v
node --check static/app.js
node --test tests/frontend.test.cjs
python -m py_compile main.py
git diff --check
```

Results: **29 HTTP integration tests passed in 31.512 seconds**, including seven new import tests. **15 frontend tests passed** with no failures. Python compilation, JavaScript syntax and the diff whitespace check passed.

The import regression tests verify:

- Anonymous users and support agents cannot preview or commit imports; administrator requests still require CSRF.
- A batch with multiple invalid fields returns line-specific feedback and creates no tickets.
- Quoted commas/newlines and a UTF-8 BOM are accepted. Imported spreadsheet formula cells remain protected in CSV exports.
- Each imported ticket starts open/unassigned and records the authenticated administrator in its audit history.
- A forced database error on the second ticket rolls back tickets, audit events and the batch receipt. A subsequent retry succeeds.
- Two concurrent commits produce one batch and return the same ticket IDs.
- The batch receipt survives a server restart. Header reordering, BOM and line-ending changes do not create duplicate tickets.
- Invalid headers/quotes/nulls/Unicode, a changed preview, extra fields, more than 50 rows and oversized CSV are rejected.
- Browser-source tests verify escaped preview markup, stale preview/account isolation, unchanged-preview/admin checks and preservation of the hash after a failed network request.

The Playwright JavaScript library is present, but this runtime has no browser binary. The standard Chromium download returned zero-byte/truncated archives and was stopped. Therefore this extension has **no new browser walkthrough, desktop/mobile layout verification or verified UI screenshot**. The older screenshots and walkthrough above describe the earlier app version. Windows launchers, Docker runtime and remote CI were not rerun for this local extension.


## Concurrent ticket edits - 2026-10-20

Environment: Linux, Python 3.12.14, Node 24.19.0. Portfolio extension developed with coding-assistant support and synthetic data.

Executed locally:

```bash
CASEPILOT_QUIET=1 python -W error::ResourceWarning -m unittest discover -s tests -v
node --check static/app.js
node --test tests/frontend.test.cjs
python -m py_compile main.py
git diff --check
```

Results: **35 HTTP integration tests passed in 54.382 seconds** and **19 frontend tests passed**, with no failures. Python compilation, JavaScript syntax and the diff whitespace check passed.

Six new HTTP checks verify mandatory positive revision input, equal-timestamp stale writes, one winner across two barrier-synchronized HTTP requests, field/revision/audit rollback on a forced database error, no-op and independent-note behavior, and legacy migration without reseeding. Four new frontend checks verify conflict-code propagation, draft retention and explicit reload/retry, an obsolete conflict after account switching, and an in-flight note that completes after a conflict without discarding field edits or a newer note draft.

No new browser walkthrough, remote CI result, Windows launcher test or production-load result is claimed here. Earlier screenshots describe earlier versions. The API now requires `expected_revision` for ticket PATCH requests; see [the contract and demonstration](CONCURRENT_EDITS.md).
