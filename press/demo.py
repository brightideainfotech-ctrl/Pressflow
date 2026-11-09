"""Sample data for trying the app out (python3 -m press.server --demo).

Goes through the real API handlers, so the demo exercises exactly the code
that real use does. Demo users all share one obvious password: use this on a
test machine only, never on a database with real data.
"""
from __future__ import annotations

from . import api, auth, db

DEMO_PASSWORD = "demo-pass-1"


def seed(db_path: str | None = None) -> None:
    conn = db.connect(db_path)
    try:
        if conn.execute("SELECT COUNT(*) FROM quotations").fetchone()[0]:
            return
        for username, name, role, dept in (
                ("desk", "Front Desk", "desk", "Office"), ("super", "Superintendent", "superintendent", "Production"),
                ("operator", "Machine Operator", "operator", "Press"), ("designer", "Mr. X (Designer)", "operator", "Design"),
                ("binder", "Binding Section", "operator", "Binding")):
            if not conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                uid = auth.create_user(conn, username, name, role, DEMO_PASSWORD)
                conn.execute("UPDATE users SET department=? WHERE id=?", (dept, uid))
        mgr = conn.execute("SELECT id FROM users WHERE role='manager' AND active=1 ORDER BY id LIMIT 1").fetchone()["id"]
        token = auth.start_session(conn, mgr)

        def call(method, path, body=None, query=None):
            status, payload = api.handle(conn, method, path, query or {}, body, token, "demo")
            conn.commit()
            return payload

        def pid(name):
            return conn.execute("SELECT id FROM papers WHERE name LIKE ?", (name + "%",)).fetchone()["id"]

        def mid(name):
            return conn.execute("SELECT id FROM machines WHERE name LIKE ?", (name + "%",)).fetchone()["id"]

        def fid(name):
            return conn.execute("SELECT id FROM finishing WHERE name=?", (name,)).fetchone()["id"]

        plate = conn.execute("SELECT id FROM plate_types WHERE name='Polymaster'").fetchone()["id"]

        customers = [
            call("POST", "/api/customers", dict(name="St. Mary's High School", contact_person="Sr. Anitha",
                                                 phone1="9847000001", email="office@stmarys.example", address="Church Road, Cherthala", pin="688524")),
            call("POST", "/api/customers", dict(name="Greenfield Traders", contact_person="Mr. Joseph",
                                                 phone1="9847000002", address="Market Junction, Alappuzha", pin="688001")),
            call("POST", "/api/customers", dict(name="Holy Cross Parish", contact_person="Fr. Thomas",
                                                 phone1="9847000003", address="Cherthala", pin="688524")),
        ]

        magazine = dict(
            size_w=5.83, size_h=8.27, copies=500, margin_pct=25,
            components=[
                dict(name="Cover", part="cover", paper_id=pid("Art Card 250"), pages=4, color_mode="multi",
                     machine_id=mid("Komori"), plate_id=plate),
                dict(name="Text", part="text", paper_id=pid("Art Paper 130"), pages=64, color_mode="multi",
                     machine_id=mid("Komori"), plate_id=plate),
            ],
            finishing=[dict(finishing_id=fid("Centre pin")), dict(finishing_id=fid("Lamination Matt - single side"))],
            design_charge=1500,
        )
        cards = dict(
            size_w=3.5, size_h=2, copies=1000, margin_pct=30,
            components=[dict(name="Card", paper_id=pid("Art Card 250"), pages=2, color_mode="multi",
                             machine_id=mid("Komori"), plate_id=plate)],
            finishing=[dict(finishing_id=fid("Lamination Matt - both sides"))],
        )
        booklets = dict(
            size_w=8.27, size_h=11.69, copies=2000, margin_pct=20,
            components=[
                dict(name="Cover", part="cover", paper_id=pid("Maplitho 80 gsm 23x36"), pages=4, color_mode="two",
                     machine_id=mid("HMT 2 Color"), plate_id=plate),
                dict(name="Text", part="text", paper_id=pid("Maplitho 70"), pages=32, color_mode="bw",
                     machine_id=mid("HMT D/Demy"), plate_id=plate, ups=8),
            ],
            finishing=[dict(finishing_id=fid("Stitching"))],
        )

        q1 = call("POST", "/api/quotations", dict(customer_id=customers[0]["id"], title="School magazine 2026", spec=magazine))
        q2 = call("POST", "/api/quotations", dict(customer_id=customers[1]["id"], title="Visiting cards", spec=cards))
        q3 = call("POST", "/api/quotations", dict(customer_id=customers[2]["id"], title="Parish bulletin booklets", spec=booklets))
        call("POST", f"/api/quotations/{q2['id']}/status", dict(status="sent"))

        reel = dict(
            size_w=5.5, size_h=8.5, copies=3000, margin_pct=20,
            components=[
                dict(name="Cover", part="cover", paper_id=pid("Art Card 250"), pages=4, color_mode="multi",
                     machine_id=mid("Komori"), plate_id=plate),
                dict(name="Text", part="text", paper_id=pid("Apelitho 70"), pages=96, color_mode="bw",
                     machine_id=mid("HMT D/Demy"), plate_id=plate),
            ],
            finishing=[dict(finishing_id=fid("Stitching"))],
        )
        own = call("POST", "/api/papers", dict(name="Newsprint (own weights)", pricing="kg", rate_per_kg=48, weight_mode="table"))
        conn.commit()
        api.handle(conn, "PUT", f"/api/papers/{own['id']}/sizes", {}, {"sizes": [
            {"name": "A4", "width_in": 8.27, "height_in": 11.69, "kg_per_100": 0.28},
            {"name": "A5", "width_in": 5.83, "height_in": 8.27, "kg_per_100": 0.14},
            {"name": "Demy 1/8", "width_in": 5.5, "height_in": 8.5, "kg_per_100": 0.14}]}, token, "demo")
        conn.commit()
        q4 = call("POST", "/api/quotations", dict(customer_id=customers[0]["id"], title="Exam workbooks (reel paper)", spec=reel))
        uid = lambda u: conn.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()["id"]  # noqa: E731

        j1 = call("POST", f"/api/quotations/{q1['id']}/convert",
                  dict(delivery_date=_days(-2), proof_date=_days(-8), priority="urgent", advance=5000,
                       receipt_no="R-101", designer="Press DTP", extra_details="Cover proof approved by Sr. Anitha."))
        call("POST", f"/api/jobs/{j1['id']}/stage", dict(stage="design_proof"))
        call("POST", f"/api/jobs/{j1['id']}/stage", dict(stage="plates"))
        call("POST", f"/api/jobs/{j1['id']}/stage", dict(stage="printing", note="Started on Komori"))
        j3 = call("POST", f"/api/quotations/{q3['id']}/convert", dict(delivery_date=_days(6), advance=2000))
        call("POST", f"/api/jobs/{j3['id']}/stage", dict(stage="design_proof"))
        call("POST", f"/api/quotations/{q4['id']}/status", dict(status="accepted"))
        j4 = call("POST", f"/api/quotations/{q4['id']}/convert", dict(delivery_date=_days(9), advance=8000, assign_to=uid("designer")))

        # Hand-over and progress: who holds each job and what has been done so far.
        call("POST", f"/api/jobs/{j1['id']}/assign", dict(user_id=uid("operator"), note="Printing on Komori"))
        call("POST", f"/api/jobs/{j1['id']}/progress", dict(progress_pct=60, note="Cover done, text forms 5 of 8 printed"))
        call("POST", f"/api/jobs/{j3['id']}/assign", dict(user_id=uid("designer"), note="Layout from customer's matter"))
        call("POST", f"/api/jobs/{j3['id']}/progress", dict(progress_pct=40, note="Pages 1-12 laid out"))
        call("POST", f"/api/jobs/{j4['id']}/progress", dict(progress_pct=15, note="Cover design started"))

        # Stock
        def item(**kw):
            return call("POST", "/api/stock", kw)

        reel_item = item(name="Apelitho 70 gsm reel stock", category="paper", unit="kg", paper_id=pid("Apelitho 70"),
                         reorder_level=150, location="Paper store", opening_qty=420)
        item(name="Art Card 250 gsm 23x36", category="paper", unit="sheets", paper_id=pid("Art Card 250"),
             reorder_level=1000, location="Paper store", opening_qty=3500)
        item(name="Art Paper 130 gsm 23x36", category="paper", unit="sheets", paper_id=pid("Art Paper 130"),
             reorder_level=1500, opening_qty=1200)
        item(name="Polymaster plates", category="plates", unit="pcs", reorder_level=60, location="Plate room", opening_qty=210)
        ink = item(name="Black ink", category="ink", unit="kg", reorder_level=5, opening_qty=18)
        item(name="Matt lamination film", category="binding", unit="rolls", reorder_level=2, opening_qty=6)
        call("POST", f"/api/stock/{reel_item['id']}/move", dict(kind="issue", qty=65, job_id=j4["id"], note="First batch to press"))
        call("POST", f"/api/stock/{ink['id']}/move", dict(kind="issue", qty=14, note="Month usage"))
    finally:
        conn.close()


def _days(n: int) -> str:
    from datetime import timedelta
    return (db.now() + timedelta(days=n)).strftime("%Y-%m-%d")
