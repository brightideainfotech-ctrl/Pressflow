"""Store keeping: material requests for confirmed jobs, issue by the storekeeper, and manager approval
before the same material is handed out to the same job a second time."""
from __future__ import annotations

import json

from . import db, estimator
from .api import (ApiError, Ctx, ALL_STAFF, CLOSED_STAGES, MANAGER, MONEY_ROLES, ON_HAND, clean, get_settings, load_masters,
                  need, one, route, rows)

OPEN = ("awaiting_approval", "pending", "partial")
ISSUERS = ("manager", "storekeeper")

SELECT = (f"SELECT r.*, j.order_no, j.title AS job_title, j.stage AS job_stage, ru.name AS requested_name, du.name AS decided_name, "
          f"iu.name AS issued_name, i.location, i.name AS item_name, {ON_HAND} AS on_hand FROM material_requests r "
          "JOIN jobs j ON j.id=r.job_id LEFT JOIN users ru ON ru.id=r.requested_by LEFT JOIN users du ON du.id=r.decided_by "
          "LEFT JOIN users iu ON iu.id=r.issued_by LEFT JOIN stock_items i ON i.id=r.item_id ")


def _shape(r: dict) -> dict:
    r["remaining"] = round(max(0.0, r["qty"] - r["qty_issued"]), 3)
    return r


def requests_for_job(conn, jid: int) -> list:
    return [_shape(r) for r in rows(conn, SELECT + "WHERE r.job_id=? ORDER BY r.id DESC", (jid,))]


def summary(conn, user) -> dict:
    n = lambda st: one(conn, f"SELECT COUNT(*) n FROM material_requests WHERE status IN ({st})")["n"]  # noqa: E731
    return {"to_issue": n("'pending','partial'"), "awaiting_approval": n("'awaiting_approval'")}


def _paper_qty(item: dict, sheets: float, kg: float) -> float:
    unit = (item["unit"] or "").lower()
    return kg if unit == "kg" else sheets / 500.0 if unit in ("ream", "reams") else sheets


def relink(conn) -> None:
    """A stock item was created or linked to a paper: attach it to open requests that were waiting for one."""
    for r in rows(conn, "SELECT id, paper_id, sheets, kg FROM material_requests WHERE item_id IS NULL AND paper_id IS NOT NULL "
                        "AND status IN ('pending','partial')"):
        item = one(conn, "SELECT * FROM stock_items WHERE paper_id=? AND active=1 AND track_stock=1 ORDER BY id LIMIT 1", (r["paper_id"],))
        if item:
            conn.execute("UPDATE material_requests SET item_id=?, name=?, unit=?, qty=? WHERE id=?",
                         (item["id"], item["name"], item["unit"], round(_paper_qty(item, r["sheets"], r["kg"]), 3), r["id"]))


def make_initial_requests(conn, job_id: int, work: dict, user_id) -> None:
    """When a job is confirmed, ask the store for the paper it needs. One request per paper."""
    now = db.stamp()
    for m in work.get("materials", []):
        item = one(conn, "SELECT * FROM stock_items WHERE paper_id=? AND active=1 AND track_stock=1 ORDER BY id LIMIT 1", (m["paper_id"],))
        if item:
            qty = _paper_qty(item, m["sheets"], m["kg"])
            name, unit_txt, iid = item["name"], item["unit"], item["id"]
        else:
            qty, name, unit_txt, iid = m["sheets"], m["paper"], "sheets", None
        if qty <= 0:
            continue
        _, number = db.next_number(conn, "mreq", "MR")
        conn.execute("INSERT INTO material_requests(number,job_id,item_id,paper_id,sheets,kg,name,unit,qty,status,kind,reason,"
                     "requested_by,requested_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (number, job_id, iid, m["paper_id"], m["sheets"], m["kg"], name, unit_txt, round(qty, 3), "pending", "initial",
                      "Job confirmed", user_id, now))


def _job_event(conn, jid, uid, text):
    conn.execute("INSERT INTO job_events(job_id,user_id,kind,note,at) VALUES(?,?,?,?,?)", (jid, uid, "stock", text, db.stamp()))


@route("GET", "/api/store/summary", roles=ALL_STAFF)
def store_summary(c: Ctx):
    return summary(c.conn, c.user)


@route("GET", "/api/store/requests", roles=ALL_STAFF)
def store_requests(c: Ctx):
    which = c.query.get("status", "open")
    sql = SELECT
    if which == "open":
        sql += f"WHERE r.status IN ({','.join(repr(s) for s in OPEN)}) "
    elif which == "history":
        sql += "WHERE r.status NOT IN ('awaiting_approval','pending','partial') "
    sql += "ORDER BY r.id DESC LIMIT 300"
    return [_shape(r) for r in rows(c.conn, sql)]


@route("POST", r"/api/jobs/(\d+)/material-requests", roles=ALL_STAFF)
def request_create(c: Ctx):
    jid = int(c.params[0])
    job = need(one(c.conn, "SELECT id, order_no, stage FROM jobs WHERE id=?", (jid,)), "Job")
    if job["stage"] in CLOSED_STAGES:
        raise ApiError(409, "This job is closed, so no more material can be requested for it")
    v = clean(c.body, [("item_id", "int", True), ("qty", "float", True), ("reason", "str", False)])
    if v["qty"] <= 0:
        raise ApiError(422, "Quantity must be more than zero")
    item = need(one(c.conn, "SELECT * FROM stock_items WHERE id=? AND active=1", (v["item_id"],)), "Stock item")
    if not item["track_stock"]:
        raise ApiError(409, "That item is not kept in stock")
    if one(c.conn, "SELECT id FROM material_requests WHERE job_id=? AND item_id=? AND status IN ('awaiting_approval','pending','partial')",
           (jid, item["id"])):
        raise ApiError(409, f"{item['name']} is already requested for {job['order_no']} and waiting at the store. Wait for it to be issued")
    allocated = (one(c.conn, "SELECT COALESCE(-SUM(qty),0) s FROM stock_moves WHERE item_id=? AND job_id=?", (item["id"], jid))["s"] > 0
                 or one(c.conn, "SELECT id FROM material_requests WHERE job_id=? AND item_id=? AND qty_issued>0", (jid, item["id"])))
    reason = (v.get("reason") or "").strip()[:500]
    now = db.stamp()
    kind, status, decided_by, decided_at, dnote = "initial", "pending", None, "", ""
    if allocated:
        kind = "additional"
        if len(reason) < 3:
            raise ApiError(422, f"{item['name']} has already been issued for this job. Say why more is needed, so the manager can authorise it")
        if c.user["role"] == "manager":
            decided_by, decided_at, dnote = c.user["id"], now, "Raised by the manager"
        else:
            status = "awaiting_approval"
    _, number = db.next_number(c.conn, "mreq", "MR")
    cur = c.conn.execute(
        "INSERT INTO material_requests(number,job_id,item_id,name,unit,qty,status,kind,reason,requested_by,requested_at,"
        "decided_by,decided_at,decision_note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (number, jid, item["id"], item["name"], item["unit"], v["qty"], status, kind, reason, c.user["id"], now,
         decided_by, decided_at, dnote))
    _job_event(c.conn, jid, c.user["id"], f"Material requested: {v['qty']:g} {item['unit']} {item['name']}"
               + (" (needs manager approval)" if status == "awaiting_approval" else ""))
    return 201, _shape(one(c.conn, SELECT + "WHERE r.id=?", (cur.lastrowid,)))


def _req(c: Ctx) -> dict:
    return _shape(need(one(c.conn, SELECT + "WHERE r.id=?", (int(c.params[0]),)), "Material request"))


@route("POST", r"/api/material-requests/(\d+)/decide", roles=MANAGER)
def request_decide(c: Ctx):
    r = _req(c)
    if r["status"] != "awaiting_approval":
        raise ApiError(409, "This request is not waiting for approval")
    approve = bool(c.body.get("approve"))
    note = str(c.body.get("note") or "").strip()[:500]
    now = db.stamp()
    if approve:
        qty = r["qty"]
        if c.body.get("qty") not in (None, ""):
            qty = clean(c.body, [("qty", "float", True)])["qty"]
            if qty <= 0:
                raise ApiError(422, "Quantity must be more than zero")
        c.conn.execute("UPDATE material_requests SET status='pending', qty=?, decided_by=?, decided_at=?, decision_note=? WHERE id=?",
                       (qty, c.user["id"], now, note, r["id"]))
        _job_event(c.conn, r["job_id"], c.user["id"], f"Extra {r['name']} authorised: {qty:g} {r['unit']}")
    else:
        if not note:
            raise ApiError(422, "Give a reason for refusing")
        c.conn.execute("UPDATE material_requests SET status='rejected', decided_by=?, decided_at=?, decision_note=? WHERE id=?",
                       (c.user["id"], now, note, r["id"]))
        _job_event(c.conn, r["job_id"], c.user["id"], f"Extra {r['name']} refused: {note}")
    return _shape(one(c.conn, SELECT + "WHERE r.id=?", (r["id"],)))


@route("POST", r"/api/material-requests/(\d+)/issue", roles=ISSUERS)
def request_issue(c: Ctx):
    r = _req(c)
    if r["status"] not in ("pending", "partial"):
        raise ApiError(409, "Awaiting the manager's approval" if r["status"] == "awaiting_approval" else "This request is already closed")
    if not r["item_id"]:
        raise ApiError(409, f"{r['name']} is not linked to a stock item. Ask the office to set it up under Items & stock")
    qty = r["remaining"] if c.body.get("qty") in (None, "") else clean(c.body, [("qty", "float", True)])["qty"]
    if qty <= 0:
        raise ApiError(422, "Quantity must be more than zero")
    if qty > r["remaining"] + 1e-9:
        raise ApiError(409, f"Only {r['remaining']:g} {r['unit']} is approved for this request. Extra material needs a new request and the manager's approval")
    if qty > r["on_hand"] + 1e-9:
        raise ApiError(409, f"Only {r['on_hand']:g} {r['unit']} of {r['name']} in stock")
    note = str(c.body.get("note") or "").strip()[:500]
    now = db.stamp()
    c.conn.execute("INSERT INTO stock_moves(item_id,qty,kind,job_id,ref,note,user_id,at) VALUES(?,?,?,?,?,?,?,?)",
                   (r["item_id"], -qty, "issue", r["job_id"], r["number"], note, c.user["id"], now))
    issued = round(r["qty_issued"] + qty, 3)
    status = "issued" if issued >= r["qty"] - 1e-9 else "partial"
    c.conn.execute("UPDATE material_requests SET qty_issued=?, status=?, issued_by=?, issued_at=?, store_note=? WHERE id=?",
                   (issued, status, c.user["id"], now, note, r["id"]))
    _job_event(c.conn, r["job_id"], c.user["id"], f"Store issued {qty:g} {r['unit']} {r['name']}")
    return _shape(one(c.conn, SELECT + "WHERE r.id=?", (r["id"],)))


@route("POST", r"/api/material-requests/(\d+)/cancel", roles=ALL_STAFF)
def request_cancel(c: Ctx):
    r = _req(c)
    if r["status"] not in ("awaiting_approval", "pending") or r["qty_issued"] > 0:
        raise ApiError(409, "Only a request that has not been issued can be cancelled")
    if c.user["role"] not in ("manager", "storekeeper") and r["requested_by"] != c.user["id"]:
        raise ApiError(403, "Only the person who asked, the storekeeper or the manager can cancel this request")
    c.conn.execute("UPDATE material_requests SET status='cancelled', decided_by=?, decided_at=? WHERE id=?",
                   (c.user["id"], db.stamp(), r["id"]))
    return _shape(one(c.conn, SELECT + "WHERE r.id=?", (r["id"],)))


# ------------------------------------------------------------ best sheet size

def _suggest(c: Ctx, spec: dict) -> dict:
    M = load_masters(c.conn)
    sizes = [(r["name"], r["width_cm"], r["height_cm"]) for r in rows(c.conn, "SELECT * FROM sheet_sizes WHERE active=1")]
    try:
        parts = estimator.suggest_sizes(spec, M, get_settings(c.conn), sizes)
    except estimator.EstimateError as e:
        raise ApiError(422, str(e)) from None
    if c.user["role"] not in MONEY_ROLES:
        for p in parts:
            for o in [p["current"], p["best"], *p["options"]]:
                if o:
                    o.pop("paper_cost", None)
    return {"parts": parts}


@route("POST", "/api/suggest-sizes", roles=("manager", "desk"))
def suggest_sizes_route(c: Ctx):
    return _suggest(c, c.body)


@route("GET", r"/api/jobs/(\d+)/size-suggestions", roles=ALL_STAFF)
def job_size_suggestions(c: Ctx):
    j = need(one(c.conn, "SELECT quotation_id FROM jobs WHERE id=?", (int(c.params[0]),)), "Job")
    q = one(c.conn, "SELECT spec_json FROM quotations WHERE id=?", (j["quotation_id"],)) if j["quotation_id"] else None
    if not q:
        raise ApiError(404, "This job has no quotation to work from")
    return _suggest(c, json.loads(q["spec_json"]))
