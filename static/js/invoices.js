import { state, get, post, del } from "./api.js";
import { h, add, clear, field, select, input, formModal, toast, fail, money, num, fmtDate, todayStr, debounce, emptyState, confirmBox, badge, logoImg, printHeader } from "./ui.js";
import { loadStates, stateName, companyStateCode, calcInvoice, inWords, PAY_MODES, PAY_BADGE, hashQuery } from "./acc.js";

const CFG = {
  sale: { path: "sales", title: "Sales invoices", one: "Sales invoice", newText: "+ New sales invoice", partyType: "customer", partyWord: "Customer", payKind: "in", payWord: "Receipt", payBtn: "Record receipt" },
  purchase: { path: "purchases", title: "Purchase bills", one: "Purchase bill", newText: "+ New purchase bill", partyType: "supplier", partyWord: "Supplier", payKind: "out", payWord: "Payment", payBtn: "Record payment" },
};
const plain = (n) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(n) || 0);
const statusBadge = (s) => { const [c, t] = PAY_BADGE[s] || ["approved", s]; return badge(c, t); };

// ------------------------------------------------------------------ list

export async function renderInvoiceList(view, kind) {
  const cfg = CFG[kind];
  let rows = [], text = "", status = "", from = "", to = "";
  const body = h("div");
  async function load() {
    const qs = new URLSearchParams({ ...(from && { from }), ...(to && { to }) });
    try { rows = await get(`/api/${cfg.path}?${qs}`); } catch (e) { return fail(e); }
    draw();
  }
  function draw() {
    clear(body);
    const shown = rows.filter((r) => (!status || r.pay_status === status) && (!text || (r.number + r.party_name + r.party_ref).toLowerCase().includes(text.toLowerCase())));
    const live = shown.filter((r) => r.status === "active");
    const sum = (k) => live.reduce((a, r) => a + r[k], 0);
    add(body, h("div", { class: "stats" },
      h("div", { class: "stat" }, h("div", { class: "lbl" }, "Total"), h("div", { class: "n" }, money(sum("total"))), h("div", { class: "small muted" }, `${live.length} invoice${live.length === 1 ? "" : "s"}`)),
      h("div", { class: "stat" }, h("div", { class: "lbl" }, kind === "sale" ? "Received" : "Paid"), h("div", { class: "n" }, money(sum("paid")))),
      h("div", { class: "stat" + (sum("due") > 0 ? " alert" : "") }, h("div", { class: "lbl" }, "Still due"), h("div", { class: "n" }, money(sum("due"))))));
    if (!shown.length) return add(body, emptyState(rows.length ? "Nothing matches." : `No ${cfg.title.toLowerCase()} yet.`));
    add(body, h("div", { class: "card tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Number", "Date", cfg.partyWord, ...(kind === "purchase" ? ["Bill no."] : []), "Taxable", "GST", "Total", "Due", "Status"].map((t, i) => h("th", { class: i >= (kind === "purchase" ? 4 : 3) && i < (kind === "purchase" ? 8 : 7) ? "num" : "" }, t)))),
      h("tbody", null, shown.map((r) => h("tr", { class: "clickable", style: r.status === "active" ? null : { opacity: ".55" }, onclick: () => (location.hash = `#/${cfg.path}/${r.id}`) },
        h("td", { class: "nowrap" }, h("b", { style: { color: "var(--accent)" } }, r.number)), h("td", { class: "nowrap" }, fmtDate(r.inv_date)), h("td", null, r.party_name),
        kind === "purchase" ? h("td", null, r.party_ref) : null,
        h("td", { class: "num" }, money(r.taxable)), h("td", { class: "num" }, money(r.cgst + r.sgst + r.igst)), h("td", { class: "num" }, money(r.total)),
        h("td", { class: "num" }, r.due ? money(r.due) : "—"), h("td", null, statusBadge(r.pay_status))))))));
  }
  const search = h("input", { type: "search", placeholder: "Search number or name", "aria-label": "Search", oninput: debounce(() => { text = search.value.trim(); draw(); }, 150) });
  const st = select([["", "All"], ["unpaid", "Unpaid"], ["part", "Part paid"], ["paid", "Paid"], ["cancelled", "Cancelled"]], "", { "aria-label": "Status", onchange: () => { status = st.value; draw(); } });
  const f = input("date", "", { "aria-label": "From date", onchange: () => { from = f.value; load(); } });
  const t = input("date", "", { "aria-label": "To date", onchange: () => { to = t.value; load(); } });
  add(view,
    h("div", { class: "pagehead" }, h("div", null, h("div", { class: "eyebrow" }, "Accounts"), h("h1", null, cfg.title)),
      h("div", { class: "actions" }, h("a", { class: "btn primary", href: `#/${cfg.path}/new` }, cfg.newText))),
    h("div", { class: "toolbar" }, search, st, "From", f, "to", t), body);
  await load();
}

// ------------------------------------------------------------------ editor

export async function renderInvoiceEditor(view, kind) {
  const cfg = CFG[kind];
  const q = hashQuery();
  await loadStates();
  const [parties, items] = await Promise.all([get("/api/parties?type=" + cfg.partyType), get("/api/stock")]);
  const states = await loadStates();
  let draft = null;
  if (kind === "sale" && q.job) {
    try { draft = await get(`/api/jobs/${Number(q.job)}/invoice-draft`); } catch (e) { fail(e); }
  }
  const itemById = (id) => items.find((i) => String(i.id) === String(id));

  const party = select([["", "Choose..."], ...parties.map((p) => [String(p.id), p.name])], draft ? String(draft.party_id) : "");
  const date = input("date", todayStr()), due = input("date", "");
  const ref = input("text", "", { placeholder: kind === "purchase" ? "Supplier's bill number" : "Optional" });
  const pos = select([["", "Same as party / my state"], ...states.map((s) => [s.code, `${s.code} ${s.name}`])], "");
  const notes = h("textarea", { value: draft ? draft.notes : "" });
  const payAmt = input("number", draft && draft.advance ? draft.advance : "", { step: "0.01", min: 0, placeholder: "0" });
  const payMode = select(PAY_MODES, "cash");
  const err = h("div", { class: "errbox hidden", role: "alert" });
  const linesBody = h("tbody"), totalsBox = h("div", { class: "card" });
  const model = [];

  const placeCode = () => pos.value || (parties.find((p) => String(p.id) === party.value) || {}).state_code || "";
  const intra = () => { const mine = companyStateCode(), p = placeCode(); return !p || !mine || p === mine; };

  function addLine(init = {}) {
    const ln = { item_id: "", description: "", hsn: "", qty: 1, unit: "", rate: 0, disc_pct: 0, gst_rate: Number(state.settings.gst_pct) || 0, ...init };
    model.push(ln);
    const amountCell = h("td", { class: "num nowrap" }, "0.00");
    ln.amountCell = amountCell;
    const bind = (key, el, numeric) => { el.addEventListener("input", () => { ln[key] = numeric ? (el.value === "" ? 0 : Number(el.value)) : el.value; recalc(); }); return el; };
    const num_ = (key, w, step = "any") => bind(key, input("number", ln[key], { step, min: 0, style: { width: w } }), true);
    const itemSel = select([["", "— none —"], ...items.map((i) => [String(i.id), i.name + (i.track_stock ? ` (${num(i.on_hand)} ${i.unit})` : "")])], ln.item_id, { style: { minWidth: "10rem" } });
    const desc = bind("description", input("text", ln.description, { placeholder: "Description", style: { minWidth: "15rem" } }), false);
    const hsn = bind("hsn", input("text", ln.hsn, { style: { width: "5.5rem" } }), false);
    const unit = bind("unit", input("text", ln.unit, { style: { width: "4.5rem" } }), false);
    const qty = num_("qty", "5.5rem"), rate = num_("rate", "6.5rem", "0.01"), disc = num_("disc_pct", "4.5rem"), gst = num_("gst_rate", "4.5rem");
    itemSel.addEventListener("change", () => {
      const it = itemById(itemSel.value); ln.item_id = itemSel.value;
      if (it) {
        ln.description = desc.value = it.name; ln.hsn = hsn.value = it.hsn || ""; ln.unit = unit.value = it.unit;
        ln.rate = rate.value = (kind === "sale" ? it.sale_price : it.purchase_price) || 0; ln.rate = Number(ln.rate);
        ln.gst_rate = gst.value = it.gst_rate; ln.gst_rate = Number(ln.gst_rate);
      }
      recalc();
    });
    const tr = h("tr", null, h("td", null, itemSel), h("td", null, desc), h("td", null, hsn), h("td", null, qty), h("td", null, unit), h("td", null, rate), h("td", null, disc), h("td", null, gst), amountCell,
      h("td", null, h("button", { class: "btn small", type: "button", "aria-label": "Remove line", onclick: () => { const i = model.indexOf(ln); model.splice(i, 1); tr.remove(); recalc(); } }, "×")));
    linesBody.append(tr);
    recalc();
  }

  function recalc() {
    const r = calcInvoice(model, intra());
    model.forEach((ln, i) => { ln.amountCell.textContent = money(r.lines[i].amount); });
    const t = r.totals;
    clear(totalsBox);
    const row = (a, b, strong) => h("tr", null, h("td", null, strong ? h("strong", null, a) : a), h("td", { class: "num" }, strong ? h("strong", null, b) : b));
    add(totalsBox, h("table", { style: { maxWidth: "340px", marginLeft: "auto" } }, h("tbody", null,
      row("Taxable value", money(t.taxable)),
      intra() ? [row("CGST", money(t.cgst)), row("SGST", money(t.sgst))] : row("IGST", money(t.igst)),
      Math.abs(t.round_off) > 0.004 ? row("Round off", money(t.round_off)) : null,
      row("Total", money(t.total), true))),
      h("div", { class: "small muted", style: { textAlign: "right" } }, intra() ? "Same state: CGST + SGST" : "Other state: IGST"));
  }

  party.addEventListener("change", () => { const p = parties.find((x) => String(x.id) === party.value); if (p && p.state_code) pos.value = ""; recalc(); });
  pos.addEventListener("change", recalc);

  const save = h("button", { class: "btn primary", type: "button" }, "Save " + cfg.one.toLowerCase());
  save.addEventListener("click", async () => {
    err.classList.add("hidden");
    const body = {
      party_id: Number(party.value) || 0, inv_date: date.value, due_date: due.value, party_ref: ref.value, notes: notes.value, place_of_supply: pos.value,
      job_id: draft ? draft.job_id : undefined,
      lines: model.map((l) => ({ item_id: l.item_id ? Number(l.item_id) : null, description: l.description, hsn: l.hsn, qty: l.qty, unit: l.unit, rate: l.rate, disc_pct: l.disc_pct, gst_rate: l.gst_rate })),
    };
    if (Number(payAmt.value) > 0) body.paid_now = { amount: Number(payAmt.value), mode: payMode.value };
    save.disabled = true;
    try { const r = await post(`/api/${cfg.path}`, body); toast("Saved " + r.number); location.hash = `#/${cfg.path}/${r.id}`; }
    catch (e) { err.textContent = e.message; err.classList.remove("hidden"); save.disabled = false; window.scrollTo(0, 0); }
  });

  add(view,
    h("div", { class: "pagehead" }, h("div", null, h("div", { class: "eyebrow" }, "Accounts"), h("h1", null, "New " + cfg.one.toLowerCase())),
      h("div", { class: "actions" }, h("a", { class: "btn", href: `#/${cfg.path}` }, "Cancel"))),
    err,
    draft && draft.existing_invoice ? h("div", { class: "banner" }, `This job already has invoice ${draft.existing_invoice}. Save only if you really need another one.`) : null,
    h("div", { class: "card" }, h("div", { class: "row" },
      field(cfg.partyWord, party, parties.length ? null : `No ${cfg.partyWord.toLowerCase()}s yet. Add one on the Parties page first.`),
      field("Date", date), field("Due date", due), field(kind === "purchase" ? "Supplier bill no." : "Reference", ref), field("Place of supply", pos))),
    h("div", { class: "card" }, h("div", { class: "tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Item", "Description", "HSN", "Qty", "Unit", "Rate", "Disc %", "GST %", "Amount", ""].map((t, i) => h("th", { class: i >= 3 && i <= 8 && i !== 4 ? "num" : "" }, t)))), linesBody)),
      h("div", null, h("button", { class: "btn small", type: "button", onclick: () => addLine() }, "+ Add line")),
      h("p", { class: "small muted" }, kind === "sale" ? "Picking a stock item takes its price and GST from Items & stock, and reduces the stock when saved." : "Picking a stock item adds the quantity to stock when saved. Leave the item blank for expenses such as rent or electricity.")),
    totalsBox,
    h("div", { class: "card" }, h("div", { class: "row" }, field(kind === "sale" ? "Received now (Rs)" : "Paid now (Rs)", payAmt, "Leave empty if nothing was paid yet"), field("Mode", payMode)),
      field("Notes", notes)),
    h("div", { class: "right" }, save));
  if (draft) draft.lines.forEach((l) => addLine(l)); else addLine();
  recalc();
}

// ------------------------------------------------------------------ view / print

export async function renderInvoiceView(view, kind, id) {
  const cfg = CFG[kind];
  await loadStates();
  const inv = await get(`/api/${cfg.path}/${id}`);
  const s = state.settings;
  const intra = !!inv.intra;
  const cancelled = inv.status !== "active";

  const pay = () => formModal({
    title: `${cfg.payWord} for ${inv.number}`, submitText: "Save",
    values: { amount: inv.due, pay_date: todayStr(), mode: "cash" },
    fields: [{ key: "amount", label: "Amount (Rs)", type: "number", step: "0.01", min: 0, required: true, help: `Still due: ${money(inv.due)}` },
      { key: "pay_date", label: "Date", type: "date", required: true }, { key: "mode", label: "Mode", type: "select", options: PAY_MODES }, { key: "ref", label: "Reference (cheque no., UTR ...)" }],
    onSubmit: async (v) => { await post("/api/payments", { ...v, kind: cfg.payKind, party_id: inv.party_id, invoice_id: inv.id }); toast("Saved"); clear(view); await renderInvoiceView(view, kind, id); },
  });
  const cancel = async () => {
    if (!(await confirmBox("Cancel " + inv.number, "The invoice stays in the list as cancelled and its stock is put back. This cannot be undone.", "Cancel invoice", true))) return;
    try { await post(`/api/${cfg.path}/${inv.id}/cancel`, {}); toast("Cancelled"); clear(view); await renderInvoiceView(view, kind, id); } catch (e) { fail(e); }
  };
  const delPay = async (p) => {
    if (!(await confirmBox("Delete payment", `Delete ${p.number} (${money(p.amount)})?`, "Delete", true))) return;
    try { await del(`/api/payments/${p.id}`); toast("Deleted"); clear(view); await renderInvoiceView(view, kind, id); } catch (e) { fail(e); }
  };

  const taxCols = intra ? ["CGST", "SGST"] : ["IGST"];
  const hasDisc = inv.lines.some((l) => l.disc_pct);
  add(view,
    h("div", { class: "pagehead no-print" }, h("div", null, h("div", { class: "eyebrow" }, "Accounts"), h("h1", null, inv.number), h("div", { class: "sub" }, statusBadge(inv.pay_status))),
      h("div", { class: "actions" }, h("a", { class: "btn", href: `#/${cfg.path}` }, "Back"), " ",
        !cancelled && inv.due > 0.004 ? [h("button", { class: "btn primary", onclick: pay }, cfg.payBtn), " "] : null,
        !cancelled ? [h("button", { class: "btn", onclick: cancel }, "Cancel invoice"), " "] : null,
        h("button", { class: "btn", onclick: () => window.print() }, "Print"))),
    h("div", { class: "sheet" },
      logoImg(), h("h1", null, s.company_name || "Company"),
      h("div", { class: "sub", style: { textDecoration: "none" } }, [s.company_address, s.company_phone, s.company_gstin && `GSTIN ${s.company_gstin}`].filter(Boolean).join(" · ")),
      h("div", { class: "bar" }, kind === "sale" ? "TAX INVOICE" : "PURCHASE BILL" + (cancelled ? " (CANCELLED)" : "")),
      cancelled ? h("div", { class: "bar", style: { background: "#a22" } }, "CANCELLED") : null,
      h("div", { class: "hdr" },
        h("div", null, h("div", null, h("b", null, kind === "sale" ? "Bill to" : "Supplier")), h("div", null, inv.party_name), inv.party_address ? h("div", null, [inv.party_address, inv.party_pin].filter(Boolean).join(" - ")) : null,
          inv.party_gstin ? h("div", null, "GSTIN: " + inv.party_gstin) : null, inv.place_name ? h("div", null, `Place of supply: ${inv.place_of_supply} ${inv.place_name}`) : null),
        h("div", null, h("div", null, "No: ", h("b", null, inv.number)), h("div", null, "Date: ", fmtDate(inv.inv_date)), inv.due_date ? h("div", null, "Due: ", fmtDate(inv.due_date)) : null,
          inv.party_ref ? h("div", null, "Supplier bill no: ", inv.party_ref) : null)),
      h("div", { class: "tablewrap" }, h("table", { style: { marginTop: ".6rem" } },
        h("thead", null, h("tr", null, ["#", "Description", "HSN", "Qty", "Rate", ...(hasDisc ? ["Disc %"] : []), "Taxable", "GST %", ...taxCols, "Amount"].map((t, i) => h("th", { class: i >= 3 ? "num" : "" }, t)))),
        h("tbody", null, inv.lines.map((l, i) => h("tr", null, h("td", null, i + 1), h("td", null, l.description), h("td", null, l.hsn),
          h("td", { class: "num nowrap" }, `${num(l.qty)} ${l.unit}`), h("td", { class: "num" }, plain(l.rate)), ...(hasDisc ? [h("td", { class: "num" }, l.disc_pct || "")] : []),
          h("td", { class: "num" }, plain(l.taxable)), h("td", { class: "num" }, l.gst_rate), ...(intra ? [h("td", { class: "num" }, plain(l.cgst)), h("td", { class: "num" }, plain(l.sgst))] : [h("td", { class: "num" }, plain(l.igst))]),
          h("td", { class: "num" }, plain(l.amount)))))),
      ),
      h("table", { style: { maxWidth: "320px", marginLeft: "auto", marginTop: ".6rem" } }, h("tbody", null,
        h("tr", null, h("td", null, "Taxable value"), h("td", { class: "num" }, money(inv.taxable))),
        intra ? [h("tr", null, h("td", null, "CGST"), h("td", { class: "num" }, money(inv.cgst))), h("tr", null, h("td", null, "SGST"), h("td", { class: "num" }, money(inv.sgst)))] : h("tr", null, h("td", null, "IGST"), h("td", { class: "num" }, money(inv.igst))),
        inv.round_off ? h("tr", null, h("td", null, "Round off"), h("td", { class: "num" }, money(inv.round_off))) : null,
        h("tr", null, h("td", null, h("strong", null, "Total")), h("td", { class: "num" }, h("strong", null, money(inv.total)))),
        inv.paid ? h("tr", null, h("td", null, "Paid"), h("td", { class: "num" }, money(inv.paid))) : null,
        inv.paid && !cancelled ? h("tr", null, h("td", null, h("strong", null, "Balance due")), h("td", { class: "num" }, h("strong", null, money(inv.due)))) : null)),
      h("p", null, h("b", null, "Amount in words: "), inWords(inv.total)),
      inv.notes ? h("p", null, "Notes: " + inv.notes) : null,
      kind === "sale" && s.invoice_terms ? h("p", { class: "small" }, s.invoice_terms) : null,
      kind === "sale" ? h("div", { class: "sig" }, h("span", null, "Customer signature"), h("span", null, "For " + (s.company_name || ""))) : null),
    inv.payments.length ? h("div", { class: "card no-print" }, h("h2", null, cfg.payWord + "s"), h("div", { class: "tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Number", "Date", "Mode", "Reference", "Amount", ""].map((t, i) => h("th", { class: i === 4 ? "num" : "" }, t)))),
      h("tbody", null, inv.payments.map((p) => h("tr", null, h("td", null, p.number), h("td", null, fmtDate(p.pay_date)), h("td", null, p.mode), h("td", null, p.ref), h("td", { class: "num" }, money(p.amount)),
        h("td", { class: "right" }, h("button", { class: "btn small", onclick: () => delPay(p) }, "Delete")))))))) : null);
}

// ------------------------------------------------------------------ payments page

export async function renderPayments(view) {
  let rows = [], kind = "";
  const body = h("div");
  const parties = await get("/api/parties");
  async function load() {
    try { rows = await get("/api/payments" + (kind ? `?kind=${kind}` : "")); } catch (e) { return fail(e); }
    draw();
  }
  function draw() {
    clear(body);
    if (!rows.length) return add(body, emptyState("No payments recorded yet."));
    const inn = rows.filter((r) => r.kind === "in").reduce((a, r) => a + r.amount, 0), out = rows.filter((r) => r.kind === "out").reduce((a, r) => a + r.amount, 0);
    add(body, h("div", { class: "stats" }, h("div", { class: "stat" }, h("div", { class: "lbl" }, "Money received"), h("div", { class: "n" }, money(inn))),
      h("div", { class: "stat" }, h("div", { class: "lbl" }, "Money paid out"), h("div", { class: "n" }, money(out)))),
      h("div", { class: "card tablewrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Number", "Date", "Party", "Against", "Mode", "Reference", "Amount", ""].map((t, i) => h("th", { class: i === 6 ? "num" : "" }, t)))),
        h("tbody", null, rows.map((r) => h("tr", null, h("td", null, r.number), h("td", { class: "nowrap" }, fmtDate(r.pay_date)), h("td", null, r.party_name), h("td", null, r.invoice_number || "On account"),
          h("td", null, r.mode), h("td", null, r.ref), h("td", { class: "num" }, (r.kind === "in" ? "+ " : "− ") + money(r.amount)),
          h("td", { class: "right" }, h("button", { class: "btn small", onclick: async () => {
            if (!(await confirmBox("Delete payment", `Delete ${r.number} (${money(r.amount)})?`, "Delete", true))) return;
            try { await del(`/api/payments/${r.id}`); toast("Deleted"); await load(); } catch (e) { fail(e); } } }, "Delete"))))))));
  }
  const add_ = (k) => formModal({
    title: k === "in" ? "Receive money" : "Pay money", values: { pay_date: todayStr(), mode: "cash", party_id: "", invoice_id: "" },
    fields: [
      { key: "party_id", label: k === "in" ? "Received from" : "Paid to", type: "select", required: true,
        options: [["", "Choose..."], ...parties.filter((p) => (k === "in" ? p.party_type !== "supplier" : p.party_type !== "customer")).map((p) => [String(p.id), p.name])] },
      { key: "amount", label: "Amount (Rs)", type: "number", step: "0.01", min: 0, required: true, help: "Not against a particular invoice? It is kept on account and reduces the balance." },
      { key: "pay_date", label: "Date", type: "date", required: true }, { key: "mode", label: "Mode", type: "select", options: PAY_MODES },
      { key: "ref", label: "Reference" }, { key: "note", label: "Note" }],
    onSubmit: async (v) => { v.party_id = Number(v.party_id) || 0; await post("/api/payments", { ...v, kind: k }); toast("Saved"); await load(); },
  });
  const sel = select([["", "All"], ["in", "Received"], ["out", "Paid out"]], "", { "aria-label": "Direction", onchange: () => { kind = sel.value; load(); } });
  add(view, h("div", { class: "pagehead" }, h("div", null, h("div", { class: "eyebrow" }, "Accounts"), h("h1", null, "Payments"),
      h("div", { class: "sub" }, "Money received from customers and paid to suppliers. To settle a particular invoice, open it and use Record receipt / payment.")),
      h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => add_("in") }, "+ Receive money"), " ", h("button", { class: "btn", onclick: () => add_("out") }, "+ Pay money"))),
    h("div", { class: "toolbar" }, sel), body);
  await load();
}
