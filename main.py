"""CasePilot: small, auditable IT service-desk application.

No external Python packages required. Intended as a deployable local portfolio
reference, not a certified production SaaS. All stored accounts/data are demo.
"""
from __future__ import annotations

import csv
from contextlib import contextmanager
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATABASE = Path(os.environ.get("CASEPILOT_DB", str(ROOT / "casepilot.sqlite3")))
SESSION_TTL = 8 * 60 * 60
PRIORITIES = ("low", "medium", "high", "critical")
STATUSES = ("open", "in_progress", "resolved")
CATEGORIES = ("Access", "Software", "Hardware", "Network", "Billing", "Other")
MAX_BODY = 32_768
PASSWORD_ITERATIONS = 600_000
LOGIN_WINDOW = 60
LOGIN_LIMIT = 8
MAX_SESSIONS = 500
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def due_in(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_password(raw: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS)
    return salt, digest.hex()


def check_password(raw: str, salt: str, digest: str, iterations: int = PASSWORD_ITERATIONS) -> bool:
    check = hashlib.pbkdf2_hmac("sha256", raw.encode(), bytes.fromhex(salt), iterations)
    return hmac.compare_digest(check, bytes.fromhex(digest))


@contextmanager
def connect(path: Path):
    con = sqlite3.connect(path, timeout=6)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=6000")
    try:
        with con:
            yield con
    finally:
        con.close()


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          display_name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','agent')),
          salt TEXT NOT NULL, password_hash TEXT NOT NULL,
          password_iterations INTEGER NOT NULL DEFAULT 600000
        );
        CREATE TABLE IF NOT EXISTS tickets (
          id INTEGER PRIMARY KEY, code TEXT UNIQUE,
          title TEXT NOT NULL, description TEXT NOT NULL, category TEXT NOT NULL,
          priority TEXT NOT NULL CHECK(priority IN ('low','medium','high','critical')),
          status TEXT NOT NULL CHECK(status IN ('open','in_progress','resolved')),
          requester TEXT NOT NULL, assignee_id INTEGER REFERENCES users(id),
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, due_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
        CREATE INDEX IF NOT EXISTS idx_tickets_updated ON tickets(updated_at);
        CREATE INDEX IF NOT EXISTS idx_tickets_recency ON tickets(julianday(updated_at) DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority);
        CREATE TABLE IF NOT EXISTS comments (
          id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
          user_id INTEGER NOT NULL REFERENCES users(id),
          body TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
          id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
          user_id INTEGER NOT NULL REFERENCES users(id),
          action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_comments_ticket ON comments(ticket_id);
        CREATE INDEX IF NOT EXISTS idx_audit_ticket ON audit_events(ticket_id);
        """)
        # Existing ZIP-version databases used 180,000 iterations. Keep them
        # readable and upgrade each hash after a successful login.
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "password_iterations" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN password_iterations INTEGER NOT NULL DEFAULT 180000")
        existing = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if existing:
            return
        demo_users = [
            ("admin", "Morgan Lee", "admin", os.environ.get("CASEPILOT_ADMIN_PASSWORD", "demo1234")),
            ("agent", "Alex Rivera", "agent", os.environ.get("CASEPILOT_AGENT_PASSWORD", "agent1234")),
        ]
        for username, name, role, password in demo_users:
            salt, digest = make_password(password)
            db.execute("INSERT INTO users (username,display_name,role,salt,password_hash,password_iterations) VALUES (?,?,?,?,?,?)",
                       (username, name, role, salt, digest, PASSWORD_ITERATIONS))
        seeds = [
            ("Email access after password reset", "A teammate cannot access their email after a reset.", "Access", "critical", "open", "Olivia Chen", 2, -1),
            ("VPN disconnects intermittently", "Remote connection drops several times a day.", "Network", "high", "in_progress", "Henry Ford", 2, 1),
            ("New employee laptop setup", "Provision standard development equipment.", "Hardware", "medium", "open", "Mila Ramos", None, 3),
            ("Monthly invoice correction", "Customer requested a billing adjustment.", "Billing", "low", "resolved", "Lucas Evans", 2, -2),
            ("CRM reports loading slowly", "Reporting pages time out when filters are applied.", "Software", "high", "in_progress", "Sophie Khan", 2, 0),
            ("Shared folder permissions", "Restore departmental folder access.", "Access", "medium", "resolved", "Nora Silva", 2, 4),
            ("Printer does not respond", "Reception printer does not appear on network.", "Hardware", "low", "open", "Ethan Reed", None, 5),
            ("Onboarding account request", "Create an account for a new teammate.", "Access", "medium", "in_progress", "Ava Martín", 2, 2),
            ("Application update rollback", "Restore service after an unsuccessful deployment.", "Software", "critical", "resolved", "Ben Torres", 1, -3),
        ]
        for title, desc, category, priority, status, requester, assignee, offset in seeds:
            _create_ticket(db, title, desc, category, priority, requester, assignee,
                           status=status, due_at=due_in(offset), creator=1)
        db.commit()


def _create_ticket(db: sqlite3.Connection, title: str, desc: str, category: str,
                   priority: str, requester: str, assignee: int | None,
                   status: str = "open", due_at: str | None = None, creator: int = 1) -> int:
    now = utc_now()
    cur = db.execute("""INSERT INTO tickets (title,description,category,priority,status,requester,
                        assignee_id,created_at,updated_at,due_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (title, desc, category, priority, status, requester, assignee, now, now,
                      due_at or due_in({"critical": 1, "high": 2, "medium": 4, "low": 7}[priority])))
    ticket_id = cur.lastrowid
    db.execute("UPDATE tickets SET code=? WHERE id=?", (f"CP-{ticket_id:04d}", ticket_id))
    db.execute("INSERT INTO audit_events (ticket_id,user_id,action,detail,created_at) VALUES (?,?,?,?,?)",
               (ticket_id, creator, "created", "Ticket opened", now))
    return ticket_id


class APIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def required_text(data: dict, key: str, *, max_len: int, min_len: int = 1) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise APIError(400, f"{key} must be text")
    value = value.strip()
    if not min_len <= len(value) <= max_len:
        raise APIError(400, f"{key} must contain {min_len} to {max_len} characters")
    return value


class DeskServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], db_path: Path):
        if address[0] not in LOCAL_HOSTS:
            passwords = (os.environ.get("CASEPILOT_ADMIN_PASSWORD", ""), os.environ.get("CASEPILOT_AGENT_PASSWORD", ""))
            if any(len(p) < 12 or p in ("demo1234", "agent1234") for p in passwords):
                raise ValueError("Non-local binding requires two custom passwords of at least 12 characters.")
        self.db_path = db_path
        init_db(db_path)
        self.sessions: dict[str, dict] = {}
        self.login_attempts: dict[str, list[float]] = {}
        self.lock = threading.Lock()
        self.local_only = address[0] in LOCAL_HOSTS
        self.secure_cookie = os.environ.get("CASEPILOT_SECURE_COOKIE") == "1"
        self.dummy_salt, self.dummy_hash = make_password(secrets.token_hex(32))
        self.allowed_hosts = set(LOCAL_HOSTS) | {address[0]}
        self.allowed_hosts.update(h.strip().lower() for h in os.environ.get("CASEPILOT_ALLOWED_HOSTS", "").split(",") if h.strip())
        # Inspect stored hashes as well as settings: adding environment variables
        # later must not make a pre-existing demo database externally available.
        with connect(db_path) as db:
            users = db.execute("SELECT * FROM users").fetchall()
        self.demo_access = self.local_only and all(
            any(row["username"] == name and check_password(password, row["salt"], row["password_hash"], row["password_iterations"])
                for row in users) for name, password in (("admin", "demo1234"), ("agent", "agent1234")))
        if not self.local_only:
            for row in users:
                if any(check_password(password, row["salt"], row["password_hash"], row["password_iterations"])
                       for password in ("demo1234", "agent1234")):
                    raise ValueError("Non-local binding refused: database still contains demo credentials. Use a new database with custom passwords.")
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, DeskHandler)

    def prune_sessions(self) -> None:
        # Caller owns self.lock.
        now = time.time()
        self.sessions = {token: item for token, item in self.sessions.items() if item["expires"] > now}

    def check_login_limit(self, client: str) -> None:
        now = time.monotonic()
        with self.lock:
            self.login_attempts = {key: [t for t in times if now - t < LOGIN_WINDOW]
                                   for key, times in self.login_attempts.items() if times and now - times[-1] < LOGIN_WINDOW}
            times = self.login_attempts.setdefault(client, [])
            if len(times) >= LOGIN_LIMIT:
                raise APIError(429, "Too many sign-in attempts. Wait one minute and try again.")
            times.append(now)


class DeskHandler(BaseHTTPRequestHandler):
    server: DeskServer
    server_version = "CasePilot/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)
        self._json_body = None

    def log_message(self, fmt: str, *args):
        if os.environ.get("CASEPILOT_QUIET") != "1":
            super().log_message(fmt, *args)

    def _headers(self, code: int, content_type: str, length: int, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if code == 429:
            self.send_header("Retry-After", str(LOGIN_WINDOW))
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()

    def respond(self, code: int, payload: dict | list, *, extra: dict | None = None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._headers(code, "application/json; charset=utf-8", len(data), extra)
        self.wfile.write(data)

    def binary(self, code: int, contents: bytes, content_type: str, *, extra: dict | None = None):
        self._headers(code, content_type, len(contents), extra)
        self.wfile.write(contents)

    def read_json(self):
        if self._json_body is not None:
            return self._json_body
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise APIError(400, "A single Content-Length is required")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise APIError(400, "Invalid request size")
        if not 1 <= length <= MAX_BODY:
            raise APIError(413, "Invalid or oversized JSON body")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise APIError(400, "Incomplete request body")
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise APIError(415, "JSON content type required")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise APIError(400, "Malformed JSON body")
        if not isinstance(data, dict):
            raise APIError(400, "Expected a JSON object")
        self._json_body = data
        return data

    def session(self) -> dict | None:
        token = self.session_token()
        if not token:
            return None
        with self.server.lock:
            self.server.prune_sessions()
            item = self.server.sessions.get(token)
            if item and item["expires"] > time.time():
                return item
        return None

    def session_token(self) -> str | None:
        match = re.search(r"(?:^|;\s*)casepilot_session=([0-9a-f]{64})(?:;|$)", self.headers.get("Cookie", ""))
        return match.group(1) if match else None

    def cookie(self, token: str, age: int) -> str:
        return f"casepilot_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={age}" + ("; Secure" if self.server.secure_cookie else "")

    def authorize(self, *, modify: bool = False, admin: bool = False) -> dict:
        session = self.session()
        if not session:
            raise APIError(401, "Sign in to continue")
        if admin and session["user"]["role"] != "admin":
            raise APIError(403, "Administrator privileges required")
        if modify and not hmac.compare_digest(self.headers.get("X-CSRF-Token", "").encode(), session["csrf"].encode()):
            raise APIError(403, "Invalid CSRF token")
        return session

    def execute(self, method: str):
        try:
            # Consume bounded JSON before authorization. Otherwise rejecting a
            # POST with an unread TCP body intermittently resets the connection
            # on Windows instead of delivering the intended HTTP error.
            if method in ("POST", "PATCH"):
                self.read_json()
            try:
                host = urlsplit("//" + self.headers.get("Host", "")).hostname
            except ValueError:
                raise APIError(400, "Invalid Host header")
            if not host or host.lower() not in self.server.allowed_hosts:
                raise APIError(403, "Host not allowed")
            origin = self.headers.get("Origin")
            if method in ("POST", "PATCH") and origin:
                try:
                    parsed_origin = urlsplit(origin)
                except ValueError:
                    raise APIError(403, "Invalid Origin header")
                if parsed_origin.scheme not in ("http", "https") or parsed_origin.netloc.lower() != self.headers.get("Host", "").lower():
                    raise APIError(403, "Cross-origin request refused")
            return self.route(method)
        except APIError as exc:
            return self.respond(exc.status, {"error": exc.message})
        except (sqlite3.Error, OSError) as exc:
            self.log_error("Service error: %s", str(exc))
            return self.respond(500, {"error": "Internal service error"})

    def do_GET(self):
        self.execute("GET")

    def do_POST(self):
        self.execute("POST")

    def do_PATCH(self):
        self.execute("PATCH")

    def route(self, method: str):
        parsed = urlsplit(self.path)
        route = parsed.path
        if method == "GET" and route == "/api/health":
            with connect(self.server.db_path) as db:
                db.execute("SELECT 1 FROM tickets LIMIT 1").fetchone()
            return self.respond(200, {"status": "ok", "service": "CasePilot", "version": "1.1.0"})
        if method == "GET" and route == "/api/config":
            return self.respond(200, {"demo_access": self.server.demo_access, "local_only": self.server.local_only})
        if method == "GET" and route in ("/", "/index.html", "/static/app.js", "/static/style.css"):
            rel = {"/": "index.html", "/index.html": "index.html", "/static/app.js": "static/app.js",
                   "/static/style.css": "static/style.css"}[route]
            file = ROOT / rel
            mime = "text/html" if rel.endswith("html") else "text/javascript" if rel.endswith("js") else "text/css"
            return self.binary(200, file.read_bytes(), f"{mime}; charset=utf-8")
        if route == "/api/login" and method == "POST":
            self.server.check_login_limit(self.client_address[0])
            data = self.read_json()
            username = required_text(data, "username", max_len=64)
            # Passwords are opaque; leading/trailing spaces are significant.
            password = data.get("password")
            if not isinstance(password, str) or not 1 <= len(password) <= 256:
                raise APIError(400, "password must contain 1 to 256 characters")
            with connect(self.server.db_path) as db:
                row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            valid = check_password(password, row["salt"] if row else self.server.dummy_salt,
                                   row["password_hash"] if row else self.server.dummy_hash,
                                   row["password_iterations"] if row else PASSWORD_ITERATIONS)
            if not row or not valid:
                raise APIError(401, "Invalid username or password")
            if row["password_iterations"] < PASSWORD_ITERATIONS:
                salt, digest = make_password(password)
                with connect(self.server.db_path) as db:
                    db.execute("UPDATE users SET salt=?,password_hash=?,password_iterations=? WHERE id=?",
                               (salt, digest, PASSWORD_ITERATIONS, row["id"]))
            user = dict(id=row["id"], username=row["username"], name=row["display_name"], role=row["role"])
            token, csrf = secrets.token_hex(32), secrets.token_hex(32)
            with self.server.lock:
                self.server.prune_sessions()
                if len(self.server.sessions) >= MAX_SESSIONS:
                    raise APIError(503, "Session capacity reached. Try again later.")
                existing = self.session_token()
                if existing:
                    self.server.sessions.pop(existing, None)
                self.server.sessions[token] = {"user": user, "csrf": csrf, "expires": time.time() + SESSION_TTL}
            return self.respond(200, {"user": user, "csrf": csrf}, extra={"Set-Cookie":
                self.cookie(token, SESSION_TTL)})

        if method == "GET" and route == "/api/session":
            s = self.authorize()
            return self.respond(200, {"user": s["user"], "csrf": s["csrf"]})
        if method == "POST" and route == "/api/logout":
            self.authorize(modify=True)
            raw = self.headers.get("Cookie", "")
            found = re.search(r"casepilot_session=([0-9a-f]{64})", raw)
            if found:
                with self.server.lock:
                    self.server.sessions.pop(found.group(1), None)
            return self.respond(200, {"ok": True}, extra={"Set-Cookie": self.cookie("", 0)})

        session = self.authorize(modify=method in ("POST", "PATCH"))
        if method == "GET" and route == "/api/users":
            with connect(self.server.db_path) as db:
                users = [dict(r) for r in db.execute("SELECT id,display_name AS name,role FROM users ORDER BY display_name")]
            return self.respond(200, {"users": users})
        if method == "GET" and route == "/api/stats":
            with connect(self.server.db_path) as db:
                counts = dict(db.execute("""SELECT COUNT(*) AS total,
                    COALESCE(SUM(status != 'resolved'),0) AS active,
                    COALESCE(SUM(status = 'resolved'),0) AS resolved,
                    COALESCE(SUM(status != 'resolved' AND due_at < ?),0) AS overdue,
                    COALESCE(SUM(status != 'resolved' AND priority = 'critical'),0) AS critical FROM tickets""", (utc_now(),)).fetchone())
                by_status = dict(db.execute("SELECT status,COUNT(*) FROM tickets GROUP BY status"))
                by_priority = dict(db.execute("SELECT priority,COUNT(*) FROM tickets GROUP BY priority"))
            return self.respond(200, {**counts, "by_status": {s: by_status.get(s, 0) for s in STATUSES},
                                     "by_priority": {p: by_priority.get(p, 0) for p in PRIORITIES}})
        if method == "GET" and route == "/api/activity":
            with connect(self.server.db_path) as db:
                activities = [dict(r) for r in db.execute("""
                    SELECT e.id,e.action,e.detail,e.created_at,t.id AS ticket_id,t.code,t.title,
                           u.display_name AS actor FROM audit_events e
                    JOIN tickets t ON t.id=e.ticket_id JOIN users u ON u.id=e.user_id
                    ORDER BY e.id DESC LIMIT 60""")]
            return self.respond(200, {"items": activities})
        if method == "GET" and route in ("/api/tickets", "/api/export.csv"):
            params = parse_qs(parsed.query)
            status, priority, q = (params.get(k, [""])[0].strip() for k in ("status", "priority", "q"))
            if status and status not in STATUSES or priority and priority not in PRIORITIES:
                raise APIError(400, "Unknown filter value")
            where, args = [], []
            if status:
                where.append("t.status=?")
                args.append(status)
            if priority:
                where.append("t.priority=?")
                args.append(priority)
            if params.get("urgent", [""])[0] == "1":
                where.append("t.status != 'resolved' AND t.priority IN ('critical','high')")
            if q:
                if len(q) > 120:
                    raise APIError(400, "Search is too long")
                where.append("(t.title LIKE ? OR t.code LIKE ? OR t.requester LIKE ? OR t.category LIKE ?)")
                args.extend([f"%{q}%"] * 4)
            where_sql = " WHERE " + " AND ".join(where) if where else ""
            query = """SELECT t.id,t.code,t.title,t.description,t.category,t.priority,t.status,t.requester,
                   t.assignee_id,u.display_name AS assignee,t.created_at,t.updated_at,t.due_at
                   FROM tickets t LEFT JOIN users u ON u.id=t.assignee_id""" + where_sql + " ORDER BY julianday(t.updated_at) DESC, t.id DESC"
            if params.get("urgent", [""])[0] == "1":
                query = query.rsplit(" ORDER BY", 1)[0] + " ORDER BY CASE t.priority WHEN 'critical' THEN 0 ELSE 1 END, t.due_at, t.id"
            page, page_size = 1, 25
            if route == "/api/tickets":
                try:
                    page = int(params.get("page", ["1"])[0])
                    page_size = int(params.get("page_size", ["25"])[0])
                except ValueError:
                    raise APIError(400, "Invalid pagination")
                if not 1 <= page <= 100000 or not 1 <= page_size <= 100:
                    raise APIError(400, "Page must be positive and page_size between 1 and 100")
            with connect(self.server.db_path) as db:
                total = db.execute("SELECT COUNT(*) FROM tickets t" + where_sql, args).fetchone()[0]
                if route == "/api/tickets":
                    rows = [dict(r) for r in db.execute(query + " LIMIT ? OFFSET ?", [*args, page_size, (page-1)*page_size])]
                else:
                    rows = [dict(r) for r in db.execute(query, args)]
            if route == "/api/export.csv":
                stream = io.StringIO()
                writer = csv.DictWriter(stream, fieldnames=["code", "title", "category", "priority", "status", "requester", "assignee", "created_at", "due_at"])
                writer.writeheader()
                def safe_csv(v):
                    text = str(v if v is not None else "")
                    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text
                for r in rows:
                    writer.writerow({k: safe_csv(r[k]) for k in writer.fieldnames})
                return self.binary(200, stream.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8",
                                  extra={"Content-Disposition": "attachment; filename=casepilot-tickets.csv"})
            return self.respond(200, {"tickets": rows, "total": total, "page": page, "page_size": page_size,
                                      "pages": max(1, (total + page_size - 1) // page_size)})
        ticket_match = re.fullmatch(r"/api/tickets/([0-9]{1,18})", route)
        comments_match = re.fullmatch(r"/api/tickets/([0-9]{1,18})/comments", route)
        if method == "GET" and ticket_match:
            ident = int(ticket_match.group(1))
            with connect(self.server.db_path) as db:
                row = db.execute("""SELECT t.*,u.display_name AS assignee FROM tickets t
                                   LEFT JOIN users u ON u.id=t.assignee_id WHERE t.id=?""", (ident,)).fetchone()
                if not row:
                    raise APIError(404, "Ticket not found")
                notes = [dict(r) for r in db.execute("""SELECT c.id,c.body,c.created_at,u.display_name AS author
                                  FROM comments c JOIN users u ON u.id=c.user_id WHERE c.ticket_id=? ORDER BY c.id""", (ident,))]
                log = [dict(r) for r in db.execute("""SELECT e.id,e.action,e.detail,e.created_at,u.display_name AS actor
                                 FROM audit_events e JOIN users u ON e.user_id=u.id WHERE e.ticket_id=? ORDER BY e.id DESC""", (ident,))]
            return self.respond(200, {"ticket": dict(row), "comments": notes, "audit": log})
        if method == "POST" and route == "/api/tickets":
            data = self.read_json()
            if set(data) - {"title", "description", "requester", "category", "priority"}:
                raise APIError(400, "Invalid ticket fields")
            title = required_text(data, "title", max_len=110, min_len=5)
            description = required_text(data, "description", max_len=2000, min_len=8)
            requester = required_text(data, "requester", max_len=100, min_len=2)
            category = data.get("category", "Other")
            priority = data.get("priority", "medium")
            if category not in CATEGORIES or priority not in PRIORITIES:
                raise APIError(400, "Invalid category or priority")
            with connect(self.server.db_path) as db:
                ident = _create_ticket(db, title, description, category, priority, requester, None,
                                       creator=session["user"]["id"])
                db.commit()
            return self.respond(201, {"id": ident, "code": f"CP-{ident:04d}"})
        if method == "PATCH" and ticket_match:
            data = self.read_json()
            permitted = {"status", "priority", "assignee_id"}
            if not data or set(data) - permitted:
                raise APIError(400, "Invalid update fields")
            if "status" in data and data["status"] not in STATUSES:
                raise APIError(400, "Unknown ticket status")
            if "priority" in data and data["priority"] not in PRIORITIES:
                raise APIError(400, "Unknown priority")
            if "assignee_id" in data:
                self.authorize(admin=True)
                if data["assignee_id"] is not None and (not isinstance(data["assignee_id"], int) or isinstance(data["assignee_id"], bool)):
                    raise APIError(400, "Assignee must be a user ID")
            ident = int(ticket_match.group(1))
            with connect(self.server.db_path) as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute("SELECT * FROM tickets WHERE id=?", (ident,)).fetchone()
                if not old:
                    raise APIError(404, "Ticket not found")
                if "assignee_id" in data and data["assignee_id"] is not None:
                    u = db.execute("SELECT id FROM users WHERE id=?", (data["assignee_id"],)).fetchone()
                    if not u:
                        raise APIError(400, "Unknown assignee")
                if "status" in data and old["status"] != data["status"]:
                    next_steps = {"open": ("in_progress",), "in_progress": ("resolved", "open"), "resolved": ("open",)}
                    if data["status"] not in next_steps[old["status"]]:
                        raise APIError(409, "Status change must follow the workflow")
                changes = {k: v for k, v in data.items() if old[k] != v}
                for k, v in changes.items():
                    db.execute(f"UPDATE tickets SET {k}=?, updated_at=? WHERE id=?", (v, utc_now(), ident))
                    db.execute("INSERT INTO audit_events (ticket_id,user_id,action,detail,created_at) VALUES (?,?,?,?,?)",
                       (ident, session["user"]["id"], f"updated_{k}", f"{k}: {old[k]} → {v}", utc_now()))
                db.commit()
            return self.respond(200, {"ok": True, "updated": list(changes)})
        if method == "POST" and comments_match:
            data = self.read_json()
            if set(data) != {"body"}:
                raise APIError(400, "Invalid comment fields")
            body = required_text(data, "body", max_len=1000, min_len=2)
            ident = int(comments_match.group(1))
            with connect(self.server.db_path) as db:
                if not db.execute("SELECT id FROM tickets WHERE id=?", (ident,)).fetchone():
                    raise APIError(404, "Ticket not found")
                db.execute("INSERT INTO comments (ticket_id,user_id,body,created_at) VALUES (?,?,?,?)",
                           (ident, session["user"]["id"], body, utc_now()))
                db.execute("INSERT INTO audit_events (ticket_id,user_id,action,detail,created_at) VALUES (?,?,?,?,?)",
                           (ident, session["user"]["id"], "commented", "Added a comment", utc_now()))
                db.execute("UPDATE tickets SET updated_at=? WHERE id=?", (utc_now(), ident))
                db.commit()
            return self.respond(201, {"ok": True})
        raise APIError(404, "Route not found")


def create_server(db_path: Path, host: str = "127.0.0.1", port: int = 8765) -> DeskServer:
    return DeskServer((host, port), db_path)


if __name__ == "__main__":
    bind = os.environ.get("CASEPILOT_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    if bind not in ("127.0.0.1", "localhost", "::1") and (not os.environ.get("CASEPILOT_ADMIN_PASSWORD") or not os.environ.get("CASEPILOT_AGENT_PASSWORD")):
        raise SystemExit("Non-local binding requires CASEPILOT_ADMIN_PASSWORD and CASEPILOT_AGENT_PASSWORD. Use localhost for default demo credentials.")
    try:
        app = create_server(DATABASE, bind, port)
    except ValueError as exc:
        raise SystemExit(str(exc))
    print(f"CasePilot ready: http://{bind}:{port}")
    if app.demo_access:
        print("Demo login (local): admin / demo1234 | agent / agent1234")
    else:
        print("Sign in with your configured account credentials.")
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping CasePilot")
    finally:
        app.server_close()
