# Security boundary

CasePilot is a local portfolio demonstration using synthetic data. It is designed to make authentication, permissions, input handling and audit decisions inspectable. It has not received an independent security assessment.

## Implemented controls

- Salted PBKDF2-HMAC-SHA256 with 600,000 iterations. Legacy 180,000-iteration records remain readable and upgrade after successful login.
- Eight-hour, random, server-side sessions with expiry cleanup, rotation on login and a 500-session capacity bound. Cookies are HttpOnly and SameSite=Lax; Secure is enabled explicitly for HTTPS deployments.
- Eight login attempts per source IP per minute. Unknown accounts also perform password verification work. Source IP means the socket peer; forwarded headers are ignored.
- State-changing API requests require a per-session CSRF token. Host and browser Origin checks reject unexpected hosts and cross-origin writes, including login.
- JSON request bodies are limited to 32 KiB and socket reads to ten seconds. Supported payloads are consumed before authorization, avoiding Windows TCP resets on ordinary rejected POST requests.
- Parameterized SQLite queries, validation of enumerations, field lengths, user IDs and ticket transitions, foreign keys and transactional update/audit writes.
- Only administrators can change assignment. Both roles can view all tickets, create requests, update status/priority and add notes. This is a shared internal workspace, with no tenant isolation.
- Dynamic browser content is escaped. CSV cells beginning with spreadsheet formula markers are prefixed to prevent formula interpretation.
- CSP, no-store caching, frame blocking, MIME sniffing prevention and no third-party scripts, fonts or API calls.
- Database files, environment files, runtime logs and local process state are excluded from Git and container context.

## Operational limits

The standard-library HTTP server uses a thread per connection. Login limiting is not a general denial-of-service defense; there is no global connection bound. Sessions and login-attempt counters reset when the process restarts. There is no TLS server, password reset, account editor, persistent session store, multi-tenancy or email service. CSV exports and per-ticket comments/audit history can grow without pagination. The current deadline is fixed when a ticket is created; changing priority does not reschedule it. Audit rows are append-only through the API, but anyone with access to the SQLite file can change them.

Non-local startup requires custom initial passwords of at least 12 characters and rejects demo passwords found in the existing database. Environment variables only initialize a new database; they do not change passwords already stored. The UI displays demo access only when both standard demo accounts are present on a loopback server.

Keep the application on localhost for demonstrations. A public service needs a production HTTP stack, TLS termination, persistent/account-managed authentication, global request/connection limiting, backups, monitoring and a further security review. `CASEPILOT_ALLOWED_HOSTS` configures trusted hostnames; `CASEPILOT_SECURE_COOKIE=1` requires HTTPS in the browser.

## Reference decisions

The password work factor follows the [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), checked on 2026-10-07. Python explicitly cautions that [`http.server` is unsuitable for production](https://docs.python.org/3/library/http.server.html); the documented local-only boundary follows that guidance.

If you find a vulnerability, document the affected route, expected behavior, observed behavior and a reproducible synthetic test. Avoid publishing real credentials, databases or institutional data in an issue or screenshot.
