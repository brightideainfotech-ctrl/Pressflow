import { state, get, post, put, del, isOffice } from "./api.js";
import { h, add, clear, badge, field, select, formModal, toast, fail, num, money, fmtDateTime, debounce, emptyState, confirmBox, modal } from "./ui.js";

const CATEGORIES = [["paper", "Paper"], ["ink", "Ink"], ["plates", "Plates"], ["chemicals", "Chemicals"], ["binding", "Binding & finishing"], ["goods", "Finished goods / trading"], ["service", "Service (no stock)"], ["other", "Other"]];
const catName = (k) => (CATEGORIES.find((c) => c[0] === k) || [0, k])[1];
const KIND_TXT = { receive: "Received", issue: "Issued", return: "Returned", adjust: "Count corrected" };

export async function renderInventory(view) {
  const canEdit = isOffice();
  let items = [], papers = [], text = "", cat = "", lowOnly = false, showOff = false;
  const body = h("div");

  async function load() {
    try {
      items = await get("/api/stock" + (showOff ? "?all=1" : ""));
      if (canEdit && !papers.length) papers = await get("/api/papers");
    } catch (e) { return fail(e); }
    draw();
  }

  const fields = (it) => [
    { key: "name", label: "Item name", required: true },
    { key: "category", label: "Category", type: "select", options: CATEGORIES },
    { key: "unit", label: "Counted in", required: true, help: "kg, sheets, reams, pcs, rolls, litres ..." },
    { key: "paper_id", label: "Is this a paper in the Rate master?", type: "select",
      options: [["", "No / not paper"], ...papers.map((p) => [String(p.id), p.name])], help: "Linking lets jobs show how much of this paper they need and take it from this stock" },
    { key: "reorder_level", label: "Warn me when stock falls to", type: "number", step: "any", min: 0 },
    { key: "location", label: "Where it is kept" },
    { key: "hsn", label: "HSN / SAC code" }, { key: "gst_rate", label: "GST %", type: "number", step: "0.5", min: 0 },
    { key: "purchase_price", label: "Buying price (Rs per unit)", type: "number", step: "0.01", min: 0, help: "Updated automatically from each purchase bill; used for stock value" },
    { key: "sale_price", label: "Selling price (Rs per unit)", type: "number", step: "0.01", min: 0 },
    { key: "track_stock", label: "Keep count of stock for this item (untick for services)", type: "checkbox", default: true },
    ...(it ? [{ key: "active", label: "In use", type: "checkbox" }] : [{ key: "opening_qty", label: "Stock on hand now", type: "number", step: "any", min: 0 }]),
    { key: "notes", label: "Notes", type: "textarea" },
  ];
  const clean = (v) => { for (const k of ["reorder_level", "opening_qty", "gst_rate", "purchase_price", "sale_price"]) if (v[k] === "") v[k] = 0; v.paper_id = v.paper_id ? Number(v.paper_id) : 0; return v; };

  const editItem = (it) => formModal({
    title: it ? `Edit ${it.name}` : "Add stock item",
    values: it ? { ...it, paper_id: it.paper_id ? String(it.paper_id) : "", active: !!it.active, track_stock: !!it.track_stock } : { category: "paper", unit: "kg", paper_id: "", track_stock: true },
    fields: fields(it),
    onSubmit: async (v) => { v = clean(v); if (it) await put(`/api/stock/${it.id}`, v); else await post("/api/stock", v); toast("Saved"); await load(); },
  });

  const move = (it, kind) => {
    const cfg = {
      receive: { title: `Receive stock: ${it.name}`, label: `Quantity received (${it.unit})`, extra: [{ key: "ref", label: "Supplier / bill no." }] },
      issue: { title: `Take from stock: ${it.name}`, label: `Quantity taken (${it.unit})`, extra: [{ key: "job_id", label: "For job (optional)", type: "select", options: [["", "No particular job"], ...jobOpts] }] },
      adjust: { title: `Correct the count: ${it.name}`, label: `Counted quantity now (${it.unit})`, extra: [] },
    }[kind];
    formModal({
      title: cfg.title, submitText: kind === "adjust" ? "Correct count" : "Save", values: { job_id: "" },
      fields: [{ key: kind === "adjust" ? "counted" : "qty", label: cfg.label, type: "number", step: "any", min: 0, required: true,
        help: `System shows ${num(it.on_hand)} ${it.unit} now` }, ...cfg.extra,
        { key: "note", label: kind === "adjust" ? "Why (required)" : "Note (optional)" }],
      onSubmit: async (v) => { await post(`/api/stock/${it.id}/move`, { kind, ...v }); toast("Stock updated"); await load(); },
    });
  };
  let jobOpts = [];

  const history = async (it) => {
    let rows;
    try { rows = await get(`/api/stock/${it.id}/moves`); } catch (e) { return fail(e); }
    modal(`${it.name}: movements`, h("div", { class: "tablewrap" }, rows.length ? h("table", null,
      h("thead", null, h("tr", null, ["When", "What", "Qty", "Job", "By", "Note"].map((t, i) => h("th", { class: i === 2 ? "num" : "" }, t)))),
      h("tbody", null, rows.map((r) => h("tr", null, h("td", { class: "nowrap" }, fmtDateTime(r.at)), h("td", null, KIND_TXT[r.kind] || r.kind),
        h("td", { class: "num" }, (r.qty > 0 ? "+" : "") + num(r.qty)), h("td", null, r.order_no ? h("a", { href: `#/jobs/${r.job_id}` }, r.order_no) : "—"),
        h("td", null, r.user_name || ""), h("td", null, [r.ref, r.note].filter(Boolean).join(" · ")))))) : emptyState("No movements yet")));
  };

  function draw() {
    clear(body);
    const shown = items.filter((i) => (!cat || i.category === cat) && (!lowOnly || i.low) && (!text || i.name.toLowerCase().includes(text.toLowerCase())));
    const low = items.filter((i) => i.low);
    if (low.length && !lowOnly) add(body, h("div", { class: "banner" }, h("span", null, `${low.length} item${low.length > 1 ? "s are" : " is"} at or below the warning level: ${low.map((i) => i.name).join(", ")}.`)));
    if (!shown.length) return add(body, emptyState(items.length ? "Nothing matches." : "No stock items yet. Add your first one."));
    add(body, h("div", { class: "card tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Item", "Category", "On hand", "Warn at", "Selling price", "GST", ""].map((t, i) => h("th", { class: i >= 2 && i <= 4 ? "num" : "" }, t)))),
      h("tbody", null, shown.map((i) => h("tr", { style: i.active ? null : { opacity: ".55" } },
        h("td", null, h("strong", null, i.name), i.paper_name ? h("div", { class: "small muted" }, "Paper: " + i.paper_name) : null),
        h("td", null, catName(i.category)),
        h("td", { class: "num" }, i.track_stock ? [h("span", { class: i.low ? "flag" : "" }, `${num(i.on_hand)} ${i.unit}`), i.low ? h("div", { class: "small flag" }, "Low") : null] : h("span", { class: "muted" }, "not counted")),
        h("td", { class: "num" }, i.reorder_level ? `${num(i.reorder_level)} ${i.unit}` : "—"), h("td", { class: "num" }, i.sale_price ? money(i.sale_price) : "—"), h("td", null, i.gst_rate ? i.gst_rate + "%" : "—"),
        h("td", { class: "right nowrap" },
          h("button", { class: "btn small", onclick: () => move(i, "issue") }, "Take"),
          canEdit ? [" ", h("button", { class: "btn small", onclick: () => move(i, "receive") }, "Receive"), " ",
            h("button", { class: "btn small", onclick: () => move(i, "adjust") }, "Recount")] : null, " ",
          state.user.role !== "operator" ? h("button", { class: "btn small", onclick: () => history(i) }, "History") : null,
          canEdit ? [" ", h("button", { class: "btn small", onclick: () => editItem(i) }, "Edit")] : null)))))));
  }

  const search = h("input", { type: "search", placeholder: "Search stock", "aria-label": "Search stock", oninput: debounce(() => { text = search.value.trim(); draw(); }, 150) });
  const catSel = select([["", "All categories"], ...CATEGORIES], "", { "aria-label": "Category", onchange: () => { cat = catSel.value; draw(); } });
  const lowCb = h("input", { type: "checkbox", onchange: () => { lowOnly = lowCb.checked; draw(); } });
  const offCb = h("input", { type: "checkbox", onchange: () => { showOff = offCb.checked; load(); } });
  add(view,
    h("div", { class: "pagehead" }, h("div", null, h("div", { class: "eyebrow" }, "Workspace"), h("h1", null, "Items & stock"),
      h("div", { class: "sub" }, "Everything you buy or sell: paper, ink, plates, finished goods and services. Purchase bills add stock and sales invoices take it out.")),
      canEdit ? h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => editItem(null) }, "+ Add item")) : null),
    h("div", { class: "toolbar" }, search, catSel, h("label", { class: "check" }, lowCb, "Low stock only"), canEdit ? h("label", { class: "check" }, offCb, "Show items not in use") : null),
    body);
  try { jobOpts = (await get("/api/jobs?open=1")).map((j) => [String(j.id), `${j.order_no} · ${j.title}`]); } catch { /* optional */ }
  await load();
}
