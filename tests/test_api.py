import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from press import auth, db, demo, server  # noqa: E402


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "t.db")
        db.init_db(cls.path)
        conn = db.connect(cls.path)
        auth.create_user(conn, "boss", "Boss", "manager", "boss-password-1")
        conn.commit()
        conn.close()
        demo.seed(cls.path)  # desk / super / operator users + sample data
        cls.srv = server.make_server("127.0.0.1", 0, cls.path)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.tokens = {}

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def call(self, method, path, body=None, token=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def login(self, user, pw):
        key = (user, pw)
        if key not in self.tokens:
            s, d = self.call("POST", "/api/login", {"username": user, "password": pw})
            self.assertEqual(s, 200, d)
            self.tokens[key] = d["token"]
        return self.tokens[key]

    def boss(self):
        return self.login("boss", "boss-password-1")

    def role(self, name):
        return self.login(name, demo.DEMO_PASSWORD)

    # ------------------------------------------------------------------
    def test_auth_required_and_bad_login(self):
        self.assertEqual(self.call("GET", "/api/jobs")[0], 401)
        self.assertEqual(self.call("POST", "/api/login", {"username": "boss", "password": "nope"})[0], 401)
        self.assertEqual(self.call("GET", "/api/jobs", token="garbage")[0], 401)

    def test_static_and_traversal(self):
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertEqual(r.status, 200)
        for bad in ("/../press/db.py", "/..%2fpress/db.py", "/%2e%2e/press/db.py"):
            try:
                urllib.request.urlopen(self.base + bad)
                self.fail("traversal allowed: " + bad)
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 404)

    def test_roles_and_money_hidden(self):
        op, boss = self.role("operator"), self.boss()
        s, jobs = self.call("GET", "/api/jobs", token=op)
        self.assertEqual(s, 200)
        self.assertTrue(jobs)
        for j in jobs:
            for k in ("total", "advance", "gst_pct", "balance", "receipt_no", "bill_no"):
                self.assertNotIn(k, j)
        s, jobs = self.call("GET", "/api/jobs", token=boss)
        self.assertIn("total", jobs[0])
        self.assertEqual(self.call("GET", "/api/quotations", token=op)[0], 403)
        self.assertEqual(self.call("GET", "/api/papers", token=op)[0], 403)
        self.assertEqual(self.call("GET", "/api/users", token=self.role("desk"))[0], 403)
        self.assertEqual(self.call("PUT", "/api/settings", {"gst_pct": 5}, token=self.role("desk"))[0], 403)

    def test_stage_permissions_and_timeline(self):
        boss, op, desk = self.boss(), self.role("operator"), self.role("desk")
        j = next(x for x in self.call("GET", "/api/jobs?stage=printing", token=boss)[1])
        s, d = self.call("POST", f"/api/jobs/{j['id']}/stage", {"stage": "finishing", "note": "done"}, token=op)
        self.assertEqual(s, 200)
        self.assertEqual(d["stage"], "finishing")
        self.assertEqual(d["events"][0]["kind"], "stage")
        self.assertEqual(self.call("POST", f"/api/jobs/{j['id']}/stage", {"stage": "billed"}, token=op)[0], 403)
        self.assertEqual(self.call("POST", f"/api/jobs/{j['id']}/stage", {"stage": "finishing"}, token=op)[0], 409)
        self.assertEqual(self.call("POST", f"/api/jobs/{j['id']}/stage", {"stage": "nonsense"}, token=op)[0], 422)
        self.assertEqual(self.call("POST", f"/api/jobs/{j['id']}/stage", {"stage": "ready"}, token=desk)[0], 200)
        s, d = self.call("POST", f"/api/jobs/{j['id']}/note", {"note": "Paper short by 20 sheets"}, token=op)
        self.assertEqual(s, 200)
        self.assertEqual(d["events"][0]["note"], "Paper short by 20 sheets")
        self.assertNotIn("total", d)

    def test_quotation_lifecycle(self):
        boss = self.boss()
        s, boot = self.call("GET", "/api/bootstrap", token=boss)
        m = boot["masters"]
        spec = dict(size_w=6, size_h=9, copies=300, margin_pct=25, gst_pct=12,
                    components=[dict(name="Sheet", paper_id=m["papers"][1]["id"], pages=2, color_mode="multi",
                                     machine_id=next(x["id"] for x in m["machines"] if x["name"].startswith("Komori")),
                                     plate_id=m["plates"][0]["id"])])
        cust = self.call("POST", "/api/customers", {"name": "Test Customer"}, token=boss)[1]
        s, est = self.call("POST", "/api/estimate", {"spec": spec, "quantities": [100, 300, 1000]}, token=boss)
        self.assertEqual(s, 200, est)
        self.assertEqual(len(est["breaks"]), 3)

        s, q = self.call("POST", "/api/quotations", {"customer_id": cust["id"], "title": "Invites", "spec": spec}, token=boss)
        self.assertEqual(s, 201, q)
        self.assertTrue(q["number"].startswith("Q-"))
        self.assertEqual(q["total"], est["totals"]["total"])
        self.assertEqual(q["status"], "draft")

        s, q2 = self.call("POST", "/api/quotations", {"customer_id": cust["id"], "title": "Second", "spec": spec}, token=boss)
        self.assertNotEqual(q["number"], q2["number"])

        # invalid spec is a readable 422, nothing saved
        bad = dict(spec, copies=0)
        s, err = self.call("POST", "/api/quotations", {"customer_id": cust["id"], "title": "x", "spec": bad}, token=boss)
        self.assertEqual(s, 422)
        self.assertIn("Copies", err["error"])

        # edit while draft
        s, q = self.call("PUT", f"/api/quotations/{q['id']}", {"customer_id": cust["id"], "title": "Invites v2",
                                                              "spec": dict(spec, copies=500)}, token=boss)
        self.assertEqual((s, q["copies"], q["title"]), (200, 500, "Invites v2"))

        self.assertEqual(self.call("POST", f"/api/quotations/{q['id']}/status", {"status": "sent"}, token=boss)[0], 200)
        self.assertEqual(self.call("POST", f"/api/quotations/{q['id']}/status", {"status": "converted"}, token=boss)[0], 409)

        s, job = self.call("POST", f"/api/quotations/{q['id']}/convert",
                           {"delivery_date": "2026-12-01", "advance": 1000}, token=boss)
        self.assertEqual(s, 201, job)
        self.assertEqual(job["stage"], "approved")
        self.assertEqual(job["total"], q["total"])
        self.assertEqual(job["balance"], round(q["total"] - 1000, 2))
        self.assertEqual(job["work"]["pages"]["m_color"], 2)
        self.assertEqual(job["events"][0]["kind"], "created")

        # converting twice / editing after convert are refused
        self.assertEqual(self.call("POST", f"/api/quotations/{q['id']}/convert", {}, token=boss)[0], 409)
        self.assertEqual(self.call("PUT", f"/api/quotations/{q['id']}", {"customer_id": cust["id"], "title": "z", "spec": spec}, token=boss)[0], 409)
        self.assertEqual(self.call("DELETE", f"/api/quotations/{q['id']}", token=boss)[0], 409)
        # a draft can be deleted
        self.assertEqual(self.call("DELETE", f"/api/quotations/{q2['id']}", token=boss)[0], 200)

        # rate change does not alter a saved quotation until recalculated
        paper = m["papers"][1]
        self.call("PUT", f"/api/papers/{paper['id']}", {"rate_per_ream": paper["rate_per_ream"] * 2}, token=boss)
        s, again = self.call("GET", f"/api/quotations/{q['id']}", token=boss)
        self.assertEqual(again["total"], q["total"])

    def test_job_edit_permissions(self):
        boss, sup, op = self.boss(), self.role("super"), self.role("operator")
        j = self.call("GET", "/api/jobs?open=1", token=boss)[1][0]
        s, d = self.call("PUT", f"/api/jobs/{j['id']}", {"designer": "Anu", "advance": 99999}, token=sup)
        self.assertEqual(s, 200)
        self.assertEqual(d["designer"], "Anu")
        s, d = self.call("GET", f"/api/jobs/{j['id']}", token=boss)
        self.assertNotEqual(d["advance"], 99999)  # superintendent cannot touch money fields
        self.assertEqual(self.call("PUT", f"/api/jobs/{j['id']}", {"designer": "x"}, token=op)[0], 403)
        self.assertEqual(self.call("PUT", f"/api/jobs/{j['id']}", {"delivery_date": "31/12/2026"}, token=boss)[0], 422)

    def test_user_management_guards(self):
        boss = self.boss()
        s, me = self.call("GET", "/api/bootstrap", token=boss)
        uid = me["user"]["id"]
        self.assertEqual(self.call("PUT", f"/api/users/{uid}", {"role": "desk"}, token=boss)[0], 422)
        self.assertEqual(self.call("PUT", f"/api/users/{uid}", {"active": False}, token=boss)[0], 422)
        self.assertEqual(self.call("POST", "/api/users", {"username": "x", "name": "X", "role": "desk", "password": "short"}, token=boss)[0], 422)
        self.assertEqual(self.call("POST", "/api/users", {"username": "boss", "name": "X", "role": "desk", "password": "longenough1"}, token=boss)[0], 409)
        s, u = self.call("POST", "/api/users", {"username": "temp1", "name": "Temp", "role": "operator", "password": "longenough1"}, token=boss)
        self.assertEqual(s, 201)
        tok = self.login("temp1", "longenough1")
        self.assertEqual(self.call("GET", "/api/jobs", token=tok)[0], 200)
        self.call("PUT", f"/api/users/{u['id']}", {"active": False}, token=boss)
        self.assertEqual(self.call("GET", "/api/jobs", token=tok)[0], 401)  # sessions end when deactivated

    def test_dashboard_and_masters(self):
        boss, op = self.boss(), self.role("operator")
        s, d = self.call("GET", "/api/dashboard", token=boss)
        self.assertEqual(s, 200)
        self.assertIn("quotes", d)
        self.assertIn("overdue", d)
        s, d = self.call("GET", "/api/dashboard", token=op)
        self.assertNotIn("quotes", d)
        s, p = self.call("POST", "/api/papers", {"name": "X", "width_in": 0, "height_in": 10, "rate_per_ream": 5}, token=boss)
        self.assertEqual(s, 422)
        s, p = self.call("POST", "/api/papers", {"name": "Tmp paper", "width_in": 10, "height_in": 10, "rate_per_ream": 5}, token=boss)
        self.assertEqual(s, 201)
        self.assertEqual(self.call("DELETE", f"/api/papers/{p['id']}", token=boss)[1]["deactivated"], True)
        ids = [x["id"] for x in self.call("GET", "/api/papers", token=boss)[1]]
        self.assertNotIn(p["id"], ids)

    def test_malformed_requests(self):
        boss = self.boss()
        req = urllib.request.Request(self.base + "/api/customers", method="POST", data=b"{not json",
                                     headers={"Authorization": "Bearer " + boss, "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(self.call("POST", "/api/customers", [1, 2], token=boss)[0], 400)
        self.assertEqual(self.call("GET", "/api/nothing", token=boss)[0], 404)
        self.assertEqual(self.call("DELETE", "/api/jobs/1", token=boss)[0], 405)

    # ---------------------------------------------------------- reel paper, assignment, stock
    def test_kg_paper_costing(self):
        boss = self.boss()
        s, p = self.call("POST", "/api/papers", {"name": "Reel A", "gsm": 0, "width_in": 23, "height_in": 36,
                                                 "pricing": "kg", "rate_per_kg": 80}, token=boss)
        self.assertEqual(s, 422)  # needs GSM
        s, p = self.call("POST", "/api/papers", {"name": "Reel A", "gsm": 70, "width_in": 23, "height_in": 36,
                                                 "pricing": "kg", "rate_per_kg": 80}, token=boss)
        self.assertEqual(s, 201, p)
        m = self.call("GET", "/api/machines", token=boss)[1][0]
        pl = self.call("GET", "/api/plates", token=boss)[1][0]
        spec = {"size_w": 5.5, "size_h": 8.5, "copies": 1000, "margin_pct": 0, "gst_pct": 0, "wastage_pct": 0,
                "components": [{"name": "Text", "part": "text", "paper_id": p["id"], "pages": 32, "color_mode": "bw",
                                "machine_id": m["id"], "plate_id": pl["id"]}]}
        s, r = self.call("POST", "/api/estimate", {"spec": spec}, token=boss)
        self.assertEqual(s, 200, r)
        comp = r["components"][0]
        kg = comp["sheets_gross"] * 23 * 36 * 0.00064516 * 70 / 1000
        self.assertAlmostEqual(comp["paper_kg"], kg, places=2)
        self.assertAlmostEqual(comp["paper_cost"], kg * 80, delta=0.5)
        self.assertEqual(comp["paper_basis"], "kg")

    def test_kg_paper_without_sheet_size(self):
        boss = self.boss()
        s, p = self.call("POST", "/api/papers", {"name": "Roll B", "gsm": 70, "pricing": "kg", "rate_per_kg": 90}, token=boss)
        self.assertEqual(s, 201, p)
        self.assertEqual(self.call("POST", "/api/papers", {"name": "Bad", "gsm": 70, "width_in": 20, "pricing": "kg", "rate_per_kg": 9}, token=boss)[0], 422)
        self.assertEqual(self.call("POST", "/api/papers", {"name": "Bad2", "pricing": "ream", "rate_per_ream": 9}, token=boss)[0], 422)
        m = self.call("GET", "/api/machines", token=boss)[1][0]
        pl = self.call("GET", "/api/plates", token=boss)[1][0]
        part = {"name": "Text", "part": "text", "paper_id": p["id"], "pages": 100, "color_mode": "bw", "machine_id": m["id"], "plate_id": pl["id"]}
        spec = {"size_w": 8.27, "size_h": 11.69, "copies": 1, "margin_pct": 0, "gst_pct": 0, "wastage_pct": 0, "components": [part]}
        self.assertEqual(self.call("POST", "/api/estimate", {"spec": spec}, token=boss)[0], 422)  # needs pages per sheet side
        part["ups"] = 1
        s, r = self.call("POST", "/api/estimate", {"spec": spec}, token=boss)
        self.assertEqual(s, 200, r)
        c = r["components"][0]
        self.assertTrue(c["paper_by_area"])
        # 1 up per sheet side: area printed = sheets x 8.27 x 11.69 in2 at 70 gsm
        self.assertAlmostEqual(c["paper_kg"], c["sheets_gross"] * 8.27 * 11.69 * 0.00064516 * 70 / 1000, places=2)

    def test_paper_weight_table(self):
        boss = self.boss()
        s, p = self.call("POST", "/api/papers", {"name": "Own weights", "pricing": "kg", "rate_per_kg": 50, "weight_mode": "table"}, token=boss)
        self.assertEqual(s, 201, p)  # no GSM needed in table mode
        self.assertEqual(self.call("PUT", f"/api/papers/{p['id']}/sizes", {"sizes": [
            {"name": "A4", "width_in": 8.27, "height_in": 11.69, "kg_per_100": 0.45},
            {"name": "A4 again", "width_in": 11.69, "height_in": 8.27, "kg_per_100": 0.5}]}, token=boss)[0], 422)  # duplicate size
        s, sizes = self.call("PUT", f"/api/papers/{p['id']}/sizes", {"sizes": [
            {"name": "A4", "width_in": 8.27, "height_in": 11.69, "kg_per_100": 0.45}]}, token=boss)
        self.assertEqual((s, len(sizes)), (200, 1))
        self.assertEqual(self.call("PUT", f"/api/papers/{p['id']}/sizes", {"sizes": []}, token=self.role("desk"))[0], 403)
        m = self.call("GET", "/api/machines", token=boss)[1][0]
        pl = self.call("GET", "/api/plates", token=boss)[1][0]
        part = {"name": "Text", "part": "text", "paper_id": p["id"], "pages": 100, "color_mode": "bw", "machine_id": m["id"], "plate_id": pl["id"], "ups": 1}
        spec = {"size_w": 8.27, "size_h": 11.69, "copies": 1, "margin_pct": 0, "gst_pct": 0, "wastage_pct": 0, "components": [part]}
        s, r = self.call("POST", "/api/estimate", {"spec": spec}, token=boss)
        self.assertEqual(s, 200, r)
        c = r["components"][0]
        self.assertEqual(c["paper_weight_src"], "table")
        self.assertAlmostEqual(c["paper_kg"], c["sheets_gross"] * 0.45 / 100, places=3)
        self.assertAlmostEqual(c["paper_cost"], c["paper_kg"] * 50, delta=0.05)
        spec["size_w"], spec["size_h"] = 5.83, 8.27  # A5 is not in the table
        s, r = self.call("POST", "/api/estimate", {"spec": spec}, token=boss)
        self.assertEqual(s, 422)
        self.assertIn("no weight is entered", r["error"])

    def test_assignment_progress_and_monitor(self):
        boss, op, desk = self.boss(), self.role("operator"), self.role("desk")
        jobs = self.call("GET", "/api/jobs", token=boss)[1]
        jid = jobs[0]["id"]
        people = self.call("GET", "/api/people", token=op)[1]
        self.assertTrue(all("pw_hash" not in x for x in people))
        op_id = next(x["id"] for x in people if x["name"] == "Machine Operator")
        other = next(x["id"] for x in people if x["role"] == "desk")
        s, j = self.call("POST", f"/api/jobs/{jid}/assign", {"user_id": op_id, "note": "go"}, token=desk)
        self.assertEqual(s, 200)
        self.assertEqual(j["assigned_to"], op_id)
        # the holder may report progress and hand over; a different operator may not
        self.assertEqual(self.call("POST", f"/api/jobs/{jid}/progress", {"progress_pct": 40}, token=op)[0], 200)
        self.assertEqual(self.call("POST", f"/api/jobs/{jid}/progress", {"progress_pct": 140}, token=boss)[0], 422)
        self.assertEqual(self.call("POST", f"/api/jobs/{jid}/assign", {"user_id": 99999}, token=boss)[0], 422)
        s, j = self.call("POST", f"/api/jobs/{jid}/assign", {"user_id": other}, token=op)
        self.assertEqual(s, 200)
        self.assertEqual(j["progress_pct"], 0)
        self.assertEqual(self.call("POST", f"/api/jobs/{jid}/progress", {"progress_pct": 10}, token=op)[0], 403)
        self.assertEqual(self.call("GET", "/api/monitor", token=op)[0], 403)
        s, mon = self.call("GET", "/api/monitor", token=boss)
        self.assertEqual(s, 200)
        self.assertTrue(any(p["id"] == other and p["jobs"] for p in mon["people"]))
        self.assertEqual(len(self.call("GET", "/api/jobs?mine=1", token=desk)[1]) >= 1, True)

    def test_stock_flow(self):
        boss, op, desk = self.boss(), self.role("operator"), self.role("desk")
        s, it = self.call("POST", "/api/stock", {"name": "Test reel", "unit": "kg", "reorder_level": 10, "opening_qty": 50}, token=desk)
        self.assertEqual(s, 201, it)
        self.assertEqual(it["on_hand"], 50)
        iid = it["id"]
        self.assertEqual(self.call("POST", "/api/stock", {"name": "x", "unit": "kg"}, token=op)[0], 403)
        self.assertEqual(self.call("POST", f"/api/stock/{iid}/move", {"kind": "receive", "qty": 5}, token=op)[0], 403)
        s, it = self.call("POST", f"/api/stock/{iid}/move", {"kind": "issue", "qty": 45}, token=op)
        self.assertEqual((s, it["on_hand"], it["low"]), (200, 5, True))
        self.assertEqual(self.call("POST", f"/api/stock/{iid}/move", {"kind": "issue", "qty": 6}, token=op)[0], 409)
        self.assertEqual(self.call("POST", f"/api/stock/{iid}/move", {"kind": "issue", "qty": -1}, token=op)[0], 422)
        self.assertEqual(self.call("POST", f"/api/stock/{iid}/move", {"kind": "adjust", "counted": 7}, token=desk)[0], 422)  # needs reason
        s, it = self.call("POST", f"/api/stock/{iid}/move", {"kind": "adjust", "counted": 7, "note": "recount"}, token=desk)
        self.assertEqual(it["on_hand"], 7)
        self.assertEqual(self.call("GET", f"/api/stock/{iid}/moves", token=op)[0], 403)
        self.assertEqual(len(self.call("GET", f"/api/stock/{iid}/moves", token=boss)[1]), 3)
        self.assertEqual(self.call("DELETE", f"/api/stock/{iid}", token=boss)[1]["deactivated"], True)

    def test_job_materials_and_issue(self):
        boss = self.boss()
        jobs = self.call("GET", "/api/jobs", token=boss)[1]
        j = next(x for x in jobs if "reel" in x["title"])
        full = self.call("GET", f"/api/jobs/{j['id']}", token=boss)[1]
        reel = next(m for m in full["materials"] if "Apelitho" in m["paper"])
        self.assertEqual(reel["unit"], "kg")
        self.assertAlmostEqual(reel["need"], reel["kg"], places=2)
        self.assertEqual(reel["issued"], 65)


if __name__ == "__main__":
    unittest.main()
