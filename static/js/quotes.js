import { state, get, post, put, del, loadBootstrap } from "./api.js";
import { h, add, clear, badge, field, input, select, formModal, toast, fail, money, money0, num, fmtDate, todayStr,
         debounce, confirmBox, emptyState } from "./ui.js";

const COLOR_MODES = [["multi", "Multi-colour (4)"], ["two", "2 colour"], ["single", "Single colour"], ["bw", "Black & white"]];
const COLOR_TEXT = Object.fromEntries(COLOR_MODES);
const kgText = (kg) => (kg < 1 ? `${+(kg * 1000).toFixed(2)} g` : `${+kg.toFixed(3)} kg`);
const PARTS = [["text", "Text / inside pages"], ["cover", "Cover"], ["end_paper", "End paper"], ["insert", "Insert / fold-out sheet"]];
const PRESETS = [["", "Custom size…"], ["11.69x16.54", "A3 (11.69 × 16.54 in)"], ["8.27x11.69", "A4 (8.27 × 11.69 in)"],
  ["5.83x8.27", "A5 (5.83 × 8.27 in)"], ["4.13x5.83", "A6 (4.13 × 5.83 in)"], ["3.9x8.27", "DL (3.9 × 8.27 in)"],
  ["8.5x11", "Letter (8.5 × 11 in)"], ["3.5x2", "Visiting card (3.5 × 2 in)"]];
const BASIS = { per_copy: "per copy", per_1000: "per 1000", per_sqft: "per sq ft", per_unit: "per unit", job: "per job", per_1000_sheets: "per 1000 sheets", per_1000_leaves: "per 1000 leaves" };
const EDITABLE = ["draft", "sent", "rejected"];

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const statusBadge = (q) => (q.expired ? badge("expired", "Expired") : badge(q.status, cap(q.status)));

// ------------------------------------------------------------------ list

export async function renderQuoteList(view) {
  let status = "", text = "";
  const body = h("div");
  const load = async () => {
    const qs = new URLSearchParams();
    if (status) qs.set("status", status);
    if (text) qs.set("q", text);
    let rows;
    try { rows = await get("/api/quotations?" + qs); } catch (e) { return fail(e); }
    clear(body);
    if (!rows.length) return add(body, emptyState(status || text ? "No quotations match." : "No quotations yet. Create the first one."));
    add(body, h("div", { class: "tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Number", "Date", "Customer", "Job", "Copies", "Total", "Valid until", "Status"].map((t, i) => h("th", { class: i === 4 || i === 5 ? "num" : "" }, t)))),
      h("tbody", null, rows.map((q) => h("tr", { class: "clickable", onclick: () => (location.hash = `#/quotes/${q.id}`) },
        h("td", { class: "nowrap" }, q.number), h("td", { class: "nowrap" }, fmtDate(q.quote_date)), h("td", null, q.customer_name),
        h("td", null, q.title), h("td", { class: "num" }, num(q.copies)), h("td", { class: "num" }, money(q.total)),
        h("td", { class: "nowrap" }, fmtDate(q.valid_until)), h("td", null, statusBadge(q), q.job_no ? h("div", { class: "small muted" }, q.job_no) : null)))))));
  };
  const search = h("input", { type: "search", placeholder: "Search number, job or customer", "aria-label": "Search", oninput: debounce(() => { text = search.value.trim(); load(); }) });
  const filter = select([["", "All statuses"], ["draft", "Draft"], ["sent", "Sent"], ["accepted", "Accepted"], ["rejected", "Rejected"], ["converted", "Converted to job"]], "",
    { "aria-label": "Status", onchange: () => { status = filter.value; load(); } });
  add(view, h("div", { class: "pagehead" }, h("h1", null, "Quotations"),
    h("div", { class: "actions" }, h("a", { class: "btn primary", href: "#/quotes/new" }, "New quotation"))),
    h("div", { class: "toolbar" }, search, filter), h("div", { class: "card" }, body));
  await load();
}

// ------------------------------------------------------------------ shared pieces

export function breakdown(r) {
  const t = r.totals;
  const line = (a, b, c, cls) => h("tr", { class: cls }, h("td", null, a), h("td", { class: "small muted" }, b), h("td", { class: "num" }, c));
  const rows = [];
  for (const c of r.components) {
    rows.push(h("tr", null, h("td", { colspan: 3 }, h("strong", null, c.name), ` — ${num(c.pages)} pp, ${c.paper}`)));
    rows.push(line("Paper", `${num(c.sheets_gross)} sheets${c.paper_basis === "kg" ? " = " + kgText(c.paper_kg) + (c.paper_by_area ? " (by page area)" : c.paper_weight_src === "table" ? " (your weight table)" : "") : ""} · ${c.ups} up${c.ups_overridden ? " (your value)" : ""} · ${c.wastage_pct}% wastage`, money(c.paper_cost)));
    if (c.plates) rows.push(line("Plates", `${c.plates} × ${c.plate}`, money(c.plate_cost)));
    rows.push(line("Printing", `${c.machine} · ${num(c.impressions)} impressions`, money(c.print_cost)));
  }
  if (r.finishing.length) rows.push(h("tr", null, h("td", { colspan: 3 }, h("strong", null, "Binding & finishing"))));
  for (const f of r.finishing) rows.push(line(f.name, `${money(f.rate)} ${BASIS[f.basis]}${f.basis === "job" ? "" : " × " + num(f.qty)}${f.times && f.times !== 1 ? " × " + f.times + " times" : ""}${f.applies_to ? " · " + f.applies_to : ""}`, money(f.amount)));
  if (t.design) rows.push(line("Design / DTP", "", money(t.design)));
  for (const e of r.extras) rows.push(line(e.description, "other charge", money(e.amount)));
  rows.push(line("Cost", "", money(t.cost), "total"));
  rows.push(line(`Mark-up ${t.margin_pct}%`, `${t.margin_on_price_pct}% of selling price`, money(t.margin_amount)));
  if (t.discount) rows.push(line("Discount", "", "− " + money(t.discount)));
  rows.push(line("Price before GST", `${money(t.per_copy)} per copy`, money(t.pre_tax)));
  rows.push(line(`GST ${t.gst_pct}%`, "", money(t.gst)));
  if (t.round_off) rows.push(line("Round off", "", money(t.round_off)));
  return h("table", null, h("tbody", null, rows), h("tfoot", null, line("TOTAL", "", money(t.total), "total")));
}

function quoteSheet(q) {
  const s = state.settings, r = q.result, t = r.totals, c = q.customer;
  const specRows = [
    ["Job", q.title], ["Finished size", `${r.size_w} × ${r.size_h} in`], ["Quantity", `${num(r.copies)} copies`],
    ...r.components.map((p) => [p.name, `${num(p.pages)} pages · ${p.paper} · ${COLOR_TEXT[p.color_mode] || p.colors + " colour"}`]),
    ...(r.finishing.length ? [["Binding / finishing", r.finishing.map((f) => f.name + (f.note ? ` (${f.note})` : "")).join(", ")]] : []),
    ...(t.design ? [["Design / DTP", "Included"]] : []),
    ...r.extras.map((e) => ["Also included", e.description]),
  ];
  return h("section", { class: "sheet" },
    h("h1", null, s.company_name || "Quotation"),
    h("div", { class: "small", style: { textAlign: "center" } }, [s.company_address, s.company_phone, s.company_email].filter(Boolean).join(" · "),
      s.company_gstin ? h("div", null, "GSTIN: " + s.company_gstin) : null),
    h("div", { class: "sub", style: { marginTop: ".5rem" } }, "QUOTATION"),
    h("div", { class: "hdr" },
      h("div", null, h("strong", null, "To: "), c.name, c.contact_person ? h("div", null, "Attn: " + c.contact_person) : null,
        c.address ? h("div", null, c.address + (c.pin ? " - " + c.pin : "")) : null, c.gstin ? h("div", null, "GSTIN: " + c.gstin) : null),
      h("div", { class: "right" }, h("div", null, h("strong", null, "No: "), q.number), h("div", null, h("strong", null, "Date: "), fmtDate(q.quote_date)),
        q.valid_until ? h("div", null, h("strong", null, "Valid until: "), fmtDate(q.valid_until)) : null)),
    h("table", { style: { marginTop: ".8rem" } }, h("thead", null, h("tr", null, h("th", null, "Specification"), h("th", null, "Details"))),
      h("tbody", null, specRows.map(([a, b]) => h("tr", null, h("td", { class: "nowrap" }, a), h("td", null, b))))),
    h("table", { style: { marginTop: ".8rem", maxWidth: "380px", marginLeft: "auto" } }, h("tbody", null,
      h("tr", null, h("td", null, "Amount"), h("td", { class: "num" }, money(t.pre_tax))),
      h("tr", null, h("td", null, `GST ${t.gst_pct}%`), h("td", { class: "num" }, money(t.gst))),
      t.round_off ? h("tr", null, h("td", null, "Round off"), h("td", { class: "num" }, money(t.round_off))) : null,
      h("tr", { class: "total" }, h("td", null, "Total"), h("td", { class: "num" }, money(t.total))),
      h("tr", null, h("td", { class: "small" }, "Rate per copy (before GST)"), h("td", { class: "num small" }, money(t.per_copy))))),
    q.notes ? h("p", null, h("strong", null, "Notes: "), q.notes) : null,
    s.quote_terms ? h("p", { class: "small" }, h("strong", null, "Terms: "), s.quote_terms) : null,
    h("div", { class: "sig" }, h("span", null, "Customer acceptance"), h("span", null, "For " + (s.company_name || "the press"))));
}

// ------------------------------------------------------------------ view

export async function renderQuoteView(view, id) {
  const q = await get(`/api/quotations/${id}`);
  const act = async (fn, msg) => { try { await fn(); if (msg) toast(msg); clear(view); await renderQuoteView(view, id); } catch (e) { fail(e); } };
  const setStatus = (s, msg) => act(() => post(`/api/quotations/${id}/status`, { status: s }), msg);
  const btn = (label, fn, cls = "") => h("button", { class: "btn " + cls, onclick: fn }, label);

  const actions = [btn("Print", () => window.print())];
  if (EDITABLE.includes(q.status)) actions.push(h("a", { class: "btn", href: `#/quotes/${id}/edit` }, "Edit"));
  actions.push(btn("Copy as new", () => {
    window.__quoteDraft = { customer_id: q.customer_id, title: q.title + " (copy)", notes: q.notes, spec: q.spec };
    location.hash = "#/quotes/new";
  }));
  if (EDITABLE.includes(q.status)) actions.push(btn("Re-price with today's rates", () => act(() => post(`/api/quotations/${id}/recalculate`), "Quotation re-priced")));
  if (q.status === "draft") actions.push(btn("Mark as sent", () => setStatus("sent", "Marked as sent")));
  if (["draft", "sent"].includes(q.status)) actions.push(btn("Customer accepted", () => setStatus("accepted", "Marked as accepted")));
  if (["draft", "sent", "accepted"].includes(q.status)) actions.push(btn("Rejected", () => setStatus("rejected")));
  if (q.status === "rejected") actions.push(btn("Re-open as draft", () => setStatus("draft")));
  if (["draft", "sent", "accepted"].includes(q.status)) actions.push(btn("Create job", () => createJobDialog(q), "primary"));
  if (q.job) actions.push(h("a", { class: "btn primary", href: `#/jobs/${q.job.id}` }, `Open job ${q.job.order_no}`));
  if (q.status === "draft") actions.push(btn("Delete", async () => {
    if (await confirmBox("Delete quotation", `Delete draft ${q.number}? This cannot be undone.`, "Delete", true))
      act(async () => { await del(`/api/quotations/${id}`); location.hash = "#/quotes"; }, "Deleted");
  }, "danger"));

  add(view, 
    h("div", { class: "pagehead no-print" }, h("div", null, h("h1", null, `${q.number} · ${q.title}`),
      h("div", null, statusBadge(q), " ", h("span", { class: "muted" }, q.customer_name))), h("div", { class: "actions" }, actions)),
    q.result.warnings.length ? h("div", { class: "warnlist no-print" }, q.result.warnings.map((w) => h("div", null, "⚠ " + w))) : "",
    quoteSheet(q),
    h("div", { class: "card no-print" }, h("h2", null, "Internal cost breakdown"),
      h("p", { class: "small muted" }, "Not printed on the customer's copy. Prices below were fixed when this quotation was last saved or re-priced."),
      breakdown(q.result)));
}

async function createJobDialog(q) {
  let people = [];
  try { people = await get("/api/people"); } catch { /* assignment is optional */ }
  const plus = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  formModal({
    title: `Create job from ${q.number}`,
    submitText: "Create job",
    values: { delivery_date: plus(7), priority: "normal", advance: 0 },
    fields: [
      { key: "delivery_date", label: "Delivery date", type: "date" },
      { key: "proof_date", label: "Proof date", type: "date" },
      { key: "priority", label: "Priority", type: "select", options: [["normal", "Normal"], ["urgent", "Urgent"]] },
      { key: "advance", label: "Advance received (₹)", type: "number", step: "0.01", min: 0 },
      { key: "receipt_no", label: "Receipt no." },
      { key: "assign_to", label: "Give the job first to", type: "select", help: "Who starts it (for example the designer). Hand it on from the job page.",
        options: [["", "Nobody yet"], ...people.map((p) => [String(p.id), p.name + (p.department ? ` (${p.department})` : "")])] },
      { key: "designer", label: "Designer / DTP operator (printed on work order)" },
      { key: "extra_details", label: "Extra details", type: "textarea" },
    ],
    onSubmit: async (v) => {
      const job = await post(`/api/quotations/${q.id}/convert`, v);
      toast(`Job ${job.order_no} created`);
      location.hash = `#/jobs/${job.id}`;
    },
  });
}

// ------------------------------------------------------------------ editor with live estimate

const uid = () => Math.random().toString(36).slice(2, 10);
const SHEET_BASES = ["per_1000_sheets", "per_1000_leaves"];

function newPart(M, kind = "text") {
  const machine = M.machines.find((m) => /komori/i.test(m.name)) || M.machines[0];
  return {
    uid: uid(), part: kind, name: kind === "cover" ? "Cover" : kind === "end_paper" ? "End paper" : kind === "insert" ? "Insert" : "Text",
    paper_id: M.papers[0].id, pages: kind === "text" ? 2 : 4, color_mode: kind === "end_paper" ? "single" : "multi",
    machine_id: machine.id, plate_id: M.plates.length ? M.plates[0].id : "", ups: "", wastage_pct: "",
  };
}

export async function renderQuoteEditor(view, id) {
  await loadBootstrap();
  const M = state.masters, st = state.settings;
  if (!M.papers.length || !M.machines.length) {
    return add(view, h("div", { class: "card" }, h("h2", null, "Set up rates first"),
      h("p", null, "Add at least one paper and one machine before creating quotations."), h("a", { class: "btn primary", href: "#/rates" }, "Go to Rates")));
  }
  let customers = await get("/api/customers");
  const existing = id ? await get(`/api/quotations/${id}`) : null;
  if (existing && !EDITABLE.includes(existing.status)) { toast("This quotation is locked and cannot be edited", true); location.hash = `#/quotes/${id}`; return; }

  const seed = window.__quoteDraft; window.__quoteDraft = null;
  const src = existing || seed || null;
  const S = {
    customer_id: src ? String(src.customer_id) : "", title: src ? src.title : "", notes: src ? src.notes || "" : "",
    quote_date: existing ? existing.quote_date : "", valid_until: existing ? existing.valid_until : "",
    spec: src ? JSON.parse(JSON.stringify(src.spec)) : {
      size_w: 5.83, size_h: 8.27, copies: 1000, components: [newPart(M)], finishing: [], extras: [],
      design_charge: 0, margin_pct: st.default_margin_pct, gst_pct: st.gst_pct, discount: 0,
    },
  };
  // Specs saved through the API may omit optional lists; make sure the editor always has them.
  const sp = S.spec;
  sp.components = sp.components || [];
  sp.finishing = sp.finishing || [];
  sp.extras = sp.extras || [];
  for (const c of sp.components) { if (!c.part) c.part = "text"; if (!c.uid) c.uid = uid(); }
  for (const k of ["design_charge", "discount"]) if (sp[k] == null) sp[k] = 0;
  if (sp.margin_pct == null) sp.margin_pct = st.default_margin_pct;
  if (sp.gst_pct == null) sp.gst_pct = st.gst_pct;
  let breaksText = "";
  let last = null, seq = 0;
  const upsInputs = [];

  const payloadSpec = () => JSON.parse(JSON.stringify(S.spec));
  const parseBreaks = () => breaksText.split(/[,\s]+/).map(Number).filter((n) => Number.isInteger(n) && n > 0).slice(0, 6);

  // ---- estimate panel
  const estBody = h("div", null, h("p", { class: "muted" }, "Fill in the job to see the price."));
  async function runEstimate() {
    const my = ++seq;
    try {
      const r = await post("/api/estimate", { spec: payloadSpec(), quantities: parseBreaks() });
      if (my !== seq) return;
      last = r; showEstimate(r, null);
      upsInputs.forEach((el, i) => { if (el && r.components[i]) el.placeholder = r.components[i].ups_auto ? `auto: ${r.components[i].ups_auto}` : "required"; });
    } catch (e) { if (my === seq) { last = null; showEstimate(null, e.message); } }
  }
  const changed = debounce(runEstimate, 300);

  function showEstimate(r, err) {
    clear(estBody);
    if (err) return add(estBody, h("div", { class: "errbox" }, err));
    const t = r.totals;
    add(estBody, 
      r.warnings.length ? h("div", { class: "warnlist" }, r.warnings.map((w) => h("div", null, "⚠ " + w))) : "",
      h("div", { class: "muted small" }, "Total including GST"),
      h("div", { class: "bigtotal" }, money(t.total)),
      h("div", { class: "small muted", style: { marginBottom: ".75rem" } }, `${money(t.per_copy)} per copy before GST · mark-up ${t.margin_on_price_pct}% of price`),
      breakdown(r),
      r.breaks.length ? h("div", null, h("h3", { style: { marginTop: "1rem" } }, "Other quantities"),
        h("table", null, h("thead", null, h("tr", null, ["Copies", "Before GST", "Total", "Per copy"].map((x, i) => h("th", { class: i ? "num" : "" }, x)))),
          h("tbody", null, r.breaks.map((b) => h("tr", null, h("td", null, num(b.copies)), h("td", { class: "num" }, money(b.pre_tax)), h("td", { class: "num" }, money(b.total)), h("td", { class: "num" }, money(b.per_copy))))))) : null);
  }

  // ---- small helpers
  const bind = (obj, key, el, { number } = {}) => { el.addEventListener("input", () => { obj[key] = el.value; changed(); }); return el; };
  const opts = (list, label = (x) => x.name) => list.map((x) => [x.id, label(x)]);

  // ---- customer & job
  const custSelect = h("select", { "aria-label": "Customer" });
  const fillCustomers = () => {
    clear(custSelect);
    add(custSelect, h("option", { value: "" }, "Choose customer…"), customers.map((c) => h("option", { value: c.id }, c.name)));
    custSelect.value = S.customer_id;
  };
  fillCustomers();
  custSelect.addEventListener("change", () => { S.customer_id = custSelect.value; });
  const newCustomer = () => formModal({
    title: "New customer", fields: [
      { key: "name", label: "Customer name", required: true }, { key: "contact_person", label: "Contact person" },
      { key: "phone1", label: "Phone" }, { key: "email", label: "E-mail" }, { key: "address", label: "Address" }, { key: "pin", label: "PIN" }],
    onSubmit: async (v) => { const c = await post("/api/customers", v); customers.push(c); S.customer_id = String(c.id); fillCustomers(); },
  });

  const preset = select(PRESETS, "", { "aria-label": "Size preset" });
  const wIn = bind(S.spec, "size_w", input("number", S.spec.size_w, { step: "0.01", min: "0.1" }));
  const hIn = bind(S.spec, "size_h", input("number", S.spec.size_h, { step: "0.01", min: "0.1" }));
  preset.addEventListener("change", () => {
    if (!preset.value) return;
    const [w, hh] = preset.value.split("x");
    wIn.value = S.spec.size_w = w; hIn.value = S.spec.size_h = hh; changed();
  });

  const jobCard = h("div", { class: "card" }, h("h2", null, "Customer & job"),
    h("div", { class: "row" },
      h("div", null, field("Customer", custSelect), h("button", { class: "btn small", type: "button", onclick: newCustomer, style: { marginTop: "-.3rem", marginBottom: ".6rem" } }, "+ New customer")),
      field("Job name", bind(S, "title", input("text", S.title, { placeholder: "e.g. School magazine 2026", maxlength: 120 })))),
    h("div", { class: "row" },
      field("Size preset", preset), field("Width (in)", wIn), field("Height (in)", hIn),
      field("Copies", bind(S.spec, "copies", input("number", S.spec.copies, { min: "1", step: "1" })))),
    h("div", { class: "row" },
      field("Quotation date", bind(S, "quote_date", input("date", S.quote_date)), "Blank = today"),
      field("Valid until", bind(S, "valid_until", input("date", S.valid_until)), `Blank = ${st.quote_valid_days} days after the date`)),
    field("Notes (printed on the quotation)", bind(S, "notes", h("textarea", { value: S.notes }))));

  // ---- parts
  const partsBox = h("div");
  function renderParts() {
    clear(partsBox); upsInputs.length = 0;
    S.spec.components.forEach((p, i) => {
      const machine = M.machines.find((m) => String(m.id) === String(p.machine_id));
      const upsEl = bind(p, "ups", input("number", p.ups, { min: "1", step: "1", placeholder: "auto" }));
      upsInputs[i] = upsEl;
      const sel = (key, list, rerender) => {
        const el = select(list, p[key]);
        el.addEventListener("change", () => { p[key] = el.value; if (rerender) renderParts(); changed(); });
        return el;
      };
      add(partsBox, h("div", { class: "partcard" },
        h("div", { class: "head" }, h("strong", null, `Part ${i + 1}`),
          S.spec.components.length > 1 ? h("button", { class: "btn small danger", type: "button", onclick: () => { const [gone] = S.spec.components.splice(i, 1); S.spec.finishing.forEach((x) => { if (x.apply_to === gone.uid) x.apply_to = "all"; }); renderParts(); renderFinishing(); changed(); } }, "Remove") : null),
        h("div", { class: "row" },
          field("Type", sel("part", PARTS)), field("Name", bind(p, "name", input("text", p.name, { maxlength: 60 }))),
          field("Paper", sel("paper_id", opts(M.papers))), field("Pages", bind(p, "pages", input("number", p.pages, { min: "1", step: "1" })))),
        h("div", { class: "row" },
          field("Colour", sel("color_mode", COLOR_MODES)), field("Machine", sel("machine_id", opts(M.machines), true)),
          machine && machine.needs_plate ? field("Plate type", sel("plate_id", opts(M.plates))) : null,
          field("Pages per sheet side", upsEl, ((M.papers.find((x) => x.id == p.paper_id) || {}).width_in > 0) ? "Leave blank to calculate" : "Required: this paper has no sheet size"),
          field("Wastage %", bind(p, "wastage_pct", input("number", p.wastage_pct, { min: "0", step: "0.5", placeholder: st.wastage_pct })))),
      ));
    });
    if (last) upsInputs.forEach((el, i) => { if (el && last.components[i]) el.placeholder = last.components[i].ups_auto ? `auto: ${last.components[i].ups_auto}` : "required"; });
  }
  renderParts();
  const partsCard = h("div", { class: "card" }, h("h2", null, "Printed parts"), partsBox,
    h("div", { style: { display: "flex", gap: ".5rem", flexWrap: "wrap" } },
      h("button", { class: "btn small", type: "button", onclick: () => { S.spec.components.push(newPart(M, S.spec.components.some((c) => c.part === "cover") ? "text" : "cover")); renderParts(); changed(); } }, "+ Add part"),
      h("span", { class: "help" }, "Add a separate part for the cover, end paper, or inserts printed on different paper or machines.")));

  // ---- finishing
  const finBox = h("div");
  function renderFinishing() {
    clear(finBox);
    const groups = {};
    M.finishing.forEach((f) => (groups[f.group_name] = groups[f.group_name] || []).push(f));
    Object.entries(groups).forEach(([g, items]) => {
      add(finBox, h("div", { class: "fingroup" }, h("h3", null, g), h("div", { class: "fingrid" }, items.map((f) => {
        const line = S.spec.finishing.find((x) => String(x.finishing_id) === String(f.id));
        const cb = h("input", { type: "checkbox", checked: !!line });
        cb.addEventListener("change", () => {
          if (cb.checked) S.spec.finishing.push({ finishing_id: f.id, qty: "", note: "" });
          else S.spec.finishing = S.spec.finishing.filter((x) => String(x.finishing_id) !== String(f.id));
          renderFinishing(); changed();
        });
        const qty = line ? bind(line, "qty", input("number", line.qty, { min: "0", step: "any", placeholder: f.basis === "per_unit" ? "qty (needed)" : "auto", "aria-label": `${f.name} quantity`, title: "Quantity, if different from the number of copies" })) : null;
        const extra = [];
        if (line && SHEET_BASES.includes(f.basis)) {
          const sel = select([["all", "Whole job (all parts)"], ...S.spec.components.map((c) => [c.uid, c.name || "Part"])], line.apply_to || "all", { "aria-label": `${f.name} applies to` });
          sel.addEventListener("change", () => { line.apply_to = sel.value; changed(); });
          extra.push(h("label", { class: "small muted" }, "Applies to ", sel));
        }
        if (line && f.basis !== "job") {
          extra.push(h("label", { class: "small muted" }, f.basis === "per_unit" ? "" : "Times (e.g. folds) ",
            f.basis === "per_unit" ? null : bind(line, "times", input("number", line.times ?? "", { min: "0", step: "any", placeholder: "1", "aria-label": `${f.name} times`, style: "width:4.5rem" }))));
        }
        return h("div", { class: "finsel" }, h("label", { class: "check" }, cb, f.name), qty, extra.length ? h("div", { class: "fininfo" }, extra) : null);
      }))));
    });
    if (!M.finishing.length) add(finBox, h("p", { class: "muted" }, "No finishing items set up yet (Rates → Finishing)."));
  }
  renderFinishing();
  const finCard = h("div", { class: "card" }, h("h2", null, "Binding & finishing"), finBox,
    h("p", { class: "help" }, "Tick what the job needs. Leave the quantity blank to work it out automatically (copies, or the sheets / leaves of the parts you choose). For folding, creasing or pasting pick which part it applies to, and set Times for several folds."));

  // ---- charges & pricing
  const extrasBox = h("div");
  function renderExtras() {
    clear(extrasBox);
    S.spec.extras.forEach((e, i) => add(extrasBox, h("div", { class: "row tight", style: { alignItems: "end" } },
      field("Description", bind(e, "description", input("text", e.description, { maxlength: 120, placeholder: "e.g. Foil block, die, courier" }))),
      field("Amount (₹)", bind(e, "amount", input("number", e.amount, { min: "0", step: "0.01" }))),
      h("div", null, h("button", { class: "btn small danger", type: "button", style: { marginBottom: ".6rem" }, onclick: () => { S.spec.extras.splice(i, 1); renderExtras(); changed(); } }, "Remove")))));
  }
  renderExtras();
  const priceCard = h("div", { class: "card" }, h("h2", null, "Charges & pricing"),
    field("Design / DTP charge (₹)", bind(S.spec, "design_charge", input("number", S.spec.design_charge, { min: "0", step: "0.01" }))),
    extrasBox,
    h("button", { class: "btn small", type: "button", style: { marginBottom: ".9rem" }, onclick: () => { S.spec.extras.push({ description: "", amount: "" }); renderExtras(); } }, "+ Other charge"),
    h("div", { class: "row" },
      field("Mark-up on cost %", bind(S.spec, "margin_pct", input("number", S.spec.margin_pct, { min: "0", step: "0.5" }))),
      field("GST %", bind(S.spec, "gst_pct", input("number", S.spec.gst_pct, { min: "0", step: "0.5" }))),
      field("Discount (₹)", bind(S.spec, "discount", input("number", S.spec.discount, { min: "0", step: "0.01" })), "Taken off before GST")),
    field("Compare other quantities", (() => { const el = input("text", "", { placeholder: "e.g. 500, 1000, 2000" }); el.addEventListener("input", () => { breaksText = el.value; changed(); }); return el; })(),
      "Shows the price for the same job at other copy counts"));

  // ---- save
  const saveBtn = h("button", { class: "btn primary", type: "button" }, id ? "Save changes" : "Save quotation");
  saveBtn.addEventListener("click", async () => {
    if (!S.customer_id) return toast("Choose a customer first", true);
    if (!S.title.trim()) return toast("Give the job a name", true);
    saveBtn.disabled = true;
    try {
      const body = { customer_id: Number(S.customer_id), title: S.title, notes: S.notes, quote_date: S.quote_date, valid_until: S.valid_until, spec: payloadSpec() };
      const saved = id ? await put(`/api/quotations/${id}`, body) : await post("/api/quotations", body);
      toast(`Quotation ${saved.number} saved`);
      location.hash = `#/quotes/${saved.id}`;
    } catch (e) { fail(e); saveBtn.disabled = false; }
  });

  add(view, 
    h("div", { class: "pagehead" }, h("h1", null, id ? `Edit ${existing.number}` : "New quotation"),
      h("div", { class: "actions" }, h("a", { class: "btn", href: id ? `#/quotes/${id}` : "#/quotes" }, "Cancel"), saveBtn)),
    state.settings.rates_confirmed !== "1" ? h("div", { class: "banner" }, "Rates are still sample values: prices shown are for trying the app out only.") : "",
    h("div", { class: "cols two" },
      h("div", null, jobCard, partsCard, finCard, priceCard),
      h("div", { class: "card sticky", "aria-live": "polite" }, h("h2", null, "Estimate"), estBody)));
  runEstimate();
}
