"""REST API: routing table and handlers. HTTP plumbing lives in server.py."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta

from . import auth, db, estimator


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ---------------------------------------------------------------- constants

STAGES = [
    ("approved", "Approved"),
    ("design_proof", "Design / Proof"),
    ("plates", "Plates"),
    ("printing", "Printing"),
    ("finishing", "Binding / Finishing"),
    ("ready", "Ready"),
    ("delivered", "Delivered"),
    ("billed", "Billed"),
]
EXTRA_STAGES = [("cancelled", "Cancelled")]
ALL_STAGE_KEYS = [k for k, _ in STAGES + EXTRA_STAGES]
CLOSED_STAGES = ("delivered", "billed", "cancelled")

# Which job stages each role may move a job into.
STAGE_PERMS = {
    "manager": set(ALL_STAGE_KEYS),
    "desk": {"approved", "design_proof", "ready", "delivered", "billed", "cancelled"},
    "superintendent": {"approved", "design_proof", "plates", "printing", "finishing", "ready"},
    "operator": {"design_proof", "plates", "printing", "finishing", "ready"},
}
MONEY_ROLES = ("manager", "desk")
JOB_MONEY_FIELDS = ("total", "gst_pct", "hsn", "advance", "receipt_no", "bill_no", "balance")

QUOTE_STATUSES = ("draft", "sent", "accepted", "rejected", "converted")
QUOTE_TRANSITIONS = {
    "draft": {"sent", "accepted", "rejected"},
    "sent": {"draft", "accepted", "rejected"},
    "accepted": {"sent", "rejected"},
    "rejected": {"draft"},
    "converted": set(),
}
QUOTE_EDITABLE = ("draft", "sent", "rejected")

ANY = "any"
ALL_STAFF = ("manager", "desk", "superintendent", "operator")
OFFICE = ("manager", "desk")
MANAGER = ("manager",)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Ctx:
    def __init__(self, conn, user, params, query, body, token, addr):
        self.conn, self.user, self.params = conn, user, params
        self.query, self.body, self.token, self.addr = query, body, token, addr


ROUTES: list = []
THROTTLE = auth.LoginThrottle()


def route(method: str, pattern: str, roles=ANY):
    rx = re.compile("^" + pattern + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn, roles))
        return fn

    return deco


def handle(conn, method, path, query, body, token, addr):
    """Returns (status, payload). Raises ApiError for expected failures."""
    path_matched = False
    for m, rx, fn, roles in ROUTES:
        mo = rx.match(path)
        if not mo:
            continue
        path_matched = True
        if m != method:
            continue
        user = None
        if roles is not None:
            user = auth.user_for_token(conn, token)
            if not user:
                raise ApiError(401, "Please sign in")
            if roles != ANY and user["role"] not in roles:
                raise ApiError(403, "You do not have permission to do this")
        if method in ("POST", "PUT") and not isinstance(body, dict):
            raise ApiError(400, "Request body must be a JSON object")
        out = fn(Ctx(conn, user, mo.groups(), query, body or {}, token, addr))
        if isinstance(out, tuple):
            return out
        return 200, out
    raise ApiError(405 if path_matched else 404, "Not allowed" if path_matched else "Not found")


# ---------------------------------------------------------------- validation

def clean(data: dict, fields, partial=False) -> dict:
    out = {}
    for f in fields:
        name, kind, required = f[0], f[1], f[2]
        default = f[3] if len(f) > 3 else None
        label = name.replace("_", " ").capitalize()
        if name not in data or data[name] is None:
            if partial:
                continue
            if required:
                raise ApiError(422, f"{label} is required")
            v = default
            if v is None:
                v = "" if kind in ("str", "date") or kind.startswith("choice:") else 0
            out[name] = v
            continue
        v = data[name]
        if kind == "str":
            v = str(v).strip()
            if len(v) > 2000:
                raise ApiError(422, f"{label} is too long")
            if required and not v:
                raise ApiError(422, f"{label} is required")
        elif kind in ("int", "float", "pfloat"):
            try:
                x = float(v)
            except (TypeError, ValueError):
                raise ApiError(422, f"{label} must be a number") from None
            if math.isnan(x) or math.isinf(x) or x < 0 or x > 1e9:
                raise ApiError(422, f"{label} is out of range")
            if kind == "pfloat" and x <= 0:
                raise ApiError(422, f"{label} must be greater than zero")
            v = int(round(x)) if kind == "int" else x
        elif kind == "bool":
            v = 1 if v in (True, 1, "1", "true", "True") else 0
        elif kind == "date":
            v = str(v).strip()
            if v and not DATE_RE.match(v):
                raise ApiError(422, f"{label} must be a date")
            if v:
                try:
                    datetime.strptime(v, "%Y-%m-%d")
                except ValueError:
                    raise ApiError(422, f"{label} is not a valid date") from None
            if required and not v:
                raise ApiError(422, f"{label} is required")
        elif kind.startswith("choice:"):
            choices = kind[7:].split(",")
            if v not in choices:
                raise ApiError(422, f"{label} must be one of: {', '.join(choices)}")
        out[name] = v
    return out


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def need(row, what="Record"):
    if row is None:
        raise ApiError(404, f"{what} not found")
    return row


# ---------------------------------------------------------------- auth

@route("POST", "/api/login", roles=None)
def login(c: Ctx):
    username = str(c.body.get("username") or "").strip()
    password = str(c.body.get("password") or "")
    if THROTTLE.blocked(c.addr, username):
        raise ApiError(429, "Too many failed attempts. Please wait a few minutes and try again.")
    u = one(c.conn, "SELECT * FROM users WHERE username=? AND active=1", (username,))
    # Verify even for unknown users so response time does not reveal which names exist.
    salt, hashed = (u["salt"], u["pw_hash"]) if u else ("00" * 16, "00" * 32)
    good = auth.verify_password(password, salt, hashed) and u is not None
    if not good:
        THROTTLE.failed(c.addr, username)
        raise ApiError(401, "Wrong username or password")
    THROTTLE.ok(c.addr, username)
    token = auth.start_session(c.conn, u["id"])
    return {"token": token, "user": {k: u[k] for k in ("id", "username", "name", "role")}}


@route("POST", "/api/logout")
def logout(c: Ctx):
    auth.end_session(c.conn, c.token)
    return {"ok": True}


@route("POST", "/api/me/password")
def change_password(c: Ctx):
    cur, new = str(c.body.get("current") or ""), str(c.body.get("new") or "")
    u = one(c.conn, "SELECT * FROM users WHERE id=?", (c.user["id"],))
    if not auth.verify_password(cur, u["salt"], u["pw_hash"]):
        raise ApiError(422, "Current password is wrong")
    if len(new) < auth.MIN_PASSWORD:
        raise ApiError(422, f"New password must be at least {auth.MIN_PASSWORD} characters")
    salt, digest = auth.hash_password(new)
    c.conn.execute("UPDATE users SET salt=?, pw_hash=? WHERE id=?", (salt, digest, u["id"]))
    auth.end_all_sessions(c.conn, u["id"], keep_token=c.token)
    return {"ok": True}


# ---------------------------------------------------------------- settings / bootstrap

NUMERIC_SETTINGS = {"gst_pct": (0, 50), "default_margin_pct": (0, 1000), "wastage_pct": (0, 100),
                    "bleed_in": (0, 5), "gripper_in": (0, 10), "quote_valid_days": (1, 365)}
TEXT_SETTINGS = ("company_name", "company_address", "company_phone", "company_email", "company_gstin",
                 "hsn_default", "quote_terms")
FLAG_SETTINGS = ("round_to_rupee", "rates_confirmed")


def get_settings(conn) -> dict:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM settings")}


@route("GET", "/api/settings")
def settings_get(c: Ctx):
    return get_settings(c.conn)


@route("PUT", "/api/settings", roles=MANAGER)
def settings_put(c: Ctx):
    for k, v in c.body.items():
        if k in NUMERIC_SETTINGS:
            lo, hi = NUMERIC_SETTINGS[k]
            try:
                x = float(v)
            except (TypeError, ValueError):
                raise ApiError(422, f"{k.replace('_', ' ').capitalize()} must be a number") from None
            if math.isnan(x) or not (lo <= x <= hi):
                raise ApiError(422, f"{k.replace('_', ' ').capitalize()} must be between {lo} and {hi}")
            val = f"{x:g}"
        elif k in TEXT_SETTINGS:
            val = str(v).strip()[:2000]
        elif k in FLAG_SETTINGS:
            val = "1" if v in (True, 1, "1", "true") else "0"
        else:
            continue
        c.conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, val))
    return get_settings(c.conn)


def load_masters(conn) -> dict:
    papers = {r["id"]: r for r in rows(conn, "SELECT * FROM papers")}
    for r in papers.values():
        r["sizes"] = []
    for sz in rows(conn, "SELECT * FROM paper_sizes ORDER BY width_in*height_in"):
        if sz["paper_id"] in papers:
            papers[sz["paper_id"]]["sizes"].append(sz)
    return {
        "papers": papers,
        "machines": {r["id"]: r for r in rows(conn, "SELECT * FROM machines")},
        "plates": {r["id"]: r for r in rows(conn, "SELECT * FROM plate_types")},
        "finishing": {r["id"]: r for r in rows(conn, "SELECT * FROM finishing")},
    }


@route("GET", "/api/bootstrap")
def bootstrap(c: Ctx):
    out = {
        "user": c.user,
        "settings": get_settings(c.conn),
        "stages": [{"key": k, "label": v} for k, v in STAGES + EXTRA_STAGES],
        "my_stages": sorted(STAGE_PERMS[c.user["role"]], key=ALL_STAGE_KEYS.index),
        "masters": {},
    }
    if c.user["role"] in OFFICE:
        out["masters"] = {
            "papers": rows(c.conn, "SELECT * FROM papers WHERE active=1 ORDER BY name"),
            "machines": rows(c.conn, "SELECT * FROM machines WHERE active=1 ORDER BY name"),
            "plates": rows(c.conn, "SELECT * FROM plate_types WHERE active=1 ORDER BY name"),
            "finishing": rows(c.conn, "SELECT * FROM finishing WHERE active=1 ORDER BY group_name, name"),
        }
    return out


# ---------------------------------------------------------------- master data CRUD

MASTERS = {
    "papers": ("papers", "name", OFFICE, MANAGER, [
        ("name", "str", True), ("gsm", "int", False), ("width_in", "float", False),
        ("height_in", "float", False), ("pricing", "choice:ream,kg", False, "ream"), ("weight_mode", "choice:auto,table", False, "auto"),
        ("rate_per_ream", "float", False), ("rate_per_kg", "float", False), ("active", "bool", False, 1)]),
    "machines": ("machines", "name", OFFICE, MANAGER, [
        ("name", "str", True), ("kind", "choice:offset,web,digital,riso", False, "offset"),
        ("rate_per_1000", "float", True), ("per_color", "bool", False, 1), ("setup_per_plate", "float", False),
        ("min_charge", "float", False), ("makeready_sheets", "int", False), ("needs_plate", "bool", False, 1),
        ("max_colors", "int", False), ("active", "bool", False, 1)]),
    "plates": ("plate_types", "name", OFFICE, MANAGER, [
        ("name", "str", True), ("rate", "float", True), ("active", "bool", False, 1)]),
    "finishing": ("finishing", "group_name, name", OFFICE, MANAGER, [
        ("name", "str", True), ("group_name", "str", False, "Finishing"),
        ("basis", "choice:per_copy,per_1000,per_sqft,per_unit,job,per_1000_sheets,per_1000_leaves", True),
        ("rate", "float", True), ("min_charge", "float", False), ("active", "bool", False, 1)]),
    "customers": ("customers", "name", OFFICE, OFFICE, [
        ("name", "str", True), ("contact_person", "str", False), ("phone1", "str", False), ("phone2", "str", False),
        ("email", "str", False), ("address", "str", False), ("pin", "str", False), ("gstin", "str", False),
        ("notes", "str", False), ("active", "bool", False, 1)]),
}


def _check_paper(v: dict):
    w, hh = v.get("width_in") or 0, v.get("height_in") or 0
    if (w > 0) != (hh > 0):
        raise ApiError(422, "Enter both the width and the height, or leave both blank")
    if v.get("pricing") != "kg" and not (w > 0 and hh > 0):
        raise ApiError(422, "Sheet width and height are required for paper priced by the ream")
    if v.get("pricing") == "kg":
        if not v.get("gsm") and v.get("weight_mode") != "table":
            raise ApiError(422, "Paper priced per kg needs its GSM (weight of one square metre), or your own weight table")
        if not v.get("rate_per_kg"):
            raise ApiError(422, "Enter the rate per kg")
    elif not v.get("rate_per_ream"):
        raise ApiError(422, "Enter the rate per ream")


CHECKS = {"papers": _check_paper}


@route("GET", r"/api/papers/(\d+)/sizes", roles=OFFICE)
def paper_sizes_get(c: Ctx):
    pid = int(c.params[0])
    need(one(c.conn, "SELECT id FROM papers WHERE id=?", (pid,)), "Paper")
    return rows(c.conn, "SELECT id,name,width_in,height_in,kg_per_100 FROM paper_sizes WHERE paper_id=? ORDER BY width_in*height_in", (pid,))


@route("PUT", r"/api/papers/(\d+)/sizes", roles=MANAGER)
def paper_sizes_put(c: Ctx):
    """Replace the paper's table of 'kg needed per 100 sheets' for each size."""
    pid = int(c.params[0])
    need(one(c.conn, "SELECT id FROM papers WHERE id=?", (pid,)), "Paper")
    items = c.body.get("sizes")
    if not isinstance(items, list) or len(items) > 100:
        raise ApiError(422, "Send the list of sizes")
    clean_rows, seen = [], []
    for it in items:
        if not isinstance(it, dict):
            raise ApiError(422, "Each size needs a name, width, height and kg")
        v = clean(it, [("name", "str", False), ("width_in", "pfloat", True), ("height_in", "pfloat", True), ("kg_per_100", "pfloat", True)])
        key = tuple(sorted((round(v["width_in"], 2), round(v["height_in"], 2))))
        if key in seen:
            raise ApiError(422, f"The size {v['width_in']:g} x {v['height_in']:g} in is listed twice")
        seen.append(key)
        clean_rows.append(v)
    c.conn.execute("DELETE FROM paper_sizes WHERE paper_id=?", (pid,))
    for v in clean_rows:
        c.conn.execute("INSERT INTO paper_sizes(paper_id,name,width_in,height_in,kg_per_100) VALUES(?,?,?,?,?)",
                       (pid, v["name"], v["width_in"], v["height_in"], v["kg_per_100"]))
    return paper_sizes_get(c)


def _register_master(name, table, order, read_roles, write_roles, fields):
    cols = [f[0] for f in fields]

    @route("GET", f"/api/{name}", roles=read_roles)
    def list_(c: Ctx, table=table, order=order):
        sql = f"SELECT * FROM {table}"
        if not (c.query.get("all") == "1" and c.user["role"] in write_roles):
            sql += " WHERE active=1"
        return rows(c.conn, sql + f" ORDER BY {order} COLLATE NOCASE")

    @route("POST", f"/api/{name}", roles=write_roles)
    def create(c: Ctx, table=table, fields=fields, cols=cols):
        v = clean(c.body, fields)
        if name in CHECKS:
            CHECKS[name](v)
        cur = c.conn.execute(
            f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [v[k] for k in cols])
        return 201, one(c.conn, f"SELECT * FROM {table} WHERE id=?", (cur.lastrowid,))

    @route("PUT", rf"/api/{name}/(\d+)", roles=write_roles)
    def update(c: Ctx, table=table, fields=fields):
        rid = int(c.params[0])
        need(one(c.conn, f"SELECT id FROM {table} WHERE id=?", (rid,)))
        v = clean(c.body, fields, partial=True)
        if name in CHECKS:
            CHECKS[name]({**one(c.conn, f"SELECT * FROM {table} WHERE id=?", (rid,)), **v})
        if v:
            c.conn.execute(f"UPDATE {table} SET {','.join(k + '=?' for k in v)} WHERE id=?", [*v.values(), rid])
        return one(c.conn, f"SELECT * FROM {table} WHERE id=?", (rid,))

    @route("DELETE", rf"/api/{name}/(\d+)", roles=write_roles)
    def delete(c: Ctx, table=table, name=name):
        rid = int(c.params[0])
        need(one(c.conn, f"SELECT id FROM {table} WHERE id=?", (rid,)))
        if name == "customers":
            used = one(c.conn, "SELECT (SELECT COUNT(*) FROM quotations WHERE customer_id=?)+"
                               "(SELECT COUNT(*) FROM jobs WHERE customer_id=?) AS n", (rid, rid))["n"]
            if not used:
                c.conn.execute("DELETE FROM customers WHERE id=?", (rid,))
                return {"deleted": True}
        # Rates may be referenced by saved quotations, so they are switched off, not removed.
        c.conn.execute(f"UPDATE {table} SET active=0 WHERE id=?", (rid,))
        return {"deleted": False, "deactivated": True}


for _n, (_t, _o, _r, _w, _f) in MASTERS.items():
    _register_master(_n, _t, _o, _r, _w, _f)


# ---------------------------------------------------------------- users

@route("GET", "/api/users", roles=MANAGER)
def users_list(c: Ctx):
    return rows(c.conn, "SELECT id,username,name,role,department,active FROM users ORDER BY active DESC, name COLLATE NOCASE")


@route("POST", "/api/users", roles=MANAGER)
def users_create(c: Ctx):
    v = clean(c.body, [("username", "str", True), ("name", "str", True),
                       ("role", "choice:" + ",".join(auth.ROLES), True), ("department", "str", False)])
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{3,40}", v["username"]):
        raise ApiError(422, "Username must be 3-40 letters, digits or . _ @ -")
    if one(c.conn, "SELECT id FROM users WHERE username=?", (v["username"],)):
        raise ApiError(409, "That username is already taken")
    try:
        uid = auth.create_user(c.conn, v["username"], v["name"], v["role"], str(c.body.get("password") or ""))
    except ValueError as e:
        raise ApiError(422, str(e)) from None
    c.conn.execute("UPDATE users SET department=? WHERE id=?", (v["department"], uid))
    return 201, one(c.conn, "SELECT id,username,name,role,department,active FROM users WHERE id=?", (uid,))


@route("PUT", r"/api/users/(\d+)", roles=MANAGER)
def users_update(c: Ctx):
    uid = int(c.params[0])
    u = need(one(c.conn, "SELECT * FROM users WHERE id=?", (uid,)), "User")
    v = clean(c.body, [("name", "str", True), ("role", "choice:" + ",".join(auth.ROLES), True),
                       ("active", "bool", False), ("department", "str", False)], partial=True)
    new_role, new_active = v.get("role", u["role"]), v.get("active", u["active"])
    if uid == c.user["id"] and (new_role != "manager" or not new_active):
        raise ApiError(422, "You cannot remove your own manager access")
    if u["role"] == "manager" and u["active"] and (new_role != "manager" or not new_active):
        left = one(c.conn, "SELECT COUNT(*) n FROM users WHERE role='manager' AND active=1 AND id<>?", (uid,))["n"]
        if left == 0:
            raise ApiError(422, "At least one active manager is required")
    if v:
        c.conn.execute(f"UPDATE users SET {','.join(k + '=?' for k in v)} WHERE id=?", [*v.values(), uid])
    pw = c.body.get("password")
    if pw:
        if len(str(pw)) < auth.MIN_PASSWORD:
            raise ApiError(422, f"Password must be at least {auth.MIN_PASSWORD} characters")
        salt, digest = auth.hash_password(str(pw))
        c.conn.execute("UPDATE users SET salt=?, pw_hash=? WHERE id=?", (salt, digest, uid))
        auth.end_all_sessions(c.conn, uid)
    if not new_active:
        auth.end_all_sessions(c.conn, uid)
    return one(c.conn, "SELECT id,username,name,role,department,active FROM users WHERE id=?", (uid,))


# ---------------------------------------------------------------- estimate & quotations

def run_estimate(conn, spec, quantities=None):
    try:
        return estimator.estimate(spec, load_masters(conn), get_settings(conn), quantities)
    except estimator.EstimateError as e:
        raise ApiError(422, str(e)) from None


@route("POST", "/api/estimate", roles=OFFICE)
def estimate_(c: Ctx):
    qs = c.body.get("quantities") or []
    if not isinstance(qs, list):
        raise ApiError(422, "Quantities must be a list")
    return run_estimate(c.conn, c.body.get("spec"), qs)


def _quote_row(conn, qid):
    return need(one(conn, "SELECT q.*, c.name AS customer_name FROM quotations q "
                          "JOIN customers c ON c.id=q.customer_id WHERE q.id=?", (qid,)), "Quotation")


def _quote_full(conn, qid):
    q = _quote_row(conn, qid)
    q["spec"] = json.loads(q.pop("spec_json"))
    q["result"] = json.loads(q.pop("result_json"))
    q["customer"] = one(conn, "SELECT * FROM customers WHERE id=?", (q["customer_id"],))
    q["job"] = one(conn, "SELECT id,order_no,stage FROM jobs WHERE id=?", (q["job_id"],)) if q["job_id"] else None
    q["expired"] = q["status"] == "sent" and bool(q["valid_until"]) and q["valid_until"] < db.today()
    return q


QUOTE_HEAD = [("customer_id", "int", True), ("title", "str", True), ("notes", "str", False),
              ("quote_date", "date", False), ("valid_until", "date", False)]


@route("GET", "/api/quotations", roles=OFFICE)
def quotes_list(c: Ctx):
    sql = ("SELECT q.id,q.number,q.title,q.customer_id,c.name AS customer_name,q.status,q.quote_date,q.valid_until,"
           "q.copies,q.total,q.job_id,j.order_no AS job_no,"
           "(q.status='sent' AND q.valid_until<>'' AND q.valid_until<?) AS expired "
           "FROM quotations q JOIN customers c ON c.id=q.customer_id LEFT JOIN jobs j ON j.id=q.job_id WHERE 1=1")
    args: list = [db.today()]
    st = c.query.get("status")
    if st:
        if st not in QUOTE_STATUSES:
            raise ApiError(422, "Unknown status")
        sql += " AND q.status=?"
        args.append(st)
    if c.query.get("customer_id", "").isdigit():
        sql += " AND q.customer_id=?"
        args.append(int(c.query["customer_id"]))
    if c.query.get("mine") == "1":
        sql += " AND j.assigned_to=?"
        args.append(c.user["id"])
    elif c.query.get("assigned_to", "").isdigit():
        sql += " AND j.assigned_to=?"
        args.append(int(c.query["assigned_to"]))
    elif c.query.get("unassigned") == "1":
        sql += " AND j.assigned_to IS NULL AND j.stage NOT IN ('delivered','billed','cancelled')"
    qtext = (c.query.get("q") or "").strip()
    if qtext:
        like = "%" + qtext.replace("%", "").replace("_", "") + "%"
        sql += " AND (q.number LIKE ? OR q.title LIKE ? OR c.name LIKE ?)"
        args += [like, like, like]
    return rows(c.conn, sql + " ORDER BY q.id DESC LIMIT 500", args)


def _quote_values(c: Ctx, existing=None):
    v = clean(c.body, QUOTE_HEAD)
    if not one(c.conn, "SELECT id FROM customers WHERE id=?", (v["customer_id"],)):
        raise ApiError(422, "Choose a customer")
    spec = c.body.get("spec")
    if not isinstance(spec, dict):
        raise ApiError(422, "Missing job specification")
    result = run_estimate(c.conn, spec)
    if not v["quote_date"]:
        v["quote_date"] = existing["quote_date"] if existing else db.today()
    if not v["valid_until"]:
        days = int(float(get_settings(c.conn).get("quote_valid_days", 15)))
        v["valid_until"] = (datetime.strptime(v["quote_date"], "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
    return v, spec, result


@route("POST", "/api/quotations", roles=OFFICE)
def quotes_create(c: Ctx):
    v, spec, result = _quote_values(c)
    _, number = db.next_number(c.conn, "quote", "Q")
    now = db.stamp()
    cur = c.conn.execute(
        "INSERT INTO quotations(number,customer_id,title,status,quote_date,valid_until,copies,spec_json,result_json,"
        "total,notes,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (number, v["customer_id"], v["title"], "draft", v["quote_date"], v["valid_until"], result["copies"],
         json.dumps(spec), json.dumps(result), result["totals"]["total"], v["notes"], c.user["id"], now, now))
    return 201, _quote_full(c.conn, cur.lastrowid)


@route("GET", r"/api/quotations/(\d+)", roles=OFFICE)
def quotes_get(c: Ctx):
    return _quote_full(c.conn, int(c.params[0]))


@route("PUT", r"/api/quotations/(\d+)", roles=OFFICE)
def quotes_update(c: Ctx):
    qid = int(c.params[0])
    q = _quote_row(c.conn, qid)
    if q["status"] not in QUOTE_EDITABLE:
        raise ApiError(409, "An accepted or converted quotation can no longer be edited")
    v, spec, result = _quote_values(c, q)
    c.conn.execute(
        "UPDATE quotations SET customer_id=?,title=?,quote_date=?,valid_until=?,copies=?,spec_json=?,result_json=?,"
        "total=?,notes=?,updated_at=? WHERE id=?",
        (v["customer_id"], v["title"], v["quote_date"], v["valid_until"], result["copies"], json.dumps(spec),
         json.dumps(result), result["totals"]["total"], v["notes"], db.stamp(), qid))
    return _quote_full(c.conn, qid)


@route("POST", r"/api/quotations/(\d+)/recalculate", roles=OFFICE)
def quotes_recalc(c: Ctx):
    """Re-price an existing quotation with today's rates."""
    qid = int(c.params[0])
    q = _quote_row(c.conn, qid)
    if q["status"] not in QUOTE_EDITABLE:
        raise ApiError(409, "An accepted or converted quotation can no longer be changed")
    result = run_estimate(c.conn, json.loads(q["spec_json"]))
    c.conn.execute("UPDATE quotations SET result_json=?,total=?,copies=?,updated_at=? WHERE id=?",
                   (json.dumps(result), result["totals"]["total"], result["copies"], db.stamp(), qid))
    return _quote_full(c.conn, qid)


@route("POST", r"/api/quotations/(\d+)/status", roles=OFFICE)
def quotes_status(c: Ctx):
    qid = int(c.params[0])
    q = _quote_row(c.conn, qid)
    new = c.body.get("status")
    if new not in QUOTE_STATUSES or new not in QUOTE_TRANSITIONS[q["status"]]:
        raise ApiError(409, f"A {q['status']} quotation cannot be changed to {new}")
    c.conn.execute("UPDATE quotations SET status=?, updated_at=? WHERE id=?", (new, db.stamp(), qid))
    return _quote_full(c.conn, qid)


@route("DELETE", r"/api/quotations/(\d+)", roles=OFFICE)
def quotes_delete(c: Ctx):
    qid = int(c.params[0])
    q = _quote_row(c.conn, qid)
    if q["status"] != "draft" or q["job_id"]:
        raise ApiError(409, "Only draft quotations can be deleted")
    c.conn.execute("DELETE FROM quotations WHERE id=?", (qid,))
    return {"deleted": True}


def _color_key(comp):
    if comp["part"] == "cover":
        return "cover"
    if comp["part"] == "end_paper":
        return "end_paper"
    mode = comp.get("color_mode")
    if mode == "multi" or (mode is None and comp["colors"] >= 3):
        return "m_color"
    if mode == "two" or (mode is None and comp["colors"] == 2):
        return "two_color"
    if mode == "bw":
        return "bw"
    return "s_color"


def build_work(result: dict) -> dict:
    """Snapshot of the production details, shaped like the paper work-order form."""
    pages = {k: 0 for k in ("m_color", "two_color", "s_color", "bw", "cover", "end_paper")}
    parts = []
    for comp in result["components"]:
        pages[_color_key(comp)] += comp["pages"]
        parts.append({k: comp[k] for k in ("name", "part", "paper", "machine", "plate", "pages", "colors", "ups",
                                           "forms", "plates", "sheets_net", "sheets_gross", "sides")})
    mats: dict = {}
    for comp in result["components"]:
        m = mats.setdefault(comp["paper_id"], {"paper_id": comp["paper_id"], "paper": comp["paper"], "sheets": 0, "kg": 0.0})
        m["sheets"] += comp["sheets_gross"]
        m["kg"] = round(m["kg"] + comp.get("paper_kg", 0), 3)
    return {
        "materials": list(mats.values()),
        "size": f"{result['size_w']:g} x {result['size_h']:g} in",
        "copies": result["copies"],
        "papers": [{"label": f"{p['name']} - {p['paper']}", "copies": result["copies"]} for p in result["components"]],
        "pages": pages,
        "machines": sorted({p["machine"] for p in result["components"]}),
        "plates": sorted({p["plate"] for p in result["components"] if p["plate"]}),
        "binding": [f["name"] + (f" ({f['note']})" if f["note"] else "") for f in result["finishing"]],
        "design": result["totals"]["design"] > 0,
        "extras": [e["description"] for e in result["extras"]],
        "parts": parts,
    }


@route("POST", r"/api/quotations/(\d+)/convert", roles=OFFICE)
def quotes_convert(c: Ctx):
    qid = int(c.params[0])
    q = _quote_row(c.conn, qid)
    if q["status"] == "converted" or q["job_id"]:
        raise ApiError(409, "This quotation already has a job")
    if q["status"] == "rejected":
        raise ApiError(409, "Re-open the rejected quotation before creating a job")
    v = clean(c.body, [("delivery_date", "date", False), ("proof_date", "date", False),
                       ("priority", "choice:normal,urgent", False, "normal"),
                       ("advance", "float", False), ("receipt_no", "str", False),
                       ("extra_details", "str", False), ("designer", "str", False)])
    target = _assignee(c.conn, c.body.get("assign_to")) if c.body.get("assign_to") not in (None, "", 0) else None
    result = json.loads(q["result_json"])
    spec = json.loads(q["spec_json"])
    settings = get_settings(c.conn)
    fy, order_no = db.next_number(c.conn, "job", "J")
    now = db.stamp()
    t = result["totals"]
    cur = c.conn.execute(
        "INSERT INTO jobs(order_no,quotation_id,customer_id,title,stage,priority,quotation_date,proof_date,delivery_date,"
        "copies,total,gst_pct,hsn,advance,receipt_no,designer,extra_details,work_json,created_by,created_at,updated_at,"
        "stage_changed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (order_no, qid, q["customer_id"], q["title"], "approved", v["priority"], q["quote_date"], v["proof_date"],
         v["delivery_date"], result["copies"], t["total"], t["gst_pct"], settings.get("hsn_default", ""), v["advance"],
         v["receipt_no"], v["designer"], v["extra_details"], json.dumps(build_work(result)), c.user["id"], now, now, now))
    jid = cur.lastrowid
    c.conn.execute("UPDATE quotations SET status='converted', job_id=?, updated_at=? WHERE id=?", (jid, now, qid))
    c.conn.execute("INSERT INTO job_events(job_id,user_id,kind,stage,note,at) VALUES(?,?,?,?,?,?)",
                   (jid, c.user["id"], "created", "approved", f"Created from quotation {q['number']}", now))
    if target:
        _do_assign(c, jid, target, "")
    return 201, _job_full(c.conn, jid, c.user["role"])


# ---------------------------------------------------------------- jobs

def _shape_job(job: dict, role: str) -> dict:
    job["balance"] = round(job["total"] - job["advance"], 2)
    job["overdue"] = bool(job["delivery_date"]) and job["delivery_date"] < db.today() and job["stage"] not in CLOSED_STAGES
    if role not in MONEY_ROLES:
        for k in JOB_MONEY_FIELDS:
            job.pop(k, None)
    return job


def _job_full(conn, jid, role):
    j = need(one(conn, "SELECT j.*, c.name AS customer_name, qn.number AS quotation_no FROM jobs j "
                       "JOIN customers c ON c.id=j.customer_id LEFT JOIN quotations qn ON qn.id=j.quotation_id "
                       "WHERE j.id=?", (jid,)), "Job")
    j["work"] = json.loads(j.pop("work_json") or "{}")
    j["customer"] = one(conn, "SELECT * FROM customers WHERE id=?", (j["customer_id"],))
    j["events"] = rows(conn, "SELECT e.id,e.kind,e.stage,e.note,e.at,u.name AS user_name FROM job_events e "
                             "LEFT JOIN users u ON u.id=e.user_id WHERE e.job_id=? ORDER BY e.id DESC", (jid,))
    j["assigned_name"] = None
    if j["assigned_to"]:
        u = one(conn, "SELECT name, department FROM users WHERE id=?", (j["assigned_to"],))
        j["assigned_name"], j["assigned_dept"] = (u["name"], u["department"]) if u else (None, "")
    j["materials"] = _job_materials(conn, j)
    return _shape_job(j, role)


@route("GET", "/api/jobs")
def jobs_list(c: Ctx):
    sql = ("SELECT j.id,j.order_no,j.title,j.stage,j.priority,j.customer_id,c.name AS customer_name,j.copies,"
           "j.delivery_date,j.proof_date,j.total,j.advance,j.stage_changed_at,j.ok_for_delivery,j.gst_pct,j.hsn,"
           "j.receipt_no,j.bill_no,j.assigned_to,j.progress_pct,u.name AS assigned_name FROM jobs j "
           "JOIN customers c ON c.id=j.customer_id LEFT JOIN users u ON u.id=j.assigned_to WHERE 1=1")
    args: list = []
    st = c.query.get("stage")
    if st:
        if st not in ALL_STAGE_KEYS:
            raise ApiError(422, "Unknown stage")
        sql += " AND j.stage=?"
        args.append(st)
    if c.query.get("open") == "1":
        sql += " AND j.stage NOT IN ('delivered','billed','cancelled')"
    if c.query.get("customer_id", "").isdigit():
        sql += " AND j.customer_id=?"
        args.append(int(c.query["customer_id"]))
    if c.query.get("overdue") == "1":
        sql += " AND j.delivery_date<>'' AND j.delivery_date<? AND j.stage NOT IN ('delivered','billed','cancelled')"
        args.append(db.today())
    qtext = (c.query.get("q") or "").strip()
    if qtext:
        like = "%" + qtext.replace("%", "").replace("_", "") + "%"
        sql += " AND (j.order_no LIKE ? OR j.title LIKE ? OR c.name LIKE ?)"
        args += [like, like, like]
    sql += " ORDER BY (j.priority='urgent') DESC, j.delivery_date='', j.delivery_date, j.id DESC LIMIT 1000"
    return [_shape_job(j, c.user["role"]) for j in rows(c.conn, sql, args)]


@route("GET", r"/api/jobs/(\d+)")
def jobs_get(c: Ctx):
    return _job_full(c.conn, int(c.params[0]), c.user["role"])


@route("PUT", r"/api/jobs/(\d+)", roles=("manager", "desk", "superintendent"))
def jobs_update(c: Ctx):
    jid = int(c.params[0])
    need(one(c.conn, "SELECT id FROM jobs WHERE id=?", (jid,)), "Job")
    fields = [("title", "str", True), ("priority", "choice:normal,urgent", False), ("proof_date", "date", False),
              ("delivery_date", "date", False), ("designer", "str", False), ("extra_details", "str", False),
              ("ok_for_delivery", "bool", False)]
    if c.user["role"] in MONEY_ROLES:
        fields += [("advance", "float", False), ("receipt_no", "str", False), ("bill_no", "str", False),
                   ("hsn", "str", False), ("gst_pct", "float", False)]
    v = clean(c.body, fields, partial=True)
    if v:
        before = one(c.conn, "SELECT * FROM jobs WHERE id=?", (jid,))
        changed = [k for k in v if before[k] != v[k]]
        if changed:
            c.conn.execute(f"UPDATE jobs SET {','.join(k + '=?' for k in v)}, updated_at=? WHERE id=?",
                           [*v.values(), db.stamp(), jid])
            c.conn.execute("INSERT INTO job_events(job_id,user_id,kind,note,at) VALUES(?,?,?,?,?)",
                           (jid, c.user["id"], "edit", "Updated: " + ", ".join(k.replace("_", " ") for k in changed), db.stamp()))
    return _job_full(c.conn, jid, c.user["role"])


@route("POST", r"/api/jobs/(\d+)/stage")
def jobs_stage(c: Ctx):
    jid = int(c.params[0])
    j = need(one(c.conn, "SELECT id,stage FROM jobs WHERE id=?", (jid,)), "Job")
    new = c.body.get("stage")
    if new not in ALL_STAGE_KEYS:
        raise ApiError(422, "Unknown stage")
    if new == j["stage"]:
        raise ApiError(409, "The job is already at that stage")
    if new not in STAGE_PERMS[c.user["role"]]:
        label = dict(STAGES + EXTRA_STAGES)[new]
        raise ApiError(403, f"Your role cannot move a job to {label}")
    note = str(c.body.get("note") or "").strip()[:500]
    now = db.stamp()
    target = _assignee(c.conn, c.body.get("assign_to")) if c.body.get("assign_to") not in (None, "", 0) else None
    c.conn.execute("UPDATE jobs SET stage=?, stage_changed_at=?, updated_at=?, progress_pct=0 WHERE id=?", (new, now, now, jid))
    c.conn.execute("INSERT INTO job_events(job_id,user_id,kind,stage,note,at) VALUES(?,?,?,?,?,?)",
                   (jid, c.user["id"], "stage", new, note, now))
    if target:
        _do_assign(c, jid, target, "")
    return _job_full(c.conn, jid, c.user["role"])


@route("POST", r"/api/jobs/(\d+)/note")
def jobs_note(c: Ctx):
    jid = int(c.params[0])
    need(one(c.conn, "SELECT id FROM jobs WHERE id=?", (jid,)), "Job")
    note = str(c.body.get("note") or "").strip()[:1000]
    if not note:
        raise ApiError(422, "Write a note first")
    c.conn.execute("INSERT INTO job_events(job_id,user_id,kind,note,at) VALUES(?,?,?,?,?)",
                   (jid, c.user["id"], "note", note, db.stamp()))
    return _job_full(c.conn, jid, c.user["role"])


# ---------------------------------------------------------------- people, assignment, progress

STOCK_VIEW = ALL_STAFF
STOCK_HISTORY = ("manager", "desk", "superintendent")
STOCK_EDIT = OFFICE


@route("GET", "/api/people")
def people(c: Ctx):
    """Everyone who can be given work (names only; no login details)."""
    return rows(c.conn, "SELECT id,name,role,department FROM users WHERE active=1 ORDER BY name COLLATE NOCASE")


def _assignee(conn, uid):
    try:
        u = one(conn, "SELECT id,name FROM users WHERE id=? AND active=1", (int(uid),))
    except (TypeError, ValueError):
        u = None
    if not u:
        raise ApiError(422, "Choose an active person to hand the job to")
    return u


def _do_assign(c: Ctx, jid: int, target, note: str):
    now = db.stamp()
    c.conn.execute("UPDATE jobs SET assigned_to=?, assigned_at=?, progress_pct=0, updated_at=? WHERE id=?",
                   (target["id"], now, now, jid))
    text = f"Handed to {target['name']}" + (f": {note}" if note else "")
    c.conn.execute("INSERT INTO job_events(job_id,user_id,kind,note,at) VALUES(?,?,?,?,?)",
                   (jid, c.user["id"], "assign", text, now))


@route("POST", r"/api/jobs/(\d+)/assign")
def jobs_assign(c: Ctx):
    jid = int(c.params[0])
    j = need(one(c.conn, "SELECT id,assigned_to,stage FROM jobs WHERE id=?", (jid,)), "Job")
    is_lead = c.user["role"] in ("manager", "desk", "superintendent")
    if not is_lead and j["assigned_to"] != c.user["id"]:
        raise ApiError(403, "Only the person holding the job, or a supervisor, can hand it over")
    note = str(c.body.get("note") or "").strip()[:500]
    to = c.body.get("user_id")
    if to in (None, "", 0):
        if not is_lead:
            raise ApiError(422, "Choose who to hand the job to")
        now = db.stamp()
        c.conn.execute("UPDATE jobs SET assigned_to=NULL, assigned_at='', progress_pct=0, updated_at=? WHERE id=?", (now, jid))
        c.conn.execute("INSERT INTO job_events(job_id,user_id,kind,note,at) VALUES(?,?,?,?,?)",
                       (jid, c.user["id"], "assign", "Taken off the assignee" + (f": {note}" if note else ""), now))
    else:
        _do_assign(c, jid, _assignee(c.conn, to), note)
    return _job_full(c.conn, jid, c.user["role"])


@route("POST", r"/api/jobs/(\d+)/progress")
def jobs_progress(c: Ctx):
    jid = int(c.params[0])
    j = need(one(c.conn, "SELECT id,assigned_to,progress_pct FROM jobs WHERE id=?", (jid,)), "Job")
    if c.user["role"] not in ("manager", "desk", "superintendent") and j["assigned_to"] != c.user["id"]:
        raise ApiError(403, "Only the person holding the job can report progress")
    v = clean(c.body, [("progress_pct", "int", True)])
    pct = v["progress_pct"]
    if pct > 100:
        raise ApiError(422, "Progress must be between 0 and 100")
    note = str(c.body.get("note") or "").strip()[:500]
    now = db.stamp()
    c.conn.execute("UPDATE jobs SET progress_pct=?, updated_at=? WHERE id=?", (pct, now, jid))
    c.conn.execute("INSERT INTO job_events(job_id,user_id,kind,note,at) VALUES(?,?,?,?,?)",
                   (jid, c.user["id"], "progress", f"{pct}% done" + (f": {note}" if note else ""), now))
    return _job_full(c.conn, jid, c.user["role"])


@route("GET", "/api/monitor", roles=MANAGER)
def monitor(c: Ctx):
    openq = "j.stage NOT IN ('delivered','billed','cancelled')"
    jobs = rows(c.conn, "SELECT j.id,j.order_no,j.title,j.stage,j.priority,j.delivery_date,j.assigned_to,j.assigned_at,"
                        "j.progress_pct,j.stage_changed_at,c.name AS customer_name,"
                        "(SELECT MAX(at) FROM job_events e WHERE e.job_id=j.id) AS last_activity "
                        f"FROM jobs j JOIN customers c ON c.id=j.customer_id WHERE {openq} "
                        "ORDER BY (j.priority='urgent') DESC, j.delivery_date='', j.delivery_date")
    today = db.today()
    for j in jobs:
        j["overdue"] = bool(j["delivery_date"]) and j["delivery_date"] < today
    people_ = rows(c.conn, "SELECT id,name,role,department FROM users WHERE active=1 ORDER BY name COLLATE NOCASE")
    for p in people_:
        p["jobs"] = [j for j in jobs if j["assigned_to"] == p["id"]]
    activity = rows(c.conn, "SELECT e.id,e.kind,e.stage,e.note,e.at,j.id AS job_id,j.order_no,u.name AS user_name "
                            "FROM job_events e JOIN jobs j ON j.id=e.job_id LEFT JOIN users u ON u.id=e.user_id "
                            "ORDER BY e.id DESC LIMIT 40")
    return {"people": people_, "unassigned": [j for j in jobs if not j["assigned_to"]],
            "open_jobs": len(jobs), "activity": activity}


# ---------------------------------------------------------------- inventory

STOCK_CATEGORIES = "paper,ink,plates,chemicals,binding,other"
STOCK_FIELDS = [("name", "str", True), ("category", "choice:" + STOCK_CATEGORIES, False, "paper"),
                ("unit", "str", True), ("paper_id", "int", False), ("reorder_level", "float", False),
                ("location", "str", False), ("notes", "str", False), ("active", "bool", False, 1)]
ON_HAND = "COALESCE((SELECT SUM(qty) FROM stock_moves m WHERE m.item_id=i.id),0)"


def _stock_row(conn, iid):
    r = need(one(conn, f"SELECT i.*, {ON_HAND} AS on_hand, p.name AS paper_name FROM stock_items i "
                       "LEFT JOIN papers p ON p.id=i.paper_id WHERE i.id=?", (iid,)), "Stock item")
    r["on_hand"] = round(r["on_hand"], 3)
    r["low"] = bool(r["active"]) and r["reorder_level"] > 0 and r["on_hand"] <= r["reorder_level"]
    return r


def _stock_fix(v: dict, conn):
    if v.get("paper_id") in (0, None, ""):
        v["paper_id"] = None
    elif not one(conn, "SELECT id FROM papers WHERE id=?", (v["paper_id"],)):
        raise ApiError(422, "That paper does not exist")
    return v


@route("GET", "/api/stock", roles=STOCK_VIEW)
def stock_list(c: Ctx):
    sql = (f"SELECT i.*, {ON_HAND} AS on_hand, p.name AS paper_name FROM stock_items i "
           "LEFT JOIN papers p ON p.id=i.paper_id")
    if c.query.get("all") != "1":
        sql += " WHERE i.active=1"
    out = rows(c.conn, sql + " ORDER BY i.category, i.name COLLATE NOCASE")
    for r in out:
        r["on_hand"] = round(r["on_hand"], 3)
        r["low"] = bool(r["active"]) and r["reorder_level"] > 0 and r["on_hand"] <= r["reorder_level"]
    return out


@route("POST", "/api/stock", roles=STOCK_EDIT)
def stock_create(c: Ctx):
    v = _stock_fix(clean(c.body, STOCK_FIELDS), c.conn)
    cols = [f[0] for f in STOCK_FIELDS]
    cur = c.conn.execute(f"INSERT INTO stock_items({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [v[k] for k in cols])
    iid = cur.lastrowid
    opening = c.body.get("opening_qty")
    if opening not in (None, "", 0, "0"):
        q = clean({"q": opening}, [("q", "float", False)])["q"]
        if q > 0:
            _add_move(c, iid, q, "receive", note="Opening stock")
    return 201, _stock_row(c.conn, iid)


@route("PUT", r"/api/stock/(\d+)", roles=STOCK_EDIT)
def stock_update(c: Ctx):
    iid = int(c.params[0])
    need(one(c.conn, "SELECT id FROM stock_items WHERE id=?", (iid,)), "Stock item")
    v = clean(c.body, STOCK_FIELDS, partial=True)
    if "paper_id" in v:
        _stock_fix(v, c.conn)
    if v:
        c.conn.execute(f"UPDATE stock_items SET {','.join(k + '=?' for k in v)} WHERE id=?", [*v.values(), iid])
    return _stock_row(c.conn, iid)


@route("DELETE", r"/api/stock/(\d+)", roles=STOCK_EDIT)
def stock_delete(c: Ctx):
    iid = int(c.params[0])
    need(one(c.conn, "SELECT id FROM stock_items WHERE id=?", (iid,)), "Stock item")
    if one(c.conn, "SELECT COUNT(*) n FROM stock_moves WHERE item_id=?", (iid,))["n"]:
        c.conn.execute("UPDATE stock_items SET active=0 WHERE id=?", (iid,))
        return {"deleted": False, "deactivated": True}
    c.conn.execute("DELETE FROM stock_items WHERE id=?", (iid,))
    return {"deleted": True}


def _add_move(c: Ctx, iid, qty, kind, job_id=None, ref="", note=""):
    c.conn.execute("INSERT INTO stock_moves(item_id,qty,kind,job_id,ref,note,user_id,at) VALUES(?,?,?,?,?,?,?,?)",
                   (iid, qty, kind, job_id, ref, note, c.user["id"], db.stamp()))


@route("POST", r"/api/stock/(\d+)/move")
def stock_move(c: Ctx):
    """receive / adjust (office) and issue / return (anyone on the floor)."""
    iid = int(c.params[0])
    item = _stock_row(c.conn, iid)
    kind = c.body.get("kind")
    if kind not in ("receive", "adjust", "issue", "return"):
        raise ApiError(422, "Unknown stock action")
    role = c.user["role"]
    if kind in ("receive", "adjust") and role not in STOCK_EDIT:
        raise ApiError(403, "Only the office can receive stock or correct counts")
    if not item["active"]:
        raise ApiError(409, "This stock item is switched off")
    ref = str(c.body.get("ref") or "").strip()[:200]
    note = str(c.body.get("note") or "").strip()[:500]
    job_id = None
    jnum = ""
    if c.body.get("job_id") not in (None, "", 0):
        try:
            job = one(c.conn, "SELECT id,order_no FROM jobs WHERE id=?", (int(c.body["job_id"]),))
        except (TypeError, ValueError):
            job = None
        if not job:
            raise ApiError(422, "That job does not exist")
        job_id, jnum = job["id"], job["order_no"]
    if kind == "adjust":
        counted = clean(c.body, [("counted", "float", True)])["counted"]
        if not note:
            raise ApiError(422, "Say why the count changed")
        delta = round(counted - item["on_hand"], 3)
        if delta == 0:
            raise ApiError(409, "The counted quantity matches what the system already shows")
        _add_move(c, iid, delta, "adjust", None, ref, note)
    else:
        qty = clean(c.body, [("qty", "float", True)])["qty"]
        if qty <= 0:
            raise ApiError(422, "Quantity must be more than zero")
        if kind == "issue":
            if qty > item["on_hand"] + 1e-9:
                raise ApiError(409, f"Only {item['on_hand']:g} {item['unit']} of {item['name']} in stock")
            _add_move(c, iid, -qty, "issue", job_id, ref, note)
        else:
            _add_move(c, iid, qty, kind, job_id, ref, note)
        if job_id:
            verb = {"issue": "Issued", "return": "Returned", "receive": "Received"}[kind]
            c.conn.execute("INSERT INTO job_events(job_id,user_id,kind,note,at) VALUES(?,?,?,?,?)",
                           (job_id, c.user["id"], "stock", f"{verb} {qty:g} {item['unit']} {item['name']}", db.stamp()))
    return _stock_row(c.conn, iid)


@route("GET", r"/api/stock/(\d+)/moves", roles=STOCK_HISTORY)
def stock_moves(c: Ctx):
    iid = int(c.params[0])
    need(one(c.conn, "SELECT id FROM stock_items WHERE id=?", (iid,)), "Stock item")
    return rows(c.conn, "SELECT m.id,m.qty,m.kind,m.ref,m.note,m.at,u.name AS user_name,j.order_no,j.id AS job_id "
                        "FROM stock_moves m LEFT JOIN users u ON u.id=m.user_id LEFT JOIN jobs j ON j.id=m.job_id "
                        "WHERE m.item_id=? ORDER BY m.id DESC LIMIT 200", (iid,))


def _job_materials(conn, j: dict) -> list:
    """Paper this job needs (from its quotation) against what has been issued from stock."""
    out = []
    for m in (j.get("work") or {}).get("materials", []):
        item = one(conn, f"SELECT i.*, {ON_HAND} AS on_hand FROM stock_items i WHERE i.paper_id=? AND i.active=1 "
                         "ORDER BY i.id LIMIT 1", (m["paper_id"],))
        row = {"paper_id": m["paper_id"], "paper": m["paper"], "sheets": m["sheets"], "kg": m["kg"],
               "item_id": None, "item_name": None, "unit": None, "need": None, "issued": 0, "on_hand": None}
        if item:
            unit = (item["unit"] or "").lower()
            need_qty = m["kg"] if unit == "kg" else m["sheets"] / 500.0 if unit in ("ream", "reams") else m["sheets"]
            issued = one(conn, "SELECT COALESCE(-SUM(qty),0) s FROM stock_moves WHERE item_id=? AND job_id=?",
                         (item["id"], j["id"]))["s"]
            row.update(item_id=item["id"], item_name=item["name"], unit=item["unit"], need=round(need_qty, 3),
                       issued=round(issued, 3), on_hand=round(item["on_hand"], 3))
        out.append(row)
    return out


# ---------------------------------------------------------------- dashboard

@route("GET", "/api/dashboard")
def dashboard(c: Ctx):
    today = db.today()
    soon = (db.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    by_stage = {r["stage"]: r["n"] for r in rows(c.conn, "SELECT stage, COUNT(*) n FROM jobs GROUP BY stage")}
    openq = "stage NOT IN ('delivered','billed','cancelled')"
    out = {
        "by_stage": by_stage,
        "open_jobs": one(c.conn, f"SELECT COUNT(*) n FROM jobs WHERE {openq}")["n"],
        "overdue": rows(c.conn, "SELECT j.id,j.order_no,j.title,j.stage,j.delivery_date,c.name AS customer_name "
                                f"FROM jobs j JOIN customers c ON c.id=j.customer_id WHERE j.{openq} AND "
                                "j.delivery_date<>'' AND j.delivery_date<? ORDER BY j.delivery_date LIMIT 20", (today,)),
        "due_soon": rows(c.conn, "SELECT j.id,j.order_no,j.title,j.stage,j.delivery_date,c.name AS customer_name "
                                 f"FROM jobs j JOIN customers c ON c.id=j.customer_id WHERE j.{openq} AND "
                                 "j.delivery_date>=? AND j.delivery_date<=? ORDER BY j.delivery_date LIMIT 20", (today, soon)),
        "ready_for_delivery": one(c.conn, "SELECT COUNT(*) n FROM jobs WHERE stage='ready'")["n"],
    }
    out["my_jobs"] = rows(c.conn, "SELECT j.id,j.order_no,j.title,j.stage,j.delivery_date,j.progress_pct,c.name AS customer_name "
                                  f"FROM jobs j JOIN customers c ON c.id=j.customer_id WHERE j.{openq} AND j.assigned_to=? "
                                  "ORDER BY j.delivery_date='', j.delivery_date", (c.user["id"],))
    out["unassigned"] = one(c.conn, f"SELECT COUNT(*) n FROM jobs WHERE {openq} AND assigned_to IS NULL")["n"]
    if c.user["role"] in STOCK_VIEW:
        out["low_stock"] = [r for r in stock_list(c) if r["low"]][:10]
    if c.user["role"] in OFFICE:
        out["quotes"] = {
            "draft": one(c.conn, "SELECT COUNT(*) n FROM quotations WHERE status='draft'")["n"],
            "awaiting_reply": rows(c.conn, "SELECT COUNT(*) n, COALESCE(SUM(total),0) value FROM quotations "
                                           "WHERE status='sent'")[0],
            "accepted_not_started": one(c.conn, "SELECT COUNT(*) n FROM quotations WHERE status='accepted' AND job_id IS NULL")["n"],
        }
        month = today[:7]
        out["month"] = rows(c.conn, "SELECT COUNT(*) n, COALESCE(SUM(total),0) value FROM jobs "
                                    "WHERE stage<>'cancelled' AND substr(created_at,1,7)=?", (month,))[0]
        out["balance_due"] = one(c.conn, "SELECT COALESCE(SUM(total-advance),0) v FROM jobs WHERE stage IN ('delivered','ready')")["v"]
    return out
