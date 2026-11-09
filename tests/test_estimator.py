import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from press.estimator import EstimateError, compute_ups, estimate, r2  # noqa: E402


def masters(**over):
    m = {
        "papers": {1: dict(id=1, name="Test sheet", gsm=80, width_in=20, height_in=30, rate_per_ream=1000)},
        "machines": {
            1: dict(id=1, name="Offset", kind="offset", rate_per_1000=100, per_color=1, setup_per_plate=0,
                    min_charge=0, makeready_sheets=0, needs_plate=1, max_colors=4),
            2: dict(id=2, name="Digital", kind="digital", rate_per_1000=600, per_color=0, setup_per_plate=0,
                    min_charge=0, makeready_sheets=0, needs_plate=0, max_colors=0),
        },
        "plates": {1: dict(id=1, name="Plate", rate=50)},
        "finishing": {
            1: dict(id=1, name="Fold", group_name="Post", basis="per_1000", rate=150, min_charge=100),
            2: dict(id=2, name="Lam", group_name="Lam", basis="per_sqft", rate=2, min_charge=0),
            3: dict(id=3, name="Pins", group_name="Bind", basis="per_unit", rate=5, min_charge=0),
            4: dict(id=4, name="Die", group_name="Special", basis="job", rate=900, min_charge=0),
        },
    }
    m.update(over)
    return m


SETTINGS = dict(bleed_in=0, gripper_in=0, wastage_pct=0, default_margin_pct=0, gst_pct=0, round_to_rupee="0")


def base_spec(**over):
    spec = dict(
        size_w=10, size_h=15, copies=1000, margin_pct=20, gst_pct=12,
        components=[dict(name="Flyer", paper_id=1, machine_id=1, plate_id=1, pages=1, color_mode="single")],
    )
    spec.update(over)
    return spec


class FinishingConditionTests(unittest.TestCase):
    def fm(self):
        m = masters()
        m["finishing"][5] = dict(id=5, name="Sheet fold", group_name="Post", basis="per_1000_sheets", rate=200, min_charge=0)
        m["finishing"][6] = dict(id=6, name="Paste leaf", group_name="Post", basis="per_1000_leaves", rate=300, min_charge=0)
        return m

    def spec(self, fin):
        return base_spec(copies=1000, margin_pct=0, gst_pct=0, size_w=5, size_h=7.5, components=[
            dict(uid="t", name="Text", paper_id=1, machine_id=1, plate_id=1, pages=48, color_mode="bw", ups=8),
            dict(uid="i", name="Insert", part="insert", paper_id=1, machine_id=1, plate_id=1, pages=2, color_mode="bw", ups=8),
        ], finishing=fin)

    def test_fold_whole_job_vs_one_sheet_insert(self):
        # text: 48 pp / (2 x 8 up) = 3 sheets per copy; insert: 2 pp / 16 = 0.125 sheet per copy
        r = estimate(self.spec([dict(finishing_id=5, apply_to="all")]), self.fm(), SETTINGS)
        self.assertAlmostEqual(r["finishing"][0]["qty"], 3125)  # 1000 x (3 + 0.125)
        self.assertAlmostEqual(r["finishing"][0]["amount"], 625.0)
        r = estimate(self.spec([dict(finishing_id=5, apply_to="i")]), self.fm(), SETTINGS)
        self.assertAlmostEqual(r["finishing"][0]["qty"], 125)
        self.assertEqual(r["finishing"][0]["applies_to"], "Insert")
        self.assertAlmostEqual(r["finishing"][0]["amount"], 25.0)

    def test_times_and_override_and_leaves(self):
        r = estimate(self.spec([dict(finishing_id=5, apply_to="t", times=2)]), self.fm(), SETTINGS)
        self.assertAlmostEqual(r["finishing"][0]["amount"], 3000 / 1000 * 200 * 2)
        r = estimate(self.spec([dict(finishing_id=5, apply_to="t", qty=500)]), self.fm(), SETTINGS)
        self.assertAlmostEqual(r["finishing"][0]["amount"], 100.0)
        r = estimate(self.spec([dict(finishing_id=6, apply_to="t")]), self.fm(), SETTINGS)
        self.assertAlmostEqual(r["finishing"][0]["qty"], 24000)  # 1000 copies x 48 pages / 2
        with self.assertRaises(EstimateError):
            estimate(self.spec([dict(finishing_id=5, apply_to="gone")]), self.fm(), SETTINGS)


class UpsTests(unittest.TestCase):
    def test_exact_grid(self):
        self.assertEqual(compute_ups(10, 15, 20, 30), 4)

    def test_rotated_piece_is_tried(self):
        self.assertEqual(compute_ups(30, 10, 20, 30), 2)

    def test_bleed_and_gripper_reduce_fit(self):
        self.assertEqual(compute_ups(10, 15, 20, 30, bleed=0.5), 2)
        self.assertLess(compute_ups(10, 15, 20, 30, gripper=1), 4)

    def test_too_big(self):
        self.assertEqual(compute_ups(40, 40, 20, 30), 0)


class EstimateTests(unittest.TestCase):
    def test_hand_calculated_flyer(self):
        # 4 ups -> 250 sheets; paper 250 * 1000/500 = 500; 1 plate = 50;
        # print 250 impressions * 100/1000 = 25; cost 575; +20% = 690; +12% GST = 772.80
        r = estimate(base_spec(), masters(), SETTINGS)
        c = r["components"][0]
        self.assertEqual((c["ups"], c["sheets_gross"], c["plates"]), (4, 250, 1))
        t = r["totals"]
        self.assertEqual(t["paper"], 500.0)
        self.assertEqual(t["plates"], 50.0)
        self.assertEqual(t["printing"], 25.0)
        self.assertEqual(t["cost"], 575.0)
        self.assertEqual(t["margin_amount"], 115.0)
        self.assertEqual(t["pre_tax"], 690.0)
        self.assertEqual(t["gst"], 82.8)
        self.assertEqual(t["total"], 772.8)
        self.assertEqual(t["per_copy"], 0.69)

    def test_round_to_rupee(self):
        r = estimate(base_spec(), masters(), dict(SETTINGS, round_to_rupee="1"))
        self.assertEqual(r["totals"]["total"], 773.0)
        self.assertEqual(r["totals"]["round_off"], 0.2)

    def test_wastage_and_makeready(self):
        m = masters()
        m["machines"][1]["makeready_sheets"] = 10
        r = estimate(base_spec(wastage_pct=0, components=[
            dict(name="Flyer", paper_id=1, machine_id=1, plate_id=1, pages=1, color_mode="single", wastage_pct=10)
        ]), m, SETTINGS)
        # 250 * 1.10 = 275 (+10 make-ready for the single plate) = 285
        self.assertEqual(r["components"][0]["sheets_gross"], 285)

    def test_four_colour_both_sides_plates(self):
        spec = base_spec(components=[dict(name="Flyer", paper_id=1, machine_id=1, plate_id=1, pages=2, color_mode="multi")])
        c = estimate(spec, masters(), SETTINGS)["components"][0]
        self.assertEqual(c["plates"], 8)  # 1 form * 2 sides * 4 colours
        self.assertEqual(c["sheets_gross"], 250)
        self.assertEqual(c["impressions"], 250 * 2 * 4)

    def test_book_forms(self):
        # 64 pages at 8 ups -> 4 sheets per copy and 4 forms; 100 copies -> 400 sheets
        spec = base_spec(copies=100, components=[
            dict(name="Text", paper_id=1, machine_id=1, plate_id=1, pages=64, color_mode="bw", ups=8)])
        c = estimate(spec, masters(), SETTINGS)["components"][0]
        self.assertEqual((c["forms"], c["sheets_gross"], c["plates"]), (4, 400, 8))

    def test_digital_ignores_colour_count_and_plates(self):
        spec = base_spec(components=[dict(name="Flyer", paper_id=1, machine_id=2, pages=1, color_mode="multi")])
        c = estimate(spec, masters(), SETTINGS)["components"][0]
        self.assertEqual(c["plates"], 0)
        self.assertEqual(c["impressions"], 250)
        self.assertEqual(c["print_cost"], 150.0)

    def test_minimum_charge(self):
        m = masters()
        m["machines"][1]["min_charge"] = 400
        t = estimate(base_spec(), m, SETTINGS)["totals"]
        self.assertEqual(t["printing"], 400.0)

    def test_finishing_bases(self):
        spec = base_spec(finishing=[
            dict(finishing_id=1),             # 1000 copies / 1000 * 150 = 150
            dict(finishing_id=2),             # 1000 * (10*15/144) sq ft * 2
            dict(finishing_id=3, qty=40),     # 40 * 5 = 200
            dict(finishing_id=4),             # flat 900
        ])
        f = {x["finishing_id"]: x["amount"] for x in estimate(spec, masters(), SETTINGS)["finishing"]}
        self.assertEqual(f[1], 150.0)
        self.assertEqual(f[2], r2(1000 * (150 / 144) * 2))
        self.assertEqual(f[3], 200.0)
        self.assertEqual(f[4], 900.0)

    def test_finishing_minimum_charge(self):
        t = estimate(base_spec(copies=100, finishing=[dict(finishing_id=1)]), masters(), SETTINGS)
        self.assertEqual(t["finishing"][0]["amount"], 100.0)  # 15 -> minimum 100

    def test_per_unit_needs_quantity(self):
        with self.assertRaises(EstimateError):
            estimate(base_spec(finishing=[dict(finishing_id=3)]), masters(), SETTINGS)

    def test_discount_design_and_extras(self):
        spec = base_spec(design_charge=300, extras=[dict(description="Courier", amount=125)], discount=100, gst_pct=0)
        t = estimate(spec, masters(), SETTINGS)["totals"]
        self.assertEqual(t["cost"], 575 + 300 + 125)
        self.assertEqual(t["pre_tax"], r2(1000 * 1.2 - 100))

    def test_totals_add_up(self):
        spec = base_spec(design_charge=100, finishing=[dict(finishing_id=1), dict(finishing_id=4)],
                         extras=[dict(description="x", amount=10)], discount=50)
        t = estimate(spec, masters(), SETTINGS)["totals"]
        self.assertAlmostEqual(t["cost"], t["paper"] + t["plates"] + t["printing"] + t["finishing"] + t["design"] + t["extras"], 2)
        self.assertAlmostEqual(t["pre_tax"], t["cost"] + t["margin_amount"] - t["discount"], 2)
        self.assertAlmostEqual(t["total"], t["pre_tax"] + t["gst"] + t["round_off"], 2)

    def test_quantity_breaks_get_cheaper_per_copy(self):
        r = estimate(base_spec(), masters(), SETTINGS, quantities=[500, 1000, 5000])
        per = [b["per_copy"] for b in r["breaks"]]
        self.assertEqual([b["copies"] for b in r["breaks"]], [500, 1000, 5000])
        self.assertGreater(per[0], per[2])  # plate cost is spread over more copies
        self.assertEqual(r["breaks"][1]["total"], r["totals"]["total"])

    def test_errors_are_readable(self):
        bad = [
            (base_spec(copies=0), "Copies"),
            (base_spec(copies="abc"), "Copies"),
            (base_spec(size_w=0), "width"),
            (base_spec(components=[]), "at least one"),
            (base_spec(size_w=60, size_h=60), "does not fit"),
            (base_spec(components=[dict(paper_id=99, machine_id=1, plate_id=1, pages=1)]), "no longer exists"),
            (base_spec(components=[dict(paper_id=1, machine_id=1, pages=1)]), "plate"),
            (base_spec(components=[dict(paper_id=1, machine_id=1, plate_id=1, pages=0)]), "pages"),
            (base_spec(discount=99999), "Discount"),
            (base_spec(copies=float("nan")), "Copies"),
        ]
        for spec, word in bad:
            with self.subTest(word=word):
                with self.assertRaises(EstimateError) as cm:
                    estimate(spec, masters(), SETTINGS)
                self.assertIn(word.lower(), str(cm.exception).lower())

    def test_machine_pass_warning(self):
        m = masters()
        m["machines"][1]["max_colors"] = 2
        spec = base_spec(components=[dict(name="F", paper_id=1, machine_id=1, plate_id=1, pages=1, color_mode="multi")])
        self.assertTrue(any("passes" in w for w in estimate(spec, m, SETTINGS)["warnings"]))


if __name__ == "__main__":
    unittest.main()
