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

