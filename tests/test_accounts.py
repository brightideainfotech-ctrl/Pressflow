import json, os, sys, tempfile, threading, unittest, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from press import auth, db, demo, server  # noqa: E402


class AccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "t.db")
        db.init_db(path)
        conn = db.connect(path)
        auth.create_user(conn, "boss", "Boss", "manager", "boss-password-1")
        conn.execute("UPDATE settings SET value='33' WHERE key='company_state_code'")  # Tamil Nadu
        conn.commit(); conn.close()
        cls.srv = server.make_server("127.0.0.1", 0, path)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        s, d = cls.call_(cls, "POST", "/api/login", {"username": "boss", "password": "boss-password-1"})
        cls.tok = d["token"]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close(); cls.tmp.cleanup()

    def call_(self, method, path, body=None, token=None):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def call(self, method, path, body=None):
        return self.call_(method, path, body, self.tok)

    def ok(self, method, path, body=None, code=None):
        if method == "POST" and body is None:
            body = {}
        s, d = self.call(method, path, body)
        self.assertEqual(s, code or (201 if method == "POST" else 200), d)
        return d

    def mk(self, **kw):
        n = getattr(AccountTests, "_n", 0) + 1; AccountTests._n = n
        return self.ok("POST", "/api/parties", {"name": f"Party {n}", **kw})

    def item(self, **kw):
        n = getattr(AccountTests, "_i", 0) + 1; AccountTests._i = n
        return self.ok("POST", "/api/stock", {"name": f"Item {n}", "unit": "kg", "category": "goods", **kw})

    def test_gst_split_same_state_and_other_state(self):
        a = self.mk(party_type="customer", state_code="33")
        b = self.mk(party_type="customer", state_code="27")
        line = {"description": "Books", "qty": 10, "rate": 100, "gst_rate": 12, "unit": "pcs"}
        i1 = self.ok("POST", "/api/sales", {"party_id": a["id"], "lines": [line]})
        self.assertEqual((i1["taxable"], i1["cgst"], i1["sgst"], i1["igst"], i1["total"]), (1000, 60, 60, 0, 1120))
        i2 = self.ok("POST", "/api/sales", {"party_id": b["id"], "lines": [line]})
        self.assertEqual((i2["cgst"], i2["sgst"], i2["igst"]), (0, 0, 120))
        self.assertTrue(i1["number"].startswith("INV-"))

    def test_round_off_discount_and_validation(self):
        p = self.mk(state_code="33")
        i = self.ok("POST", "/api/sales", {"party_id": p["id"], "lines": [{"description": "x", "qty": 3, "rate": 33.33, "disc_pct": 10, "gst_rate": 5}]})
        self.assertEqual(i["taxable"], 89.99)  # 3 x 33.33 = 99.99, less 10%
        self.assertEqual(i["total"], float(round(i["taxable"] + i["cgst"] + i["sgst"] + i["igst"])))
        self.assertAlmostEqual(i["round_off"], i["total"] - (i["taxable"] + i["cgst"] + i["sgst"]), places=2)
        s, d = self.call("POST", "/api/sales", {"party_id": p["id"], "lines": []})
        self.assertEqual(s, 422)
        s, d = self.call("POST", "/api/sales", {"party_id": p["id"], "lines": [{"description": "x", "qty": 0, "rate": 1}]})
        self.assertEqual(s, 422)
        s, d = self.call("POST", "/api/sales", {"party_id": p["id"], "lines": [{"description": "x", "qty": 1, "rate": 1, "gst_rate": 99}]})
        self.assertEqual(s, 422)

    def test_stock_flows_with_purchase_and_sale(self):
        sup = self.mk(party_type="supplier", state_code="33")
        cus = self.mk(party_type="customer", state_code="33")
        it = self.item(reorder_level=5)
        self.ok("POST", "/api/purchases", {"party_id": sup["id"], "party_ref": "B-77",
                "lines": [{"item_id": it["id"], "description": it["name"], "qty": 100, "rate": 50, "gst_rate": 12, "unit": "kg"}]})
        self.assertEqual(self.ok("GET", "/api/stock?all=1")[0]["on_hand"] if False else [x for x in self.ok("GET", "/api/stock") if x["id"] == it["id"]][0]["on_hand"], 100)
        sale = self.ok("POST", "/api/sales", {"party_id": cus["id"], "lines": [{"item_id": it["id"], "description": "sold", "qty": 40, "rate": 80, "gst_rate": 12}]})
        self.assertEqual([x for x in self.ok("GET", "/api/stock") if x["id"] == it["id"]][0]["on_hand"], 60)
        # cannot oversell
        s, d = self.call("POST", "/api/sales", {"party_id": cus["id"], "lines": [{"item_id": it["id"], "description": "x", "qty": 61, "rate": 1}]})
        self.assertEqual(s, 409, d)
        # latest purchase price recorded
        self.assertEqual([x for x in self.ok("GET", "/api/stock") if x["id"] == it["id"]][0]["purchase_price"], 50)
        # cancelling the sale returns the stock
        self.ok("POST", f"/api/sales/{sale['id']}/cancel", code=200)
        self.assertEqual([x for x in self.ok("GET", "/api/stock") if x["id"] == it["id"]][0]["on_hand"], 100)
        s, d = self.call("POST", f"/api/sales/{sale['id']}/cancel", {})
        self.assertEqual(s, 409)

    def test_cancel_purchase_blocked_when_stock_used(self):
        sup = self.mk(party_type="supplier"); cus = self.mk(party_type="customer")
        it = self.item()
        pb = self.ok("POST", "/api/purchases", {"party_id": sup["id"], "lines": [{"item_id": it["id"], "description": "p", "qty": 10, "rate": 5}]})
        self.ok("POST", "/api/sales", {"party_id": cus["id"], "lines": [{"item_id": it["id"], "description": "s", "qty": 8, "rate": 9}]})
        s, d = self.call("POST", f"/api/purchases/{pb['id']}/cancel", {})
        self.assertEqual(s, 409, d)

    def test_party_type_rules(self):
        sup = self.mk(party_type="supplier"); cus = self.mk(party_type="customer"); both = self.mk(party_type="both")
        ln = [{"description": "x", "qty": 1, "rate": 10}]
        self.assertEqual(self.call("POST", "/api/sales", {"party_id": sup["id"], "lines": ln})[0], 422)
        self.assertEqual(self.call("POST", "/api/purchases", {"party_id": cus["id"], "lines": ln})[0], 422)
        self.ok("POST", "/api/sales", {"party_id": both["id"], "lines": ln})
        names = [c["name"] for c in self.ok("GET", "/api/customers")]
        self.assertNotIn(sup["name"], names)  # suppliers stay out of the quotation customer list
        self.assertIn(cus["name"], names)

    def test_balances_payments_and_statement(self):
        p = self.mk(party_type="customer", opening_balance=500)
        i = self.ok("POST", "/api/sales", {"party_id": p["id"], "inv_date": "2026-05-10", "lines": [{"description": "x", "qty": 1, "rate": 1000}]})
        self.assertEqual(self.ok("GET", "/api/parties")[-1]["balance"] if False else [x for x in self.ok("GET", "/api/parties") if x["id"] == p["id"]][0]["balance"], 1500)
        self.ok("POST", "/api/payments", {"kind": "in", "party_id": p["id"], "invoice_id": i["id"], "amount": 400, "pay_date": "2026-05-12", "mode": "upi"})
        inv = self.ok("GET", f"/api/sales/{i['id']}")
        self.assertEqual((inv["paid"], inv["due"], inv["pay_status"]), (400, 600, "part"))
        s, d = self.call("POST", "/api/payments", {"kind": "in", "party_id": p["id"], "invoice_id": i["id"], "amount": 601})
        self.assertEqual(s, 422)
        s, d = self.call("POST", "/api/payments", {"kind": "out", "party_id": p["id"], "invoice_id": i["id"], "amount": 10})
        self.assertEqual(s, 422)  # wrong direction
        s, d = self.call("POST", f"/api/sales/{i['id']}/cancel", {})
        self.assertEqual(s, 409)  # has payments
        st = self.ok("GET", f"/api/parties/{p['id']}/statement?from=2026-04-01&to=2026-12-31")
        self.assertEqual(st["opening"], 500)
        self.assertEqual(st["closing"], 1100)
        self.assertEqual([r["balance"] for r in st["rows"]], [1500, 1100])
        out = self.ok("GET", "/api/reports/outstanding?kind=receivable")
        row = [r for r in out["rows"] if r["id"] == p["id"]][0]
        self.assertEqual(row["balance"], 1100)
        self.assertAlmostEqual(row["b0"] + row["b1"] + row["b2"] + row["b3"] + row["other"], 1100, places=2)

    def test_paid_now_and_payable(self):
        sup = self.mk(party_type="supplier")
        b = self.ok("POST", "/api/purchases", {"party_id": sup["id"], "lines": [{"description": "Electricity", "qty": 1, "rate": 2000}],
                                                "paid_now": {"amount": 500, "mode": "cash"}})
        self.assertEqual(b["paid"], 500)
        pay = self.ok("GET", "/api/reports/outstanding?kind=payable")
        self.assertEqual([r for r in pay["rows"] if r["id"] == sup["id"]][0]["balance"], 1500)

    def test_reports(self):
        sup = self.mk(party_type="supplier", state_code="33"); cus = self.mk(party_type="customer", state_code="27")
        it = self.item()
        self.ok("POST", "/api/purchases", {"party_id": sup["id"], "inv_date": "2026-06-01",
                "lines": [{"item_id": it["id"], "description": "paper", "qty": 10, "rate": 100, "gst_rate": 12}]})
        self.ok("POST", "/api/purchases", {"party_id": sup["id"], "inv_date": "2026-06-02",
                "lines": [{"description": "rent", "qty": 1, "rate": 300, "gst_rate": 0}]})
        self.ok("POST", "/api/sales", {"party_id": cus["id"], "inv_date": "2026-06-03",
                "lines": [{"item_id": it["id"], "description": "paper", "qty": 4, "rate": 200, "gst_rate": 12, "hsn": "4802"}]})
        q = "?from=2026-06-01&to=2026-06-30"
        reg = self.ok("GET", "/api/reports/register?kind=sale&party_id=%d&from=2026-06-01&to=2026-06-30" % cus["id"])
        self.assertEqual(reg["totals"]["taxable"], 800); self.assertEqual(reg["totals"]["igst"], 96)
        gst = self.ok("GET", "/api/reports/gst" + q)
        self.assertGreaterEqual(gst["output"]["totals"]["igst"], 96)
        self.assertTrue(any(h["hsn"] == "4802" for h in gst["hsn"]))
        pnl = self.ok("GET", "/api/reports/pnl" + q)
        self.assertEqual(pnl["expenses"], 300)
        self.assertAlmostEqual(pnl["cost_of_goods"], pnl["opening_stock"] + pnl["stock_purchases"] + pnl["other_additions"] - pnl["closing_stock"], places=2)
        self.assertAlmostEqual(pnl["net_profit"], pnl["gross_profit"] - 300, places=2)
        day = self.ok("GET", "/api/reports/daybook" + q)
        self.assertGreaterEqual(len(day["rows"]), 3)
        stock = self.ok("GET", "/api/reports/stock")
        self.assertTrue(any(r["id"] == it["id"] and r["on_hand"] == 6 for r in stock["rows"]))
        self.assertEqual(self.call("GET", "/api/reports/pnl?from=2026-07-01&to=2026-06-01")[0], 422)

    def test_permissions_and_validation(self):
        self.assertEqual(self.call_("GET", "/api/parties")[0], 401)
        self.assertEqual(self.call("POST", "/api/parties", {"name": "X", "gstin": "123"})[0], 422)
        self.assertEqual(self.call("POST", "/api/parties", {"name": "X", "state_code": "99"})[0], 422)
        p = self.mk(gstin="33abcde1234f1z5")
        self.assertEqual(p["gstin"], "33ABCDE1234F1Z5")

    def test_logo_setting(self):
        png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        self.assertEqual(self.ok("PUT", "/api/settings", {"company_logo": png}, code=200)["company_logo"], png)
        self.assertEqual(self.call("PUT", "/api/settings", {"company_logo": "data:text/html;base64,AAAA"})[0], 422)
        self.assertEqual(self.call("PUT", "/api/settings", {"company_logo": "javascript:alert(1)"})[0], 422)
        self.assertEqual(self.call("PUT", "/api/settings", {"company_logo": "data:image/png;base64," + "A" * 400_100})[0], 422)
        self.assertEqual(self.ok("PUT", "/api/settings", {"company_logo": ""}, code=200)["company_logo"], "")

    def test_job_invoice_draft(self):
        s, d = self.call("GET", "/api/jobs/99999/invoice-draft")
        self.assertEqual(s, 404)


if __name__ == "__main__":
    unittest.main()
