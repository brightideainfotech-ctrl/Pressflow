"""Basic accounting: parties, sales invoices, purchase bills, payments and reports.

Sign convention for a party balance: positive = the party owes us (receivable),
negative = we owe the party (payable).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db
from .api import (ApiError, Ctx, OFFICE, clean, get_settings, need, one, route, rows, ON_HAND)

STATES = [
    ("01", "Jammu & Kashmir"), ("02", "Himachal Pradesh"), ("03", "Punjab"), ("04", "Chandigarh"),
    ("05", "Uttarakhand"), ("06", "Haryana"), ("07", "Delhi"), ("08", "Rajasthan"), ("09", "Uttar Pradesh"),
    ("10", "Bihar"), ("11", "Sikkim"), ("12", "Arunachal Pradesh"), ("13", "Nagaland"), ("14", "Manipur"),
    ("15", "Mizoram"), ("16", "Tripura"), ("17", "Meghalaya"), ("18", "Assam"), ("19", "West Bengal"),
    ("20", "Jharkhand"), ("21", "Odisha"), ("22", "Chhattisgarh"), ("23", "Madhya Pradesh"), ("24", "Gujarat"),
    ("26", "Dadra & Nagar Haveli and Daman & Diu"), ("27", "Maharashtra"), ("29", "Karnataka"), ("30", "Goa"),
    ("31", "Lakshadweep"), ("32", "Kerala"), ("33", "Tamil Nadu"), ("34", "Puducherry"),
    ("35", "Andaman & Nicobar Islands"), ("36", "Telangana"), ("37", "Andhra Pradesh"), ("38", "Ladakh"),
]
STATE_NAMES = dict(STATES)
PAY_MODES = "cash,upi,bank,cheque,card,other"
r2 = lambda x: round(x + 0.0, 2)  # noqa: E731


def _fy_start() -> str:
    n = db.now()
    return f"{n.year if n.month >= 4 else n.year - 1}-04-01"


def _range(c: Ctx) -> tuple[str, str]:
    f = c.query.get("from") or _fy_start()
    t = c.query.get("to") or db.today()
    for v in (f, t):
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ApiError(422, "Dates must look like 2026-04-01") from None
    if f > t:
        raise ApiError(422, "The 'from' date is after the 'to' date")
    return f, t


@route("GET", "/api/states", roles=OFFICE)
def states(c: Ctx):
    return [{"code": k, "name": v} for k, v in STATES]


# ---------------------------------------------------------------- parties

PARTY_FIELDS = [
    ("name", "str", True), ("party_type", "choice:customer,supplier,both", False, "customer"),
    ("contact_person", "str", False), ("phone1", "str", False), ("phone2", "str", False), ("email", "str", False),
    ("address", "str", False), ("pin", "str", False), ("gstin", "str", False), ("state_code", "str", False),
    ("notes", "str", False), ("active", "bool", False, 1)]

BAL_SQL = (
    "(p.opening_balance"
    " + COALESCE((SELECT SUM(CASE i.kind WHEN 'sale' THEN i.total ELSE -i.total END) FROM invoices i"
    "             WHERE i.party_id=p.id AND i.status='active'),0)"
    " - COALESCE((SELECT SUM(CASE y.kind WHEN 'in' THEN y.amount ELSE -y.amount END) FROM payments y"
    "             WHERE y.party_id=p.id),0))")


def _party_fix(v: dict, existing: dict | None = None) -> dict:
    if "gstin" in v:
        g = v["gstin"].upper().replace(" ", "")
        if g and (len(g) != 15 or not g.isalnum()):
            raise ApiError(422, "GSTIN must be 15 letters and digits")
        v["gstin"] = g
    sc = v.get("state_code")
    if sc:
        if sc not in STATE_NAMES:
            raise ApiError(422, "Choose a state from the list")
    g = v.get("gstin") if "gstin" in v else (existing or {}).get("gstin", "")
    if g and "state_code" in v and not v["state_code"] and g[:2] in STATE_NAMES:
        v["state_code"] = g[:2]
    return v


def _party_row(conn, pid: int) -> dict:
    r = need(one(conn, f"SELECT p.*, {BAL_SQL} AS balance FROM customers p WHERE p.id=?", (pid,)), "Party")
    r["balance"] = r2(r["balance"])
    return r


@route("GET", "/api/parties", roles=OFFICE)
def parties_list(c: Ctx):
    sql = f"SELECT p.*, {BAL_SQL} AS balance FROM customers p WHERE 1=1"
    args: list = []
    if c.query.get("all") != "1":
        sql += " AND p.active=1"
    t = c.query.get("type")
    if t == "customer":
        sql += " AND p.party_type IN ('customer','both')"
    elif t == "supplier":
        sql += " AND p.party_type IN ('supplier','both')"
    out = rows(c.conn, sql + " ORDER BY p.name COLLATE NOCASE", args)
    for r in out:
        r["balance"] = r2(r["balance"])
    return out


@route("POST", "/api/parties", roles=OFFICE)
def parties_create(c: Ctx):
    v = _party_fix(clean(c.body, PARTY_FIELDS))
    ob = c.body.get("opening_balance", 0)
    try:
        ob = float(ob or 0)
    except (TypeError, ValueError):
        raise ApiError(422, "Opening balance must be a number") from None
    if abs(ob) > 1e9:
        raise ApiError(422, "Opening balance is out of range")
    v["opening_balance"] = r2(ob)
    cols = list(v)
    cur = c.conn.execute(f"INSERT INTO customers({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [v[k] for k in cols])
    return 201, _party_row(c.conn, cur.lastrowid)


@route("PUT", r"/api/parties/(\d+)", roles=OFFICE)
def parties_update(c: Ctx):
    pid = int(c.params[0])
    ex = need(one(c.conn, "SELECT * FROM customers WHERE id=?", (pid,)), "Party")
    v = _party_fix(clean(c.body, PARTY_FIELDS, partial=True), ex)
    if "opening_balance" in c.body:
        try:
            v["opening_balance"] = r2(float(c.body["opening_balance"] or 0))
        except (TypeError, ValueError):
            raise ApiError(422, "Opening balance must be a number") from None
    if v:
        c.conn.execute(f"UPDATE customers SET {','.join(k + '=?' for k in v)} WHERE id=?", [*v.values(), pid])
    return _party_row(c.conn, pid)


@route("DELETE", r"/api/parties/(\d+)", roles=OFFICE)
def parties_delete(c: Ctx):
    pid = int(c.params[0])
    need(one(c.conn, "SELECT id FROM customers WHERE id=?", (pid,)), "Party")
    used = one(c.conn, "SELECT (SELECT COUNT(*) FROM quotations WHERE customer_id=?)+(SELECT COUNT(*) FROM jobs WHERE customer_id=?)"
                       "+(SELECT COUNT(*) FROM invoices WHERE party_id=?)+(SELECT COUNT(*) FROM payments WHERE party_id=?) n",
               (pid, pid, pid, pid))["n"]
    if used:
        c.conn.execute("UPDATE customers SET active=0 WHERE id=?", (pid,))
        return {"deleted": False, "deactivated": True}
    c.conn.execute("DELETE FROM customers WHERE id=?", (pid,))
    return {"deleted": True}


# ---------------------------------------------------------------- invoices

def _company_state(settings: dict) -> str:
    sc = settings.get("company_state_code", "")
    if sc in STATE_NAMES:
        return sc
    g = settings.get("company_gstin", "")
    return g[:2] if g[:2] in STATE_NAMES else ""


def _compute(lines: list[dict], intra: bool) -> tuple[list[dict], dict]:
    out, tot = [], {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0}
    for ln in lines:
        taxable = r2(ln["qty"] * ln["rate"] * (1 - ln["disc_pct"] / 100.0))
        gst = r2(taxable * ln["gst_rate"] / 100.0)
        if intra:
            cg = r2(gst / 2)
            cgst, sgst, igst = cg, r2(gst - cg), 0.0
        else:
            cgst = sgst = 0.0
            igst = gst
        row = {**ln, "taxable": taxable, "cgst": cgst, "sgst": sgst, "igst": igst, "amount": r2(taxable + gst)}
        out.append(row)
        for k in tot:
            tot[k] = r2(tot[k] + row[k])
    raw = tot["taxable"] + tot["cgst"] + tot["sgst"] + tot["igst"]
    total = float(round(raw))
    tot["round_off"] = r2(total - raw)
    tot["total"] = total
    return out, tot


LINE_FIELDS = [("description", "str", True), ("hsn", "str", False), ("qty", "pfloat", True), ("unit", "str", False),
               ("rate", "float", True), ("disc_pct", "float", False), ("gst_rate", "float", False)]


def _paid(conn, iid: int) -> float:
    return r2(one(conn, "SELECT COALESCE(SUM(amount),0) s FROM payments WHERE invoice_id=?", (iid,))["s"])


def _invoice_full(conn, iid: int, kind: str | None = None) -> dict:
    inv = need(one(conn, "SELECT i.*, p.name AS party_name, p.gstin AS party_gstin, p.address AS party_address, "
                         "p.pin AS party_pin, p.phone1 AS party_phone, p.state_code AS party_state "
                         "FROM invoices i JOIN customers p ON p.id=i.party_id WHERE i.id=?", (iid,)), "Invoice")
    if kind and inv["kind"] != kind:
        raise ApiError(404, "Invoice not found")
    inv["lines"] = rows(conn, "SELECT l.*, i.name AS item_name FROM invoice_lines l LEFT JOIN stock_items i ON i.id=l.item_id "
                              "WHERE l.invoice_id=? ORDER BY l.id", (iid,))
    inv["paid"] = _paid(conn, iid)
    inv["due"] = r2(inv["total"] - inv["paid"]) if inv["status"] == "active" else 0.0
    inv["pay_status"] = _pay_status(inv)
    inv["payments"] = rows(conn, "SELECT id,number,pay_date,amount,mode,ref FROM payments WHERE invoice_id=? ORDER BY pay_date,id", (iid,))
    inv["place_name"] = STATE_NAMES.get(inv["place_of_supply"], "")
    return inv


def _pay_status(inv: dict) -> str:
    if inv["status"] != "active":
        return "cancelled"
    if inv["paid"] >= inv["total"] - 0.005:
        return "paid"
    return "part" if inv["paid"] > 0 else "unpaid"


def _make_invoice(c: Ctx, kind: str) -> dict:
    b = c.body
    settings = get_settings(c.conn)
    v = clean(b, [("party_id", "int", True), ("inv_date", "date", False), ("due_date", "date", False),
                  ("party_ref", "str", False), ("notes", "str", False), ("place_of_supply", "str", False)])
    party = need(one(c.conn, "SELECT * FROM customers WHERE id=? AND active=1", (v["party_id"],)), "Party")
    if kind == "sale" and party["party_type"] == "supplier":
        raise ApiError(422, f"{party['name']} is set up as a supplier. Change the party type to customer or both to sell to them")
    if kind == "purchase" and party["party_type"] == "customer":
        raise ApiError(422, f"{party['name']} is set up as a customer. Change the party type to supplier or both to buy from them")
    v["inv_date"] = v["inv_date"] or db.today()
    if v["due_date"] and v["due_date"] < v["inv_date"]:
        raise ApiError(422, "Due date is before the invoice date")
    raw_lines = b.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ApiError(422, "Add at least one line")
    if len(raw_lines) > 200:
        raise ApiError(422, "Too many lines")
    lines = []
    for i, rl in enumerate(raw_lines, 1):
        if not isinstance(rl, dict):
            raise ApiError(422, f"Line {i} is not valid")
        try:
            ln = clean(rl, LINE_FIELDS)
        except ApiError as e:
            raise ApiError(422, f"Line {i}: {e.message}") from None
        if ln["disc_pct"] > 100 or ln["gst_rate"] > 50:
            raise ApiError(422, f"Line {i}: discount must be up to 100% and GST up to 50%")
        item_id = rl.get("item_id")
        item = None
        if item_id not in (None, "", 0):
            try:
                item = one(c.conn, "SELECT * FROM stock_items WHERE id=?", (int(item_id),))
            except (TypeError, ValueError):
                item = None
            if not item:
                raise ApiError(422, f"Line {i}: that item does not exist")
        ln["item_id"] = item["id"] if item else None
        ln["_track"] = bool(item and item["track_stock"])
        ln["_item"] = item
        lines.append(ln)

    pos = v["place_of_supply"] or party["state_code"] or (party["gstin"][:2] if party["gstin"][:2] in STATE_NAMES else "")
    if pos and pos not in STATE_NAMES:
        raise ApiError(422, "Choose the place of supply from the list")
    mine = _company_state(settings)
    # Same state (or unknown) -> CGST+SGST, different state -> IGST.
    intra = (not pos) or (not mine) or pos == mine
    comp, tot = _compute(lines, intra)

    # stock check for sales, before anything is written
    need_by_item: dict[int, float] = {}
    for ln in lines:
        if ln["_track"]:
            need_by_item[ln["item_id"]] = need_by_item.get(ln["item_id"], 0) + ln["qty"]
    if kind == "sale":
        for iid, q in need_by_item.items():
            it = one(c.conn, f"SELECT i.name, i.unit, {ON_HAND} AS on_hand FROM stock_items i WHERE i.id=?", (iid,))
            if q > it["on_hand"] + 1e-9:
                raise ApiError(409, f"Only {it['on_hand']:g} {it['unit']} of {it['name']} in stock, but the invoice needs {q:g}")

    job_id = None
    if kind == "sale" and b.get("job_id") not in (None, "", 0):
        job = one(c.conn, "SELECT id, order_no, bill_no FROM jobs WHERE id=?", (int(b["job_id"]),))
        if not job:
            raise ApiError(422, "That job does not exist")
        job_id = job["id"]

    # optional payment recorded together with the invoice
    paid_now = 0.0
    pn = b.get("paid_now")
    if isinstance(pn, dict) and pn.get("amount") not in (None, "", 0, "0"):
        pv = clean(pn, [("amount", "pfloat", True), ("mode", "choice:" + PAY_MODES, False, "cash"), ("ref", "str", False)])
        paid_now = r2(pv["amount"])
        if paid_now > tot["total"] + 0.005:
            raise ApiError(422, "The amount received is more than the invoice total")

    prefix, seq = ("INV", "sale") if kind == "sale" else ("PUR", "purchase")
    _, number = db.next_number(c.conn, seq, prefix)
    stamp = db.stamp()
    cur = c.conn.execute(
        "INSERT INTO invoices(kind,number,party_ref,party_id,inv_date,due_date,place_of_supply,intra,taxable,cgst,sgst,igst,"
        "round_off,total,status,job_id,notes,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (kind, number, v["party_ref"], party["id"], v["inv_date"], v["due_date"], pos, 1 if intra else 0, tot["taxable"],
         tot["cgst"], tot["sgst"], tot["igst"], tot["round_off"], tot["total"], "active", job_id, v["notes"],
         c.user["id"], stamp))
    iid = cur.lastrowid
    for ln in comp:
        c.conn.execute(
            "INSERT INTO invoice_lines(invoice_id,item_id,description,hsn,qty,unit,rate,disc_pct,gst_rate,taxable,cgst,sgst,igst,amount)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (iid, ln["item_id"], ln["description"], ln["hsn"], ln["qty"], ln["unit"], ln["rate"], ln["disc_pct"], ln["gst_rate"],
             ln["taxable"], ln["cgst"], ln["sgst"], ln["igst"], ln["amount"]))
        if ln["_track"]:
            q = ln["qty"] if kind == "purchase" else -ln["qty"]
            c.conn.execute("INSERT INTO stock_moves(item_id,qty,kind,job_id,ref,note,user_id,at,invoice_id) VALUES(?,?,?,?,?,?,?,?,?)",
                           (ln["item_id"], q, "receive" if kind == "purchase" else "issue", job_id,
                            number, ("Purchase from " if kind == "purchase" else "Sold to ") + party["name"], c.user["id"], stamp, iid))
            if kind == "purchase" and ln["rate"] > 0:  # latest buying price is the cost used for stock value
                c.conn.execute("UPDATE stock_items SET purchase_price=? WHERE id=?", (ln["rate"], ln["item_id"]))
    if job_id:
        c.conn.execute("UPDATE jobs SET bill_no=? WHERE id=? AND bill_no=''", (number, job_id))
        c.conn.execute("INSERT INTO job_events(job_id,user_id,kind,note,at) VALUES(?,?,?,?,?)",
                       (job_id, c.user["id"], "note", f"Invoice {number} raised", stamp))
    if paid_now:
        _insert_payment(c, "in" if kind == "sale" else "out", party["id"], iid, v["inv_date"], paid_now,
                        pv["mode"], pv["ref"], "Paid with the invoice")
    return _invoice_full(c.conn, iid)


def _register(kind: str, path: str):
    @route("GET", f"/api/{path}", roles=OFFICE)
    def list_(c: Ctx, kind=kind):
        f, t = c.query.get("from") or "", c.query.get("to") or ""
        sql = ("SELECT i.id,i.number,i.party_ref,i.inv_date,i.due_date,i.taxable,i.cgst,i.sgst,i.igst,i.total,i.status,i.party_id,"
               "p.name AS party_name, COALESCE((SELECT SUM(amount) FROM payments y WHERE y.invoice_id=i.id),0) AS paid "
               "FROM invoices i JOIN customers p ON p.id=i.party_id WHERE i.kind=?")
        args: list = [kind]
        if f:
            sql += " AND i.inv_date>=?"; args.append(f)
        if t:
            sql += " AND i.inv_date<=?"; args.append(t)
        if c.query.get("party_id"):
            sql += " AND i.party_id=?"; args.append(int(c.query["party_id"]))
        q = (c.query.get("q") or "").strip()
        if q:
            sql += " AND (i.number LIKE ? OR i.party_ref LIKE ? OR p.name LIKE ?)"; args += [f"%{q}%"] * 3
        out = rows(c.conn, sql + " ORDER BY i.inv_date DESC, i.id DESC LIMIT 1000", args)
        for r in out:
            r["paid"] = r2(r["paid"])
            r["pay_status"] = _pay_status(r)
            r["due"] = r2(r["total"] - r["paid"]) if r["status"] == "active" else 0.0
        st = c.query.get("status")
        if st:
            out = [r for r in out if r["pay_status"] == st]
        return out

    @route("POST", f"/api/{path}", roles=OFFICE)
    def create_(c: Ctx, kind=kind):
        return 201, _make_invoice(c, kind)

    @route("GET", rf"/api/{path}/(\d+)", roles=OFFICE)
    def get_(c: Ctx, kind=kind):
        return _invoice_full(c.conn, int(c.params[0]), kind)

    @route("POST", rf"/api/{path}/(\d+)/cancel", roles=OFFICE)
    def cancel_(c: Ctx, kind=kind):
        iid = int(c.params[0])
        inv = _invoice_full(c.conn, iid, kind)
        if inv["status"] != "active":
            raise ApiError(409, "This invoice is already cancelled")
        if inv["payments"]:
            raise ApiError(409, "Delete the payments recorded against this invoice first, then cancel it")
        stamp = db.stamp()
        for mv in rows(c.conn, "SELECT item_id, SUM(qty) q FROM stock_moves WHERE invoice_id=? GROUP BY item_id", (iid,)):
            if mv["q"] > 0:  # a purchase added stock: taking it back must not leave a negative balance
                it = one(c.conn, f"SELECT i.name, i.unit, {ON_HAND} AS on_hand FROM stock_items i WHERE i.id=?", (mv["item_id"],))
                if mv["q"] > it["on_hand"] + 1e-9:
                    raise ApiError(409, f"Cannot cancel: {it['name']} from this bill has already been used (only {it['on_hand']:g} {it['unit']} left)")
            c.conn.execute("INSERT INTO stock_moves(item_id,qty,kind,ref,note,user_id,at,invoice_id) VALUES(?,?,?,?,?,?,?,?)",
                           (mv["item_id"], -mv["q"], "return" if mv["q"] < 0 else "adjust", inv["number"],
                            f"Cancelled {inv['number']}", c.user["id"], stamp, iid))
        c.conn.execute("UPDATE invoices SET status='cancelled', cancelled_at=? WHERE id=?", (stamp, iid))
        return _invoice_full(c.conn, iid)


_register("sale", "sales")
_register("purchase", "purchases")


@route("GET", r"/api/jobs/(\d+)/invoice-draft", roles=OFFICE)
def job_invoice_draft(c: Ctx):
    """Pre-filled sales invoice for a job; nothing is saved until the user confirms."""
    j = need(one(c.conn, "SELECT * FROM jobs WHERE id=?", (int(c.params[0]),)), "Job")
    import json
    pre = None
    if j["quotation_id"]:
        q = one(c.conn, "SELECT result_json FROM quotations WHERE id=?", (j["quotation_id"],))
        if q:
            pre = json.loads(q["result_json"])["totals"].get("pre_tax")
    if pre is None:
        pre = r2(j["total"] / (1 + j["gst_pct"] / 100.0)) if j["total"] else 0
    existing = one(c.conn, "SELECT number FROM invoices WHERE job_id=? AND status='active' AND kind='sale' LIMIT 1", (j["id"],))
    return {"party_id": j["customer_id"], "job_id": j["id"], "order_no": j["order_no"], "existing_invoice": existing and existing["number"],
            "advance": j["advance"], "notes": f"Job {j['order_no']}",
            "lines": [{"description": f"{j['title']} ({j['copies']} copies)" if j["copies"] else j["title"], "hsn": j["hsn"],
                       "qty": 1, "unit": "job", "rate": r2(pre), "disc_pct": 0, "gst_rate": j["gst_pct"]}]}


# ---------------------------------------------------------------- payments

def _insert_payment(c: Ctx, kind: str, party_id: int, invoice_id, date: str, amount: float, mode: str, ref: str, note: str) -> int:
    _, number = db.next_number(c.conn, "receipt" if kind == "in" else "payment", "RCT" if kind == "in" else "PAY")
    cur = c.conn.execute(
        "INSERT INTO payments(kind,number,party_id,invoice_id,pay_date,amount,mode,ref,note,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (kind, number, party_id, invoice_id, date, r2(amount), mode, ref, note, c.user["id"], db.stamp()))
    return cur.lastrowid


@route("GET", "/api/payments", roles=OFFICE)
def payments_list(c: Ctx):
    sql = ("SELECT y.*, p.name AS party_name, i.number AS invoice_number FROM payments y JOIN customers p ON p.id=y.party_id "
           "LEFT JOIN invoices i ON i.id=y.invoice_id WHERE 1=1")
    args: list = []
    if c.query.get("kind") in ("in", "out"):
        sql += " AND y.kind=?"; args.append(c.query["kind"])
    if c.query.get("party_id"):
        sql += " AND y.party_id=?"; args.append(int(c.query["party_id"]))
    if c.query.get("from"):
        sql += " AND y.pay_date>=?"; args.append(c.query["from"])
    if c.query.get("to"):
        sql += " AND y.pay_date<=?"; args.append(c.query["to"])
    return rows(c.conn, sql + " ORDER BY y.pay_date DESC, y.id DESC LIMIT 1000", args)


@route("POST", "/api/payments", roles=OFFICE)
def payments_create(c: Ctx):
    v = clean(c.body, [("kind", "choice:in,out", True), ("party_id", "int", True), ("pay_date", "date", False),
                       ("amount", "pfloat", True), ("mode", "choice:" + PAY_MODES, False, "cash"), ("ref", "str", False),
                       ("note", "str", False)])
    need(one(c.conn, "SELECT id FROM customers WHERE id=?", (v["party_id"],)), "Party")
    inv_id = None
    if c.body.get("invoice_id") not in (None, "", 0):
        try:
            inv_id = int(c.body["invoice_id"])
        except (TypeError, ValueError):
            raise ApiError(422, "Invalid invoice") from None
        inv = _invoice_full(c.conn, inv_id)
        if inv["party_id"] != v["party_id"]:
            raise ApiError(422, "That invoice belongs to a different party")
        if inv["status"] != "active":
            raise ApiError(409, "That invoice is cancelled")
        if (inv["kind"] == "sale") != (v["kind"] == "in"):
            raise ApiError(422, "Receipts go against sales invoices and payments against purchase bills")
        if v["amount"] > inv["due"] + 0.005:
            raise ApiError(422, f"Only {inv['due']:.2f} is still due on {inv['number']}")
    pid = _insert_payment(c, v["kind"], v["party_id"], inv_id, v["pay_date"] or db.today(), v["amount"], v["mode"], v["ref"], v["note"])
    return 201, one(c.conn, "SELECT * FROM payments WHERE id=?", (pid,))


@route("DELETE", r"/api/payments/(\d+)", roles=OFFICE)
def payments_delete(c: Ctx):
    pid = int(c.params[0])
    need(one(c.conn, "SELECT id FROM payments WHERE id=?", (pid,)), "Payment")
    c.conn.execute("DELETE FROM payments WHERE id=?", (pid,))
    return {"deleted": True}


# ---------------------------------------------------------------- reports

@route("GET", "/api/reports/register", roles=OFFICE)
def rpt_register(c: Ctx):
    kind = c.query.get("kind", "sale")
    if kind not in ("sale", "purchase"):
        raise ApiError(422, "kind must be sale or purchase")
    f, t = _range(c)
    sql = ("SELECT i.id,i.number,i.party_ref,i.inv_date,i.taxable,i.cgst,i.sgst,i.igst,i.round_off,i.total,p.name AS party_name,p.gstin "
           "FROM invoices i JOIN customers p ON p.id=i.party_id WHERE i.kind=? AND i.status='active' AND i.inv_date>=? AND i.inv_date<=?")
    args: list = [kind, f, t]
    if c.query.get("party_id"):
        sql += " AND i.party_id=?"; args.append(int(c.query["party_id"]))
    out = rows(c.conn, sql + " ORDER BY i.inv_date, i.id", args)
    tot = {k: r2(sum(r[k] for r in out)) for k in ("taxable", "cgst", "sgst", "igst", "round_off", "total")}
    return {"from": f, "to": t, "kind": kind, "rows": out, "totals": tot}


def _balance_rows(conn, party_id: int, before: str | None = None):
    """Ledger entries for one party, oldest first. Each has `delta` (+ = they owe us more)."""
    ents = []
    for r in rows(conn, "SELECT id,kind,number,party_ref,inv_date AS d,total FROM invoices WHERE party_id=? AND status='active'", (party_id,)):
        ents.append({"date": r["d"], "type": "Sales invoice" if r["kind"] == "sale" else "Purchase bill", "number": r["number"],
                     "ref": r["party_ref"], "delta": r["total"] if r["kind"] == "sale" else -r["total"], "id": r["id"], "src": r["kind"]})
    for r in rows(conn, "SELECT id,kind,number,pay_date AS d,amount,mode,ref FROM payments WHERE party_id=?", (party_id,)):
        ents.append({"date": r["d"], "type": "Receipt" if r["kind"] == "in" else "Payment made", "number": r["number"],
                     "ref": f"{r['mode']} {r['ref']}".strip(), "delta": -r["amount"] if r["kind"] == "in" else r["amount"], "id": r["id"], "src": "pay"})
    ents.sort(key=lambda e: (e["date"], e["number"]))
    return ents


@route("GET", r"/api/parties/(\d+)/statement", roles=OFFICE)
def party_statement(c: Ctx):
    pid = int(c.params[0])
    party = _party_row(c.conn, pid)
    f, t = _range(c)
    ents = _balance_rows(c.conn, pid)
    opening = r2(party["opening_balance"] + sum(e["delta"] for e in ents if e["date"] < f))
    run, out = opening, []
    for e in ents:
        if f <= e["date"] <= t:
            run = r2(run + e["delta"])
            out.append({**e, "debit": r2(e["delta"]) if e["delta"] > 0 else 0, "credit": r2(-e["delta"]) if e["delta"] < 0 else 0, "balance": run})
    return {"party": party, "from": f, "to": t, "opening": opening, "rows": out, "closing": run}


@route("GET", "/api/reports/outstanding", roles=OFFICE)
def rpt_outstanding(c: Ctx):
    kind = c.query.get("kind", "receivable")
    if kind not in ("receivable", "payable"):
        raise ApiError(422, "kind must be receivable or payable")
    sign = 1 if kind == "receivable" else -1
    inv_kind = "sale" if kind == "receivable" else "purchase"
    today = datetime.strptime(db.today(), "%Y-%m-%d")
    out, tot = [], {"balance": 0.0, "b0": 0.0, "b1": 0.0, "b2": 0.0, "b3": 0.0, "other": 0.0}
    for p in rows(c.conn, f"SELECT p.id,p.name,p.phone1,{BAL_SQL} AS balance FROM customers p ORDER BY p.name COLLATE NOCASE"):
        bal = r2(p["balance"] * sign)
        if bal <= 0.004:
            continue
        b = [0.0, 0.0, 0.0, 0.0]
        for i in rows(c.conn, "SELECT i.inv_date, i.total, COALESCE((SELECT SUM(amount) FROM payments y WHERE y.invoice_id=i.id),0) paid "
                              "FROM invoices i WHERE i.party_id=? AND i.kind=? AND i.status='active'", (p["id"], inv_kind)):
            due = i["total"] - i["paid"]
            if due <= 0.004:
                continue
            age = (today - datetime.strptime(i["inv_date"], "%Y-%m-%d")).days
            b[0 if age <= 30 else 1 if age <= 60 else 2 if age <= 90 else 3] += due
        other = r2(bal - sum(b))
        row = {"id": p["id"], "name": p["name"], "phone": p["phone1"], "balance": bal, "b0": r2(b[0]), "b1": r2(b[1]),
               "b2": r2(b[2]), "b3": r2(b[3]), "other": other}
        out.append(row)
        for k in tot:
            tot[k] = r2(tot[k] + row[k])
    return {"kind": kind, "rows": out, "totals": tot}


@route("GET", "/api/reports/stock", roles=OFFICE)
def rpt_stock(c: Ctx):
    items = rows(c.conn, f"SELECT i.id,i.name,i.category,i.unit,i.hsn,i.purchase_price,i.sale_price,i.reorder_level,{ON_HAND} AS on_hand "
                         "FROM stock_items i WHERE i.active=1 AND i.track_stock=1 ORDER BY i.category, i.name COLLATE NOCASE")
    total = 0.0
    for r in items:
        r["on_hand"] = round(r["on_hand"], 3)
        r["value"] = r2(r["on_hand"] * r["purchase_price"])
        r["low"] = r["reorder_level"] > 0 and r["on_hand"] <= r["reorder_level"]
        total += r["value"]
    return {"rows": items, "total_value": r2(total)}


@route("GET", "/api/reports/gst", roles=OFFICE)
def rpt_gst(c: Ctx):
    f, t = _range(c)

    def side(kind):
        by_rate = rows(c.conn, "SELECT l.gst_rate, SUM(l.taxable) taxable, SUM(l.cgst) cgst, SUM(l.sgst) sgst, SUM(l.igst) igst "
                               "FROM invoice_lines l JOIN invoices i ON i.id=l.invoice_id WHERE i.kind=? AND i.status='active' "
                               "AND i.inv_date>=? AND i.inv_date<=? GROUP BY l.gst_rate ORDER BY l.gst_rate", (kind, f, t))
        for r in by_rate:
            for k in ("taxable", "cgst", "sgst", "igst"):
                r[k] = r2(r[k])
        tot = {k: r2(sum(r[k] for r in by_rate)) for k in ("taxable", "cgst", "sgst", "igst")}
        return by_rate, tot

    out_rate, out_tot = side("sale")
    in_rate, in_tot = side("purchase")
    net = {k: r2(out_tot[k] - in_tot[k]) for k in ("cgst", "sgst", "igst")}
    net["total"] = r2(sum(net.values()))
    hsn = rows(c.conn, "SELECT l.hsn, l.gst_rate, SUM(l.qty) qty, SUM(l.taxable) taxable, SUM(l.cgst+l.sgst+l.igst) tax "
                       "FROM invoice_lines l JOIN invoices i ON i.id=l.invoice_id WHERE i.kind='sale' AND i.status='active' "
                       "AND i.inv_date>=? AND i.inv_date<=? GROUP BY l.hsn, l.gst_rate ORDER BY l.hsn", (f, t))
    for r in hsn:
        r["taxable"], r["tax"] = r2(r["taxable"]), r2(r["tax"])
    return {"from": f, "to": t, "output": {"rows": out_rate, "totals": out_tot}, "input": {"rows": in_rate, "totals": in_tot},
            "net": net, "hsn": hsn}


def _stock_value_before(conn, date: str) -> float:
    """Stock value at the start of `date`, valued at each item's latest purchase price."""
    r = one(conn, "SELECT COALESCE(SUM(q*price),0) v FROM (SELECT SUM(m.qty) q, i.purchase_price price FROM stock_moves m "
                  "JOIN stock_items i ON i.id=m.item_id WHERE i.track_stock=1 AND substr(m.at,1,10)<? GROUP BY m.item_id)", (date,))
    return r2(r["v"])


@route("GET", "/api/reports/pnl", roles=OFFICE)
def rpt_pnl(c: Ctx):
    f, t = _range(c)
    nxt = (datetime.strptime(t, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    sales = one(c.conn, "SELECT COALESCE(SUM(taxable),0) s FROM invoices WHERE kind='sale' AND status='active' AND inv_date>=? AND inv_date<=?", (f, t))["s"]
    buy = rows(c.conn, "SELECT (i2.id IS NOT NULL AND i2.track_stock=1) AS is_stock, SUM(l.taxable) s FROM invoice_lines l "
                       "JOIN invoices i ON i.id=l.invoice_id LEFT JOIN stock_items i2 ON i2.id=l.item_id "
                       "WHERE i.kind='purchase' AND i.status='active' AND i.inv_date>=? AND i.inv_date<=? GROUP BY 1", (f, t))
    stock_buy = r2(sum(r["s"] for r in buy if r["is_stock"]))
    expenses = r2(sum(r["s"] for r in buy if not r["is_stock"]))
    opening, closing = _stock_value_before(c.conn, f), _stock_value_before(c.conn, nxt)
    # Stock that arrived outside a purchase bill (opening stock, counts, returns) is added at the latest buying price.
    other = r2(one(c.conn, "SELECT COALESCE(SUM(m.qty*i.purchase_price),0) v FROM stock_moves m JOIN stock_items i ON i.id=m.item_id "
                           "WHERE i.track_stock=1 AND m.invoice_id IS NULL AND m.qty>0 AND substr(m.at,1,10)>=? AND substr(m.at,1,10)<?", (f, nxt))["v"])
    cogs = r2(opening + stock_buy + other - closing)
    gross = r2(sales - cogs)
    return {"from": f, "to": t, "sales": r2(sales), "opening_stock": opening, "stock_purchases": stock_buy, "other_additions": other, "closing_stock": closing,
            "cost_of_goods": cogs, "gross_profit": gross, "expenses": expenses, "net_profit": r2(gross - expenses),
            "note": "Stock is valued at each item's latest purchase price, so the profit is an estimate."}


@route("GET", "/api/reports/daybook", roles=OFFICE)
def rpt_daybook(c: Ctx):
    f, t = _range(c)
    ents = []
    for r in rows(c.conn, "SELECT i.id,i.kind,i.number,i.inv_date d,i.total,i.status,p.name FROM invoices i JOIN customers p ON p.id=i.party_id "
                          "WHERE i.inv_date>=? AND i.inv_date<=?", (f, t)):
        ents.append({"date": r["d"], "type": "Sales invoice" if r["kind"] == "sale" else "Purchase bill", "number": r["number"], "party": r["name"],
                     "amount": r["total"], "cancelled": r["status"] != "active", "in": 0, "out": 0})
    for r in rows(c.conn, "SELECT y.kind,y.number,y.pay_date d,y.amount,y.mode,p.name FROM payments y JOIN customers p ON p.id=y.party_id "
                          "WHERE y.pay_date>=? AND y.pay_date<=?", (f, t)):
        ents.append({"date": r["d"], "type": "Receipt" if r["kind"] == "in" else "Payment made", "number": r["number"], "party": r["name"],
                     "amount": r["amount"], "mode": r["mode"], "cancelled": False,
                     "in": r["amount"] if r["kind"] == "in" else 0, "out": r["amount"] if r["kind"] == "out" else 0})
    ents.sort(key=lambda e: (e["date"], e["number"]))
    return {"from": f, "to": t, "rows": ents, "money_in": r2(sum(e["in"] for e in ents)), "money_out": r2(sum(e["out"] for e in ents))}


def account_summary(conn) -> dict:
    """Totals for the dashboard."""
    recv = pay = 0.0
    for p in rows(conn, f"SELECT {BAL_SQL} AS b FROM customers p"):
        if p["b"] > 0:
            recv += p["b"]
        else:
            pay -= p["b"]
    m = db.today()[:7]
    return {"receivable": r2(recv), "payable": r2(pay),
            "sales_month": r2(one(conn, "SELECT COALESCE(SUM(total),0) s FROM invoices WHERE kind='sale' AND status='active' AND substr(inv_date,1,7)=?", (m,))["s"]),
            "purchases_month": r2(one(conn, "SELECT COALESCE(SUM(total),0) s FROM invoices WHERE kind='purchase' AND status='active' AND substr(inv_date,1,7)=?", (m,))["s"])}
