# CasePilot — support operations with an auditable workflow

## Problem

A small remote support team needs one place to track incoming requests, ownership, deadlines and the reason for each change. A queue alone is insufficient when decisions and hand-offs have no history.

## Demonstrated solution

CasePilot provides a shared internal workspace with a dashboard, searchable/paged tickets, a constrained state workflow, administrative assignment, team notes and an activity record. SQLite stores the work between restarts. Filtered CSV export lets a reviewer inspect the queue in a spreadsheet.

The frontend uses HTML, CSS and JavaScript without framework dependencies. The backend uses Python and SQLite, allowing a reviewer to run the demonstration with Python alone. Node is optional for the frontend test suite. The choice favors a small, inspectable local demo; a public service would require a different HTTP deployment stack.

## Engineering decisions to explain in an interview

1. Changes to ticket fields and their audit events share a database transaction. Concurrent updates acquire the write lock before reading the existing state.
2. Agent/admin behavior is checked by the API as well as the interface; disabling a dropdown alone cannot enforce a permission.
3. Session tokens remain in HttpOnly cookies and CSRF tokens accompany mutations. Stored password hashes carry their iteration count so a legacy database can be upgraded without discarding accounts.
4. Tickets are paged by SQL and metrics are aggregated in SQLite. A stale search response cannot replace a newer one in the browser.
5. Imported text is escaped before HTML rendering, and CSV exports neutralize spreadsheet formulas. Tests use synthetic hostile input to verify these boundaries.
6. The verification process exposed an intermittent Windows TCP reset when rejecting an unread POST body. The handler and regression tests now cover that path.

## Evidence

The repository contains 22 HTTP integration tests, four frontend tests, a Windows/Linux CI matrix, launch/stop scripts, security notes and verified screenshots. See [local verification](VERIFICATION.md) for observed results and remaining gaps.

Suggested demo: sign in, inspect SLA metrics, create a synthetic request, assign an agent, move it into investigation, add a note, resolve it, and show the resulting audit history and filtered export. Use the included English script as captions until personal narration is available.

This is an independent portfolio project developed and improved with AI assistance. It uses fictional incidents and demonstrates implementation work; it does not imply paid employment, institutional deployment or a production security certification.
