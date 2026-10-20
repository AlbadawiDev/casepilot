# Preventing lost ticket updates

## User story

Two support teammates open the same ticket. One changes its priority while the other changes its status and priority from an old view. Previously, the later request could overwrite the first priority without warning. CasePilot now refuses stale edits and leaves the second teammate's unsaved inputs visible for comparison.

This is a local portfolio feature using synthetic incidents. It does not represent a deployed customer help desk.

## Try it in two browser windows

1. Start the app and sign in as administrator. Open the same ticket in two windows.
2. In window A, change its priority and save.
3. In window B, choose a different priority and save without reopening the ticket.
4. Window B shows that a teammate changed the ticket. Its unsaved selection remains visible; the save button stays disabled. Window A's priority and audit history remain intact.
5. Select **Discard edits and reload latest** in window B. Review the newer values, make a deliberate new change and save.

Internal notes are append-only. Adding a note does not alter the status/priority/assignment revision or invalidate independent field edits. A no-op update does not create events or advance the revision.

## API contract

`GET /api/tickets/:id` includes `ticket.revision`, a persistent positive integer.

A write must send that value with at least one editable field:

```json
{"priority":"high","expected_revision":1}
```

- `200`: the response includes the resulting `revision` and the names of changed fields.
- `428`: the client omitted `expected_revision`. Older API clients must fetch a detail and include this value before saving.
- `400`: the revision is not a positive JSON integer, or update fields are invalid.
- `409` with `code: "ticket_conflict"`: the stored revision differs. No fields, revision or audit events change. Fetch the current detail, review the differences and make an explicit new decision; do not automatically retry against its new revision.
- An invalid workflow transition also returns `409`, without the conflict code. The browser retains its ordinary workflow feedback rather than incorrectly treating it as concurrent editing.

Existing authentication, administrator-only assignment and CSRF requirements still apply. The revision is a consistency token, not an authorization credential.

## Implementation decisions

The server begins an SQLite `IMMEDIATE` transaction before reading the current ticket. Validation, the revision comparison, all field updates, the single revision increment and per-field audit entries share that transaction. The second writer waits for the first transaction and then reads the advanced revision. An audit insertion error rolls back the fields and revision as well.

A monotonic integer avoids collisions between updates with equal timestamps. The migration adds a default revision of 1 to legacy rows without reseeding or deleting existing tickets. Re-running initialization preserves current revisions.

The browser sends the revision from the selected detail. On a conflict it keeps the draft and requires an explicit reload. A delayed response from a previous account or a previously opened detail cannot mark the current ticket as conflicted or close its dialog.

## Evidence and limits

Automated HTTP checks cover a real pair of concurrent requests with one winner, timestamp-collision writes, audit rollback, no-op behavior, independent notes, invalid revision input and legacy migration. Frontend checks cover draft retention, explicit reload/retry, machine-readable errors and a delayed conflict after switching accounts.

See [verification notes](VERIFICATION.md) for executed commands and results. The old screenshots predate this extension; no new browser or remote CI result is claimed by local automated tests. SQLite serializes writes for this small local demo; this is not a claim of distributed concurrency or production-scale load testing.
