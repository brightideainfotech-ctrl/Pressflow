"""Itemised print-job estimator.

Pure functions only: no database or HTTP access, so the maths can be tested on
its own. All sizes are in inches, all money in rupees.

How a job is priced
-------------------
A job is made of *components* (text, cover, end paper ...). For each one:

    ups            finished pages that fit on one side of a parent sheet
                   (worked out from sizes, or typed in by the user)
    sheets/copy  = max(pages, 2) / (2 * ups)
    forms        = plate sets needed = ceil(sheets/copy), at least 1
    plates       = forms * sides * colours          (offset machines only)
    sheets       = copies * sheets/copy, plus wastage %, plus make-ready sheets
    paper cost   = sheets * (rate per ream / 500)
    print cost   = max(minimum, colour impressions * rate/1000 + set-up)

Finishing / binding lines are priced by their basis (per copy, per 1000,
per sq ft, per unit, or flat per job), then design charge and any free-form
extras are added.  Mark-up %, discount and GST come last.
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP

EPS = 1e-9

COLOR_MODES = {"multi": 4, "two": 2, "single": 1, "bw": 1}
PARTS = ("text", "cover", "end_paper", "insert")
BASES = ("per_copy", "per_1000", "per_sqft", "per_unit", "job", "per_1000_sheets", "per_1000_leaves")


class EstimateError(ValueError):
    """The specification cannot be priced; the message is safe to show to users."""


def r2(x) -> float:
    return float(Decimal(repr(float(x))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _f(value, label, lo=None, hi=None, default=None) -> float:
    if value is None or value == "":
        if default is not None:
            return float(default)
        raise EstimateError(f"{label} is required")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise EstimateError(f"{label} must be a number") from None
    if math.isnan(x) or math.isinf(x):
        raise EstimateError(f"{label} must be a number")
    if lo is not None and x < lo:
        raise EstimateError(f"{label} must be at least {lo:g}")
    if hi is not None and x > hi:
        raise EstimateError(f"{label} must be at most {hi:g}")
    return x


def _get(table: dict, key, label):
    try:
        k = int(key)
    except (TypeError, ValueError):
        raise EstimateError(f"{label}: please choose one") from None
    row = table.get(k)
    if row is None:
        raise EstimateError(f"{label}: the selected item no longer exists")
    return row


def compute_ups(piece_w, piece_h, sheet_w, sheet_h, bleed=0.0, gripper=0.0) -> int:
    """How many pieces of piece_w x piece_h fit on one side of the sheet.

    A bleed margin is added around each piece and a gripper strip is lost along
    one edge of the sheet. Both piece orientations and both gripper edges are
    tried and the best layout wins.
    """
    pw, ph = piece_w + 2 * bleed, piece_h + 2 * bleed
    best = 0
    for uw, uh in ((sheet_w - gripper, sheet_h), (sheet_w, sheet_h - gripper)):
        if uw <= 0 or uh <= 0:
            continue
        a = int((uw + EPS) // pw) * int((uh + EPS) // ph)
        b = int((uw + EPS) // ph) * int((uh + EPS) // pw)
        best = max(best, a, b)
    return best


def _find_size(sizes, w, h, tol=0.06):
    """The entry of a paper's weight table that matches w x h (either way round)."""
    for sz in sizes:
        a, b = sz["width_in"], sz["height_in"]
        if (abs(a - w) <= tol and abs(b - h) <= tol) or (abs(a - h) <= tol and abs(b - w) <= tol):
            return sz
    return None


def _component(c, copies, w, h, M, S):
    paper = _get(M["papers"], c.get("paper_id"), "Paper")
    machine = _get(M["machines"], c.get("machine_id"), "Machine")
    part = c.get("part") or "text"
    if part not in PARTS:
        raise EstimateError("Unknown part type")
    name = (str(c.get("name") or "").strip() or part.replace("_", " ").title())[:60]
    label = name

    pages = int(_f(c.get("pages"), f"{label}: pages", lo=1, hi=5000))
    mode = c.get("color_mode")
    if mode is not None and mode not in COLOR_MODES:
        raise EstimateError(f"{label}: unknown colour mode")
    colors = c.get("colors")
    if colors in (None, ""):
        colors = COLOR_MODES.get(mode, 1)
    colors = int(_f(colors, f"{label}: colours", lo=1, hi=8))

    warnings: list[str] = []
    bleed = _f(S.get("bleed_in"), "Bleed", lo=0, default=0.125)
    gripper = _f(S.get("gripper_in"), "Gripper", lo=0, default=0.5)

    ups_auto = compute_ups(w, h, paper["width_in"], paper["height_in"], bleed, gripper)
    ups_in = c.get("ups")
    has_sheet = paper["width_in"] > 0 and paper["height_in"] > 0
    if not has_sheet and ups_in in (None, ""):
        raise EstimateError(
            f"{label}: {paper['name']} has no sheet size, so enter 'Pages per sheet side' for this part")
    if ups_in not in (None, ""):
        ups = int(_f(ups_in, f"{label}: pages per sheet side", lo=1, hi=500))
    else:
        ups = ups_auto
    if ups < 1:
        raise EstimateError(
            f"{label}: a {w:g} x {h:g} in page does not fit on the {paper['name']} sheet "
            f"({paper['width_in']:g} x {paper['height_in']:g} in)"
        )

    waste_pct = c.get("wastage_pct")
    if waste_pct in (None, ""):
        waste_pct = S.get("wastage_pct", 5)
    waste_pct = _f(waste_pct, "Wastage %", lo=0, hi=100)

    pages_eff = max(pages, 2)
    sides = 1 if pages == 1 else 2
    sheets_per_copy = pages_eff / (2 * ups)
    forms = max(1, math.ceil(sheets_per_copy - EPS))
    sheets_net = copies * sheets_per_copy

    per_color = bool(machine["per_color"])
    colors_eff = colors if per_color else 1
    needs_plate = bool(machine["needs_plate"])
    plates = forms * sides * colors_eff if needs_plate else 0

    makeready = int(machine["makeready_sheets"] or 0) * (plates if needs_plate else forms * sides)
    sheets_gross = math.ceil(sheets_net * (1 + waste_pct / 100) - EPS) + makeready

    if machine["max_colors"] and colors_eff > machine["max_colors"]:
        passes = math.ceil(colors_eff / machine["max_colors"])
        warnings.append(f"{label}: {machine['name']} prints {machine['max_colors']} colour(s) per pass, so this needs {passes} passes")

    # Sheet weight in kg = area (m2) x gsm / 1000. Reel paper is bought and costed by weight.
    # Weight of paper used. Three ways, depending on the paper's set-up:
    #  - table: the press's own "kg per 100 sheets" figure for this size
    #  - sheet: sheet area x GSM (the paper has a sheet size)
    #  - page area: pages printed x page area x GSM (no sheet size)
    pieces = sheets_gross if has_sheet else sheets_gross * ups
    size_w, size_h = (paper["width_in"], paper["height_in"]) if has_sheet else (w, h)
    weight_src = "sheet" if has_sheet else "area"
    if (paper.get("weight_mode") or "auto") == "table":
        hit = _find_size(paper.get("sizes") or [], size_w, size_h)
        if hit is None:
            raise EstimateError(
                f"{label}: no weight is entered for {size_w:g} x {size_h:g} in on {paper['name']}. "
                "Add it under Rate master > Paper > Weights")
        paper_kg = pieces * hit["kg_per_100"] / 100.0
        weight_src = "table"
    else:
        paper_kg = pieces * size_w * size_h * 0.00064516 * float(paper["gsm"] or 0) / 1000.0
    by_weight = (paper.get("pricing") or "ream") == "kg"
    if by_weight:
        if not paper["gsm"] and weight_src != "table":
            raise EstimateError(f"{label}: {paper['name']} is priced per kg, so it needs a GSM value")
        paper_cost = paper_kg * float(paper.get("rate_per_kg") or 0)
    else:
        paper_cost = sheets_gross * paper["rate_per_ream"] / 500.0

    plate_cost = 0.0
    plate_name = None
    if needs_plate:
        plate = _get(M["plates"], c.get("plate_id"), f"{label}: plate type")
        plate_name = plate["name"]
        plate_cost = plates * plate["rate"]

    impressions = sheets_gross * sides * colors_eff
    setup_units = plates if needs_plate else forms * sides
    run_cost = impressions * machine["rate_per_1000"] / 1000.0 + setup_units * machine["setup_per_plate"]
    print_cost = max(float(machine["min_charge"] or 0), run_cost)

    return {
        "uid": str(c.get("uid") or "")[:40],
        "name": name,
        "part": part,
        "color_mode": mode,
        "paper_id": paper["id"],
        "paper": paper["name"],
        "machine_id": machine["id"],
        "machine": machine["name"],
        "plate_id": int(c["plate_id"]) if needs_plate else None,
        "plate": plate_name,
        "pages": pages,
        "colors": colors,
        "ups": ups,
        "ups_auto": ups_auto,
        "ups_overridden": ups_in not in (None, ""),
        "wastage_pct": waste_pct,
        "sides": sides,
        "forms": forms,
        "plates": plates,
        "sheets_net": r2(sheets_net),
        "sheets_gross": sheets_gross,
        "impressions": impressions,
        "paper_basis": "kg" if by_weight else "ream",
        "paper_by_area": by_weight and weight_src == "area",
        "paper_weight_src": weight_src,
        "paper_kg": round(paper_kg, 5),
        "paper_cost": r2(paper_cost),
        "plate_cost": r2(plate_cost),
        "print_cost": r2(print_cost),
        "total": r2(r2(paper_cost) + r2(plate_cost) + r2(print_cost)),
        "warnings": warnings,
    }


def _finishing_line(line, copies, w, h, M, components=()):
    f = _get(M["finishing"], line.get("finishing_id"), "Finishing item")
    qty_in = line.get("qty")
    has_qty = qty_in not in (None, "")
    qty = _f(qty_in, f"{f['name']}: quantity", lo=0) if has_qty else None
    times = _f(line.get("times"), f"{f['name']}: times", lo=0, hi=100, default=1) if line.get("times") not in (None, "") else 1.0
    basis = f["basis"]
    if basis not in BASES:
        raise EstimateError(f"{f['name']}: unknown pricing basis")

    # Which printed parts the work applies to (only matters for the sheet / leaf bases).
    apply_to = str(line.get("apply_to") or "all")
    if apply_to == "all":
        chosen = list(components)
    else:
        chosen = [c for c in components if c.get("uid") == apply_to]
        if not chosen:
            raise EstimateError(f"{f['name']}: the part it was set for is no longer in this quotation")
    applies = ", ".join(c["name"] for c in chosen) if apply_to != "all" else ""

    base_qty = qty if has_qty else float(copies)
    if basis == "per_copy":
        used, raw = base_qty, base_qty * f["rate"]
    elif basis == "per_1000":
        used, raw = base_qty, base_qty / 1000.0 * f["rate"]
    elif basis == "per_sqft":
        used, raw = base_qty, base_qty * (w * h / 144.0) * f["rate"]
    elif basis == "per_1000_sheets":
        # printed sheets that go through the work, e.g. every sheet of the text folded once
        auto = sum(c["sheets_net"] for c in chosen)
        used = qty if has_qty else auto
        raw = used / 1000.0 * f["rate"]
    elif basis == "per_1000_leaves":
        # leaves = pages / 2 for every copy, e.g. each leaf pasted or tipped in
        auto = sum(copies * max(c["pages"], 2) / 2.0 for c in chosen)
        used = qty if has_qty else auto
        raw = used / 1000.0 * f["rate"]
    elif basis == "per_unit":
        if not has_qty:
            raise EstimateError(f"{f['name']}: enter a quantity")
        used, raw = qty, qty * f["rate"]
    else:  # job
        used, raw = 1, f["rate"]
    if basis != "job":
        raw *= times
    used = round(used, 2)
    amount = max(float(f["min_charge"] or 0), raw) if raw > 0 else 0.0
    return {
        "finishing_id": f["id"],
        "name": f["name"],
        "group": f["group_name"],
        "basis": basis,
        "rate": f["rate"],
        "qty": used,
        "times": times,
        "applies_to": applies,
        "note": str(line.get("note") or "")[:120],
        "amount": r2(amount),
    }


def _price(spec, copies, M, S):
    w = _f(spec.get("size_w"), "Finished width", lo=0.1, hi=200)
    h = _f(spec.get("size_h"), "Finished height", lo=0.1, hi=200)

    comps_in = spec.get("components") or []
    if not comps_in:
        raise EstimateError("Add at least one printed part (for example Text or Cover)")
    if len(comps_in) > 12:
        raise EstimateError("Too many parts (maximum 12)")
    components = [_component(c, copies, w, h, M, S) for c in comps_in]

    fin_in = spec.get("finishing") or []
    if len(fin_in) > 40:
        raise EstimateError("Too many finishing lines (maximum 40)")
    finishing = [_finishing_line(f, copies, w, h, M, components) for f in fin_in]

    extras = []
    for e in (spec.get("extras") or [])[:20]:
        desc = str(e.get("description") or "").strip()[:120]
        amt = _f(e.get("amount"), "Extra charge amount", lo=0, default=0)
        if desc or amt:
            extras.append({"description": desc or "Other charge", "amount": r2(amt)})

    design = r2(_f(spec.get("design_charge"), "Design charge", lo=0, default=0))

    paper_t = r2(sum(c["paper_cost"] for c in components))
    plates_t = r2(sum(c["plate_cost"] for c in components))
    print_t = r2(sum(c["print_cost"] for c in components))
    fin_t = r2(sum(f["amount"] for f in finishing))
    extras_t = r2(sum(e["amount"] for e in extras))
    cost = r2(paper_t + plates_t + print_t + fin_t + design + extras_t)

    margin_pct = _f(spec.get("margin_pct"), "Mark-up %", lo=0, hi=1000, default=S.get("default_margin_pct", 25))
    gst_pct = _f(spec.get("gst_pct"), "GST %", lo=0, hi=50, default=S.get("gst_pct", 0))
    margin_amt = r2(cost * margin_pct / 100.0)
    discount = r2(_f(spec.get("discount"), "Discount", lo=0, default=0))
    gross = r2(cost + margin_amt)
    if discount > gross:
        raise EstimateError("Discount is larger than the price")
    pre_tax = r2(gross - discount)
    gst = r2(pre_tax * gst_pct / 100.0)
    total_exact = r2(pre_tax + gst)
    if str(S.get("round_to_rupee", "1")) in ("1", "true", "True"):
        total = float(round(total_exact))
    else:
        total = total_exact
    round_off = r2(total - total_exact)

    warnings = [w_ for c in components for w_ in c["warnings"]]
    if margin_amt == 0 and cost > 0:
        warnings.append("Mark-up is 0%: this quotation earns nothing above cost")
    pre_tax_per_copy = r2(pre_tax / copies)

    return {
        "copies": copies,
        "size_w": w,
        "size_h": h,
        "components": components,
        "finishing": finishing,
        "extras": extras,
        "totals": {
            "paper": paper_t,
            "plates": plates_t,
            "printing": print_t,
            "finishing": fin_t,
            "design": design,
            "extras": extras_t,
            "cost": cost,
            "margin_pct": margin_pct,
            "margin_amount": margin_amt,
            "discount": discount,
            "pre_tax": pre_tax,
            "gst_pct": gst_pct,
            "gst": gst,
            "round_off": round_off,
            "total": total,
            "per_copy": pre_tax_per_copy,
            "margin_on_price_pct": r2(margin_amt / gross * 100) if gross else 0.0,
        },
        "warnings": warnings,
    }


def estimate(spec: dict, masters: dict, settings: dict, quantities=None) -> dict:
    """Price `spec`. `masters` maps papers/machines/plates/finishing to {id: row-dict}.

    If `quantities` is given, also returns a short table of totals at each
    alternative copy count (same specification, everything recalculated).
    """
    if not isinstance(spec, dict):
        raise EstimateError("Invalid specification")
    copies = int(_f(spec.get("copies"), "Copies", lo=1, hi=10_000_000))
    result = _price(spec, copies, masters, settings)

    breaks = []
    for q in (quantities or [])[:8]:
        q = int(_f(q, "Quantity", lo=1, hi=10_000_000))
        t = _price(spec, q, masters, settings)["totals"]
        breaks.append({"copies": q, "cost": t["cost"], "pre_tax": t["pre_tax"], "total": t["total"], "per_copy": t["per_copy"]})
    result["breaks"] = breaks
    return result
