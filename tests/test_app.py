"""Black-box HTTP integration tests for core CasePilot workflows."""
from pathlib import Path
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from main import create_server, connect, init_db, make_password, LOGIN_LIMIT, MAX_SESSIONS


class CasePilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = create_server(Path(self.temp.name) / "test.sqlite3", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.cookie = ""
        self.csrf = ""

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(self, path: str, method="GET", payload=None, csrf=True, as_json=True, extra_headers=None):
        headers=dict(extra_headers or {})
        if self.cookie:
            headers["Cookie"]=self.cookie
        if csrf and self.csrf and method!="GET":
            headers["X-CSRF-Token"]=self.csrf
        data=None
        if payload is not None:
            headers["Content-Type"]="application/json"
            data=json.dumps(payload).encode()
        req=Request(self.base + path, headers=headers, data=data, method=method)
        try:
            with urlopen(req,timeout=5) as response:
                raw=response.read()
                status=response.status
                response_headers=dict(response.headers)
        except HTTPError as err:
            with err:
                raw=err.read()
                status=err.code
                response_headers=dict(err.headers)
        if as_json:
            return status,json.loads(raw.decode()),response_headers
        return status,raw,response_headers

    def login(self, role="admin"):
        username,password={"admin":("admin","demo1234"),"agent":("agent","agent1234")}[role]
        code,data,h=self.request("/api/login","POST",{"username":username,"password":password})
        self.assertEqual(code,200)
        self.cookie=h["Set-Cookie"].split(";",1)[0]
        self.csrf=data["csrf"]
        return data

    def test_health_page_and_security_headers(self):
        status,health,h=self.request("/api/health")
        self.assertEqual(status,200)
        self.assertEqual(health["status"],"ok")
        self.assertIn("nosniff",h["X-Content-Type-Options"])
        self.assertIn("default-src 'self'",h["Content-Security-Policy"])
        status,html,_=self.request("/",as_json=False)
        self.assertEqual(status,200)
        self.assertIn(b"casepilot",html)
        status,js,_=self.request("/static/app.js",as_json=False)
        self.assertEqual(status,200)
        self.assertIn(b"addComment",js)
        status,_,_=self.request("/../../etc/passwd")
        self.assertEqual(status,401)  # unknown API paths require authentication first

    def test_requires_login(self):
        code,data,_=self.request("/api/tickets")
        self.assertEqual(code,401)
        self.assertIn("Sign in",data["error"])
        code,_,_=self.request("/api/session")
        self.assertEqual(code,401)

    def test_login_validates_password_and_returns_session(self):
        code,_,_=self.request("/api/login","POST",{"username":"admin","password":"wrong"})
        self.assertEqual(code,401)
        result=self.login()
        self.assertEqual(result["user"]["role"],"admin")
        code,session,_=self.request("/api/session")
        self.assertEqual(code,200)
        self.assertEqual(session["user"]["username"],"admin")
        code,users,_=self.request("/api/users")
        self.assertEqual(code,200)
        self.assertEqual(len(users["users"]),2)

    def test_csrf_and_bad_fields_blocked(self):
        self.login()
        valid={"title":"Test remote access issue", "description":"Remote access is broken today", "requester":"Jamie", "category":"Access", "priority":"high"}
        status,_,_=self.request("/api/tickets","POST",valid,csrf=False)
        self.assertEqual(status,403)
        status,_,_=self.request("/api/tickets","POST",dict(valid, priority="emergency"))
        self.assertEqual(status,400)
        status,_,_=self.request("/api/tickets","POST",dict(valid, title="x"))
        self.assertEqual(status,400)

    def test_ticket_lifecycle_and_audit_trail(self):
        self.login()
        data={"title":"Cannot connect to virtual desktop", "description":"All team members see a timeout", "requester":"Jamie Lee", "category":"Access", "priority":"high"}
        status,created,_=self.request("/api/tickets","POST",data)
        self.assertEqual(status,201)
        tid=created["id"]
        code,full,_=self.request(f"/api/tickets/{tid}")
        self.assertEqual(code,200)
        self.assertEqual(full["ticket"]["status"],"open")
        code,_,_=self.request(f"/api/tickets/{tid}","PATCH",{"status":"resolved"})
        self.assertEqual(code,409)  # no skipping investigation
        code,upd,_=self.request(f"/api/tickets/{tid}","PATCH",{"status":"in_progress", "assignee_id":2})
        self.assertEqual(code,200)
        self.assertIn("assignee_id",upd["updated"])
        code,_,_=self.request(f"/api/tickets/{tid}/comments","POST",{"body":"Checked with request owner."})
        self.assertEqual(code,201)
        code,_,_=self.request(f"/api/tickets/{tid}","PATCH",{"status":"resolved"})
        self.assertEqual(code,200)
        code,full,_=self.request(f"/api/tickets/{tid}")
        self.assertEqual(code,200)
        self.assertEqual(full["ticket"]["status"],"resolved")
        self.assertEqual(len(full["comments"]),1)
        self.assertGreaterEqual(len(full["audit"]),4)
        code,stats,_=self.request("/api/stats")
        self.assertEqual(code,200)
        self.assertEqual(stats["total"],10)
        self.assertGreaterEqual(stats["resolved"],4)

    def test_agent_cannot_reassign_and_can_comment(self):
        self.login("agent")
        code,_,_=self.request("/api/tickets/1","PATCH",{"assignee_id":1})
        self.assertEqual(code,403)
        code,_,_=self.request("/api/tickets/1/comments","POST",{"body":"Investigating this incident."})
        self.assertEqual(code,201)
        code,full,_=self.request("/api/tickets/1")
        self.assertEqual(code,200)
        self.assertEqual(full["comments"][0]["author"],"Alex Rivera")

    def test_search_filters_csv_and_logout(self):
        self.login()
        status,result,_=self.request("/api/tickets?priority=critical&status=open")
        self.assertEqual(status,200)
        self.assertEqual(len(result["tickets"]),1)
        status,result,_=self.request("/api/tickets?q=CP-0001")
        self.assertEqual(status,200)
        self.assertEqual(len(result["tickets"]),1)
        status,raw,headers=self.request("/api/export.csv?status=open",as_json=False)
        self.assertEqual(status,200)
        self.assertIn(b"code,title,category",raw)
        self.assertIn("text/csv",headers["Content-Type"])
        status,_,_=self.request("/api/tickets?status=malformed")
        self.assertEqual(status,400)
        status,_,_=self.request("/api/logout","POST",{})
        self.assertEqual(status,200)
        status,_,_=self.request("/api/session")
        self.assertEqual(status,401)

    def test_query_is_parameterized(self):
        self.login()
        code,result,_=self.request("/api/tickets?q=%27%20OR%201%3D1%20--")
        self.assertEqual(code,200)
        self.assertEqual(result["total"],0)
        code,normal,_=self.request("/api/tickets")
        self.assertEqual(code,200)
        self.assertEqual(normal["total"],9)

    def test_pagination_is_stable_and_csv_exports_all_matches(self):
        self.login()
        code,first,_=self.request("/api/tickets?page=1&page_size=4")
        self.assertEqual(code,200)
        self.assertEqual((first["total"],first["pages"],len(first["tickets"])),(9,3,4))
        code,second,_=self.request("/api/tickets?page=2&page_size=4")
        self.assertEqual(code,200)
        self.assertFalse({t["id"] for t in first["tickets"]}&{t["id"] for t in second["tickets"]})
        for query in ("page=0","page_size=101","page=banana"):
            self.assertEqual(self.request("/api/tickets?"+query)[0],400)
        _,raw,_=self.request("/api/export.csv?page_size=4",as_json=False)
        self.assertEqual(len(raw.decode('utf-8-sig').splitlines()),10)

    def test_expired_session_is_rejected_and_pruned(self):
        self.login()
        token=self.cookie.split('=',1)[1]
        self.server.sessions[token]["expires"]=time.time()-1
        self.assertEqual(self.request("/api/session")[0],401)
        self.assertNotIn(token,self.server.sessions)

    def test_login_rotates_an_existing_session(self):
        self.login()
        old=self.cookie.split('=',1)[1]
        self.login("agent")
        self.assertNotIn(old,self.server.sessions)
        self.assertEqual(len(self.server.sessions),1)

    def test_login_attempt_limit(self):
        for _ in range(LOGIN_LIMIT):
            code,_,_=self.request('/api/login','POST',{'username':'admin','password':'wrong'})
            self.assertEqual(code,401)
        code,_,headers=self.request('/api/login','POST',{'username':'admin','password':'demo1234'})
        self.assertEqual(code,429)
        self.assertEqual(headers['Retry-After'],'60')

    def test_cross_origin_and_untrusted_host_are_blocked(self):
        code,_,_=self.request('/api/login','POST',{'username':'admin','password':'demo1234'},extra_headers={'Origin':'https://attacker.example'})
        self.assertEqual(code,403)
        code,_,_=self.request('/api/health',extra_headers={'Host':'attacker.example'})
        self.assertEqual(code,403)
        self.login()
        self.assertEqual(self.request('/api/tickets/1','PATCH',{'priority':'critical'},csrf=False,extra_headers={'X-CSRF-Token':'invalid'})[0],403)

    def test_unknown_fields_and_large_ticket_ids_do_not_crash(self):
        self.login()
        data={'title':'A support request','description':'A detailed support issue','requester':'Jamie','status':'resolved'}
        self.assertEqual(self.request('/api/tickets','POST',data)[0],400)
        self.assertEqual(self.request('/api/tickets/'+('9'*80))[0],404)
        self.assertEqual(self.request('/api/tickets/1','PATCH',{'assignee_id':True})[0],400)
        self.assertEqual(self.request('/api/tickets/1','PATCH',{'assignee_id':9999})[0],400)

    def test_csv_formula_injection_is_neutralized(self):
        self.login()
        payload={'title':'=HYPERLINK("https://example.com")','description':'Synthetic export security test','requester':'@SUM(1,2)','priority':'high'}
        self.assertEqual(self.request('/api/tickets','POST',payload)[0],201)
        _,raw,_=self.request('/api/export.csv',as_json=False)
        import csv, io
        row=next(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        self.assertTrue(row['title'].startswith("'="))
        self.assertTrue(row['requester'].startswith("'@"))

    def test_secure_cookie_and_demo_config(self):
        self.assertTrue(self.request('/api/config')[1]['demo_access'])
        self.server.secure_cookie=True
        _,_,headers=self.request('/api/login','POST',{'username':'admin','password':'demo1234'})
        self.assertIn('; Secure',headers['Set-Cookie'])
        self.assertIn('HttpOnly',headers['Set-Cookie'])

    def test_nonlocal_binding_refuses_existing_demo_database(self):
        with patch.dict('os.environ',{'CASEPILOT_ADMIN_PASSWORD':'a-custom-password-123','CASEPILOT_AGENT_PASSWORD':'another-custom-password-456'}):
            with self.assertRaisesRegex(ValueError,'still contains demo credentials'):
                create_server(self.server.db_path,host='0.0.0.0',port=0)

    def test_sqlite_integrity_and_foreign_keys(self):
        self.login()
        with connect(self.server.db_path) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(list(db.execute('PRAGMA foreign_key_check')),[])
            self.assertTrue(all(r[0]==600000 for r in db.execute('SELECT password_iterations FROM users')))

    def test_session_capacity_is_bounded(self):
        self.server.sessions={str(i):{'expires':time.time()+500} for i in range(MAX_SESSIONS)}
        self.assertEqual(self.request('/api/login','POST',{'username':'admin','password':'demo1234'})[0],503)

    def test_note_updates_ticket_recency(self):
        self.login()
        with connect(self.server.db_path) as db:
            # A legacy second-resolution timestamp must sort before a later
            # update in that same second, without relying on wall-clock speed.
            db.execute("UPDATE tickets SET updated_at='2030-01-01T00:00:00Z'")
        with patch('main.utc_now',return_value='2030-01-01T00:00:00.250Z'):
            self.assertEqual(self.request('/api/tickets/1/comments','POST',{'body':'The request owner confirmed the symptom.'})[0],201)
        self.assertEqual(self.request('/api/tickets')[1]['tickets'][0]['id'],1)

    def test_legacy_database_migration_and_hash_upgrade(self):
        import hashlib
        legacy=Path(self.temp.name)/'legacy.sqlite3'
        salt='a'*32
        digest=hashlib.pbkdf2_hmac('sha256',b'demo1234',bytes.fromhex(salt),180000).hex()
        with connect(legacy) as db:
            db.execute('CREATE TABLE users (id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,display_name TEXT NOT NULL,role TEXT NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL)')
            db.execute('INSERT INTO users VALUES (1,?,?,?,?,?)',('admin','Legacy demo','admin',salt,digest))
        init_db(legacy)
        self.server.db_path=legacy
        self.login()
        with connect(legacy) as db:
            row=db.execute('SELECT password_iterations,password_hash FROM users WHERE id=1').fetchone()
            self.assertEqual(row['password_iterations'],600000)
            self.assertNotEqual(row['password_hash'],digest)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)

    def test_password_spaces_are_preserved(self):
        password='  custom password  '
        salt,digest=make_password(password)
        with connect(self.server.db_path) as db:
            db.execute('UPDATE users SET salt=?,password_hash=? WHERE username=?',(salt,digest,'admin'))
        self.assertEqual(self.request('/api/login','POST',{'username':'admin','password':password.strip()})[0],401)
        self.assertEqual(self.request('/api/login','POST',{'username':'admin','password':password})[0],200)


if __name__ == "__main__":
    unittest.main()
