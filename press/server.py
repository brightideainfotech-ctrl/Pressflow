"""Small threaded HTTP server: JSON API under /api and the static front end.

Run:  python3 -m press.server            (from the project folder)
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import posixpath
import secrets
import sqlite3
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

from . import api, auth, db

STATIC_DIR = os.path.realpath(os.path.join(db.BASE_DIR, "static"))
MAX_BODY = 1_000_000

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                              "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PressApp"
    db_path: str | None = None

    def log_message(self, fmt, *args):  # one short line per request
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    # -- responses ---------------------------------------------------------
    def _send(self, status: int, body: bytes, ctype: str, head_only=False, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _json(self, status: int, payload):
        self._send(status, json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                   "application/json; charset=utf-8", extra={"Cache-Control": "no-store"})

    # -- dispatch ----------------------------------------------------------
    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):
        self._route("HEAD")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")

    def _route(self, method: str):
        parts = urlsplit(self.path)
        if parts.path.startswith("/api/"):
            self._api(method, parts.path.rstrip("/") or "/", dict(parse_qsl(parts.query)))
        elif method in ("GET", "HEAD"):
            self._static(parts.path, head_only=method == "HEAD")
        else:
            self._json(405, {"error": "Method not allowed"})

    def _api(self, method: str, path: str, query: dict):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            return self._json(413, {"error": "Request too large"})
        raw = self.rfile.read(length) if length else b""
        body = None
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"error": "Invalid JSON"})
        auth_header = self.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""

        conn = db.connect(self.db_path)
        try:
            status, payload = api.handle(conn, method, path, query, body, token, self.client_address[0])
            conn.commit()
        except api.ApiError as e:
            conn.rollback()
            status, payload = e.status, {"error": e.message}
        except sqlite3.IntegrityError:
            conn.rollback()
            status, payload = 409, {"error": "That conflicts with existing data"}
        except sqlite3.OperationalError as e:
            conn.rollback()
            traceback.print_exc()
            if "locked" in str(e):
                status, payload = 503, {"error": "The database is busy, please try again"}
            else:
                status, payload = 500, {"error": "Server error"}
        except Exception:
            conn.rollback()
            traceback.print_exc()
            status, payload = 500, {"error": "Something went wrong on the server"}
        finally:
            conn.close()
        self._json(status, payload)

    def _static(self, path: str, head_only=False):
        rel = posixpath.normpath(unquote(path)).lstrip("/") or "index.html"
        full = os.path.realpath(os.path.join(STATIC_DIR, rel))
        if not (full == STATIC_DIR or full.startswith(STATIC_DIR + os.sep)) or not os.path.isfile(full):
            return self._send(404, b"Not found", "text/plain; charset=utf-8", head_only)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json", "application/javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            data = fh.read()
        self._send(200, data, ctype, head_only, extra={"Cache-Control": "no-cache"})


def make_server(host: str, port: int, db_path: str | None = None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"db_path": db_path})
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv


def ensure_first_manager(db_path: str | None) -> str | None:
    """On a brand-new database create the 'admin' manager and return its password."""
    conn = db.connect(db_path)
    try:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return None
        password = os.environ.get("PRESS_ADMIN_PASSWORD") or secrets.token_urlsafe(9)
        auth.create_user(conn, "admin", "Manager", "manager", password)
        conn.commit()
        return password
    finally:
        conn.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Press estimating and job tracking server")
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow other computers on the network")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default=None, help="database file (default: data/press.db)")
    ap.add_argument("--demo", action="store_true", help="load sample customers, quotations, jobs and demo users")
    args = ap.parse_args(argv)

    db.init_db(args.db)
    first_pw = ensure_first_manager(args.db)
    if args.demo:
        from . import demo
        demo.seed(args.db)
    if first_pw:
        print("=" * 60)
        print(" First run: manager account created")
        print("   username: admin")
        print(f"   password: {first_pw}")
        print(" Sign in and change it (top right menu). It is shown only once.")
        print("=" * 60)

    srv = make_server(args.host, args.port, args.db)
    print(f"Serving on http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
