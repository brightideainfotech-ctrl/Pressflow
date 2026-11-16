"""Store keeping (material requests, approvals) and best-sheet-size suggestions."""
import os
import sqlite3
import tempfile
import unittest

from press import db, estimator
from tests.test_api import ApiTests


class StoreFlowTests(ApiTests):
    def _new_job(self, boss, paper_id, stock_item=True):
        m = self.call("GET", "/api/bootstrap", token=boss)[1]["masters"]
        spec = dict(size_w=21, size_h=29.7, copies=1000, margin_pct=25, gst_pct=12,
                    components=[dict(name="Text", paper_id=paper_id, pages=16, color_mode="multi",
                                     machine_id=next(x["id"] for x in m["machines"] if x["name"].startswith("Komori")),
                                     plate_id=m["plates"][0]["id"])])
        cust = self.call("POST", "/api/customers", {"name": "Store Test Co"}, token=boss)[1]
        q = self.call("POST", "/api/quotations", {"customer_id": cust["id"], "title": "Store job", "spec": spec}, token=boss)[1]
        job = self.call("POST", f"/api/quotations/{q['id']}/convert", {}, token=boss)[1]
        return job, spec

    def test_full_store_flow(self):
        boss = self.boss()
        s, u = self.call("POST", "/api/users", {"username": "store1", "name": "Stores", "role": "storekeeper",
                                                "password": "store-pass-123"}, token=boss)
        self.assertEqual(s, 201, u)
        keeper = self.login("store1", "store-pass-123")
        papers = self.call("GET", "/api/papers", token=boss)[1]
        linked = {i["paper_id"] for i in self.call("GET", "/api/stock", token=boss)[1]}
        paper = next(p for p in papers if p["pricing"] == "ream" and p["id"] not in linked)
        s, item = self.call("POST", "/api/stock", {"name": "Flow paper", "unit": "sheets", "paper_id": paper["id"],
                                                   "opening_qty": 100000}, token=boss)
        self.assertEqual(s, 201, item)

        job, _ = self._new_job(boss, paper["id"])
        reqs = [r for r in self.call("GET", "/api/store/requests", token=keeper)[1] if r["job_id"] == job["id"]]
        self.assertEqual(len(reqs), 1)
        r = reqs[0]
        self.assertEqual((r["status"], r["kind"], r["item_id"]), ("pending", "initial", item["id"]))

        # Only the store / manager can issue; floor staff cannot take stock directly
        op = self.role("operator")
        self.assertEqual(self.call("POST", f"/api/material-requests/{r['id']}/issue", {}, token=op)[0], 403)
        self.assertEqual(self.call("POST", f"/api/stock/{item['id']}/move", {"kind": "issue", "qty": 5, "job_id": job["id"]}, token=op)[0], 403)
        self.assertEqual(self.call("POST", f"/api/stock/{item['id']}/move", {"kind": "issue", "qty": 5, "job_id": job["id"]}, token=keeper)[0], 409)

        # cannot issue more than approved
        self.assertEqual(self.call("POST", f"/api/material-requests/{r['id']}/issue", {"qty": r["qty"] + 100}, token=keeper)[0], 409)
        s, done = self.call("POST", f"/api/material-requests/{r['id']}/issue", {}, token=keeper)
        self.assertEqual((s, done["status"], done["qty_issued"]), (200, "issued", r["qty"]))
        self.assertEqual(self.call("POST", f"/api/material-requests/{r['id']}/issue", {}, token=keeper)[0], 409)  # already closed

        # asking again for the same paper now needs a reason and the manager's authorisation
        sup = self.role("super")
        url = f"/api/jobs/{job['id']}/material-requests"
        self.assertEqual(self.call("POST", url, {"item_id": item["id"], "qty": 500}, token=sup)[0], 422)
        s, extra = self.call("POST", url, {"item_id": item["id"], "qty": 500, "reason": "Spoilage on press"}, token=sup)
        self.assertEqual((s, extra["status"], extra["kind"]), (201, "awaiting_approval", "additional"))
        self.assertEqual(self.call("POST", url, {"item_id": item["id"], "qty": 10, "reason": "again again"}, token=sup)[0], 409)  # duplicate open
        self.assertEqual(self.call("POST", f"/api/material-requests/{extra['id']}/issue", {}, token=keeper)[0], 409)  # not authorised yet
        self.assertEqual(self.call("POST", f"/api/material-requests/{extra['id']}/decide", {"approve": True}, token=keeper)[0], 403)
        self.assertEqual(self.call("POST", f"/api/material-requests/{extra['id']}/decide", {"approve": True}, token=sup)[0], 403)
        s, ok = self.call("POST", f"/api/material-requests/{extra['id']}/decide", {"approve": True, "qty": 300, "note": "ok"}, token=boss)
        self.assertEqual((s, ok["status"], ok["qty"]), (200, "pending", 300))
        s, done = self.call("POST", f"/api/material-requests/{extra['id']}/issue", {}, token=keeper)
        self.assertEqual((s, done["status"]), (200, "issued"))

        # a refusal needs a reason
        s, e2 = self.call("POST", url, {"item_id": item["id"], "qty": 50, "reason": "more please"}, token=sup)
        self.assertEqual(self.call("POST", f"/api/material-requests/{e2['id']}/decide", {"approve": False}, token=boss)[0], 422)
        s, rej = self.call("POST", f"/api/material-requests/{e2['id']}/decide", {"approve": False, "note": "No"}, token=boss)
        self.assertEqual(rej["status"], "rejected")

        full = self.call("GET", f"/api/jobs/{job['id']}", token=sup)[1]
        self.assertEqual(len(full["material_requests"]), 3)
        mat = next(m for m in full["materials"] if m["item_id"] == item["id"])
        self.assertEqual(mat["issued"], r["qty"] + 300)

    def test_request_waits_for_stock_item_then_links(self):
        boss = self.boss()
        papers = self.call("GET", "/api/papers", token=boss)[1]
        linked = {i["paper_id"] for i in self.call("GET", "/api/stock", token=boss)[1]}
        paper = [p for p in papers if p["pricing"] == "ream" and p["id"] not in linked][-1]
        job, _ = self._new_job(boss, paper["id"])
        r = next(x for x in self.call("GET", "/api/store/requests", token=boss)[1] if x["job_id"] == job["id"])
        if r["item_id"]:
            self.skipTest("paper already has a stock item")
        self.assertEqual(self.call("POST", f"/api/material-requests/{r['id']}/issue", {}, token=boss)[0], 409)
        self.call("POST", "/api/stock", {"name": "Late link", "unit": "sheets", "paper_id": paper["id"], "opening_qty": 99999}, token=boss)
        r = next(x for x in self.call("GET", "/api/store/requests", token=boss)[1] if x["id"] == r["id"])
        self.assertTrue(r["item_id"])

    def test_size_suggestions(self):
        boss = self.boss()
        m = self.call("GET", "/api/bootstrap", token=boss)[1]["masters"]
        paper = next(p for p in m["papers"] if p["pricing"] == "ream")
        spec = dict(size_w=21, size_h=29.7, copies=5000, components=[dict(name="Text", paper_id=paper["id"], pages=16, color_mode="multi",
                    machine_id=m["machines"][0]["id"], plate_id=m["plates"][0]["id"])])
        s, out = self.call("POST", "/api/suggest-sizes", spec, token=boss)
        self.assertEqual(s, 200, out)
        part = out["parts"][0]
        utils = [o["utilisation_pct"] for o in part["options"]]
        self.assertEqual(utils, sorted(utils, reverse=True))
        self.assertGreater(part["best"]["utilisation_pct"], 0)
        self.assertEqual(self.call("POST", "/api/suggest-sizes", spec, token=self.role("operator"))[0], 403)
        j = self.call("GET", "/api/jobs", token=boss)[1][0]
        s, jo = self.call("GET", f"/api/jobs/{j['id']}/size-suggestions", token=self.role("operator"))
        self.assertEqual(s, 200)
        self.assertNotIn("paper_cost", jo["parts"][0]["best"])  # no prices for floor staff


class SuggestMathTests(unittest.TestCase):
    def test_utilisation_and_ranking(self):
        paper = {"id": 1, "name": "P", "gsm": 80, "width_cm": 58.4, "height_cm": 91.4, "rate_per_ream": 1000, "pricing": "ream",
                 "weight_mode": "auto", "active": 1, "sizes": []}
        M = {"papers": {1: paper}, "machines": {1: {"id": 1, "name": "M", "rate_per_1000": 100, "per_color": 1, "setup_per_plate": 0,
             "min_charge": 0, "makeready_sheets": 0, "needs_plate": 0, "max_colors": 0}}, "plates": {}, "finishing": {}}
        spec = {"size_w": 21, "size_h": 29.7, "copies": 1000, "components": [{"paper_id": 1, "machine_id": 1, "pages": 16, "colors": 1}]}
        out = estimator.suggest_sizes(spec, M, {"bleed_cm": 0, "gripper_cm": 0}, [("A3", 29.7, 42), ("A4", 21, 29.7)])
        part = out[0]
        a4 = next(o for o in part["options"] if o["name"] == "A4")
        self.assertEqual(a4["ups"], 1)
        self.assertAlmostEqual(a4["utilisation_pct"], 100.0, places=1)
        self.assertAlmostEqual(part["best"]["utilisation_pct"], 100.0, places=1)
        self.assertTrue(all(o["ups"] >= 1 for o in part["options"]))


class RoleMigrationTests(unittest.TestCase):
    def test_old_users_table_accepts_storekeeper(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.db")
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL, "
                         "role TEXT NOT NULL CHECK(role IN ('manager','desk','superintendent','operator')), salt TEXT NOT NULL, "
                         "pw_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)")
            conn.execute("INSERT INTO users(username,name,role,salt,pw_hash,created_at) VALUES('a','A','manager','s','h','t')")
            conn.commit()
            db._allow_storekeeper(conn)
            conn.execute("INSERT INTO users(username,name,role,salt,pw_hash,created_at) VALUES('b','B','storekeeper','s','h','t')")
            self.assertEqual(conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"], 2)
            db._allow_storekeeper(conn)  # idempotent
            conn.close()


if __name__ == "__main__":
    unittest.main()
