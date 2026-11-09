import { state, get, post, put, del, isManager } from "./api.js";
import { sheetSizeField, weightsEditor, sizeNameFor } from "./sizes.js";
import { h, add, clear, badge, field, input, select, formModal, modal, toast, fail, money, num, confirmBox, emptyState, debounce } from "./ui.js";

/**
 * Generic list + add/edit/remove screen.
 * columns: [{label, get(row), num?}]   fields: formModal field definitions
 */
function crud({ endpoint, noun, columns, fields, defaults = {}, noRemove = false, createFields, editFields, afterChange, prepare, afterSave }) {
  let rows = [], text = "", showInactive = false;
  const body = h("div", { class: "tablewrap" });

  const normalise = (v, fs) => {
    const out = { ...v };
    for (const f of fs) if (f.type === "number" && out[f.key] === "" && !f.required) out[f.key] = 0;
    return out;
  };

  const openForm = async (row) => {
    let extra = {};
    if (prepare && row) { try { extra = await prepare(row); } catch (e) { return fail(e); } }
    formModal({
    title: row ? `Edit ${noun}` : `Add ${noun}`,
    fields: row ? (editFields || fields) : (createFields || fields),
    values: row ? { ...row, ...extra, active: !!row.active } : defaults,
    onSubmit: async (v) => {
      const fs = row ? (editFields || fields) : (createFields || fields);
      const payload = normalise(v, fs);
      const saveExtra = afterSave ? afterSave(payload) : null;
      const saved = row ? await put(`${endpoint}/${row.id}`, payload) : await post(endpoint, payload);
      if (saveExtra) await saveExtra(saved);
      toast("Saved");
      if (afterChange) await afterChange();
      await load();
    },
    });
  };

  const draw = () => {
    clear(body);
    const q = text.toLowerCase();
    const shown = rows.filter((r) => (showInactive || r.active) && (!q || JSON.stringify(Object.values(r)).toLowerCase().includes(q)));
    if (!shown.length) return add(body, emptyState(rows.length ? "Nothing matches." : `No ${noun}s yet.`));
    add(body, h("table", null,
      h("thead", null, h("tr", null, columns.map((c) => h("th", { class: c.num ? "num" : "" }, c.label)), h("th", null, ""))),
      h("tbody", null, shown.map((r) => h("tr", { style: r.active ? null : { opacity: ".55" } },
        columns.map((c) => h("td", { class: c.num ? "num" : "" }, c.get(r))),
        h("td", { class: "nowrap right" },
          h("button", { class: "btn small", onclick: () => openForm(r) }, "Edit"), " ",
          !r.active ? h("button", { class: "btn small", onclick: async () => { try { await put(`${endpoint}/${r.id}`, { active: true }); await load(); } catch (e) { fail(e); } } }, "Restore")
            : noRemove ? null : h("button", { class: "btn small danger", onclick: async () => {
              if (!(await confirmBox(`Remove ${noun}`, `Remove "${r.name}"? Saved quotations and jobs keep their data.`, "Remove", true))) return;
              try { await del(`${endpoint}/${r.id}`); if (afterChange) await afterChange(); await load(); } catch (e) { fail(e); }
            } }, "Remove")))))));
  };

  async function load() {
    try { rows = await get(endpoint + "?all=1"); } catch (e) { return fail(e); }
    draw();
  }

  const search = h("input", { type: "search", placeholder: `Search ${noun}s`, "aria-label": "Search", oninput: debounce(() => { text = search.value.trim(); draw(); }, 150) });
  const inactiveCb = h("input", { type: "checkbox", onchange: () => { showInactive = inactiveCb.checked; draw(); } });
  const el = h("div", null,
    h("div", { class: "toolbar" }, search, h("label", { class: "check" }, inactiveCb, "Show removed"),
      h("button", { class: "btn primary", onclick: () => openForm(null) }, `Add ${noun}`)),
    h("div", { class: "card" }, body));
  return { el, load };
}

const yn = (v) => (v ? "Yes" : "No");

// ------------------------------------------------------------------ customers

export async function renderCustomers(view) {
  const c = crud({
    endpoint: "/api/customers", noun: "customer", noRemove: false,
    columns: [
      { label: "Customer", get: (r) => r.name }, { label: "Contact", get: (r) => r.contact_person },
      { label: "Phone", get: (r) => [r.phone1, r.phone2].filter(Boolean).join(", ") }, { label: "E-mail", get: (r) => r.email },
      { label: "Address", get: (r) => [r.address, r.pin].filter(Boolean).join(" - ") }],
    fields: [
      { key: "name", label: "Customer name", required: true }, { key: "contact_person", label: "Contact person" },
      { key: "phone1", label: "Phone 1" }, { key: "phone2", label: "Phone 2" }, { key: "email", label: "E-mail" },
      { key: "address", label: "Address" }, { key: "pin", label: "PIN" }, { key: "gstin", label: "GSTIN" },
      { key: "notes", label: "Notes", type: "textarea" }, { key: "active", label: "Active", type: "checkbox", default: true }],
  });
  add(view, h("div", { class: "pagehead" }, h("h1", null, "Customers")), c.el);
  await c.load();
}

// ------------------------------------------------------------------ rates

const KINDS = [["offset", "Offset (sheet-fed)"], ["web", "Web"], ["digital", "Digital / laser"], ["riso", "RISO"]];
const BASES = [["per_copy", "Per copy"], ["per_1000", "Per 1000 copies"], ["per_sqft", "Per sq ft of finished size"], ["per_unit", "Per unit (quantity entered on quotation)"], ["per_1000_sheets", "Per 1000 printed sheets (folding, creasing: every sheet of the chosen part)"], ["per_1000_leaves", "Per 1000 leaves (pages ÷ 2, e.g. pasting each leaf)"], ["job", "Flat per job"]];
const BASIS_TXT = Object.fromEntries(BASES.map(([k, v]) => [k, v]));
const active = { key: "active", label: "Active", type: "checkbox", default: true };

async function weightsModal(paper) {
  let list;
  try { list = await get(`/api/papers/${paper.id}/sizes`); } catch (e) { return fail(e); }
  const ed = weightsEditor(list);
  const save = h("button", { class: "btn primary", onclick: async () => {
    try { await put(`/api/papers/${paper.id}/sizes`, { sizes: ed.getValue() }); toast("Weights saved"); m.close(); await refresh(); } catch (e) { fail(e); }
  } }, "Save weights");
  const m = modal(`Weights: ${paper.name}`, h("div", null,
    h("p", { class: "small muted" }, `How many kg do 100 sheets of each size of ${paper.name} weigh? A job uses the row that matches its size (width and height can be either way round).`), ed),
    { footer: [h("button", { class: "btn", onclick: () => m.close() }, "Cancel"), save] });
}

const RATE_TABS = [
  ["Paper", () => crud({
    endpoint: "/api/papers", noun: "paper", afterChange: refresh,
    columns: [{ label: "Paper", get: (r) => r.name }, { label: "GSM", num: true, get: (r) => r.gsm || "" },
      { label: "Sheet size (in)", get: (r) => (r.width_in > 0 ? `${sizeNameFor(r.width_in, r.height_in) ? sizeNameFor(r.width_in, r.height_in) + " · " : ""}${r.width_in} × ${r.height_in}` : "no fixed size") }, { label: "Bought by", get: (r) => (r.pricing === "kg" ? "Weight (kg)" : "Ream") },
      { label: "Rate", num: true, get: (r) => (r.pricing === "kg" ? `${money(r.rate_per_kg)} / kg` : `${money(r.rate_per_ream)} / ream`) },
      { label: "Weight worked out", get: (r) => (r.pricing !== "kg" ? "—" : r.weight_mode === "table"
        ? h("button", { class: "btn small", onclick: () => weightsModal(r) }, "My weights per size") : "From GSM and size") }],
    fields: [{ key: "name", label: "Paper name", required: true }, { key: "gsm", label: "GSM (g per m²)", type: "number", min: 0, help: "Needed for paper priced by weight" },
      { key: "pricing", label: "Price this paper by", type: "select", options: [["ream", "Ream of 500 sheets"], ["kg", "Weight in kg (reels, kg-priced paper)"]] },
      { key: "weight_mode", label: "How is the weight of paper worked out?", type: "select",
        options: [["auto", "Automatically, from GSM and size"], ["table", "From my own figures: kg per 100 sheets for each size"]],
        help: "Only for paper priced by weight. If you choose your own figures, enter them in the table below" },
      { key: "sheet", label: "Sheet size", type: "custom", full: true, merge: true, render: (v) => sheetSizeField(v),
        help: "Pick a standard size or choose Custom. For reel / kg paper with no fixed size, leave it as ‘No fixed size’" },
      { key: "rate_per_ream", label: "Rate per ream of 500 sheets (₹)", type: "number", step: "0.01", help: "Used when priced by ream" },
      { key: "rate_per_kg", label: "Rate per kg (₹)", type: "number", step: "0.01", help: "Used when priced by weight. With no sheet size, weight comes from the pages printed × GSM" },
      { key: "sizes", label: "My weight for each paper size (kg per 100 sheets)", type: "custom", full: true, render: (v) => weightsEditor(v.sizes || []),
        help: "Only used when ‘How is the weight…’ is set to my own figures. Pick a standard size or Custom for each row" }, active],
    defaults: { gsm: 80, pricing: "ream", active: true },
    prepare: async (r) => ({ sizes: await get(`/api/papers/${r.id}/sizes`) }),
    afterSave: (payload) => {
      const sizes = payload.sizes; delete payload.sizes;
      return async (saved) => { if (sizes && (sizes.length || saved)) await put(`/api/papers/${saved.id}/sizes`, { sizes }); };
    },
  })],
  ["Machines", () => crud({
    endpoint: "/api/machines", noun: "machine", afterChange: refresh,
    columns: [{ label: "Machine", get: (r) => r.name }, { label: "Type", get: (r) => (KINDS.find((k) => k[0] === r.kind) || [0, r.kind])[1] },
      { label: "₹ / 1000", num: true, get: (r) => money(r.rate_per_1000) }, { label: "Per colour", get: (r) => yn(r.per_color) },
      { label: "Set-up / plate", num: true, get: (r) => money(r.setup_per_plate) }, { label: "Minimum", num: true, get: (r) => money(r.min_charge) }, { label: "Plates", get: (r) => yn(r.needs_plate) }],
    fields: [{ key: "name", label: "Machine name", required: true }, { key: "kind", label: "Type", type: "select", options: KINDS },
      { key: "rate_per_1000", label: "Rate per 1000 impressions (₹)", type: "number", step: "0.01", required: true, help: "Per colour if ‘Charge per colour’ is ticked, otherwise per sheet side (digital click rate)" },
      { key: "per_color", label: "Charge per colour", type: "checkbox", default: true },
      { key: "setup_per_plate", label: "Set-up charge per plate / form (₹)", type: "number", step: "0.01" },
      { key: "min_charge", label: "Minimum charge per job (₹)", type: "number", step: "0.01" },
      { key: "makeready_sheets", label: "Make-ready sheets per plate", type: "number", min: 0, help: "Paper spoiled while setting up" },
      { key: "needs_plate", label: "Uses printing plates", type: "checkbox", default: true },
      { key: "max_colors", label: "Colours per pass", type: "number", min: 0, help: "Used only to warn when a job needs several passes. 0 = no limit" }, active],
    defaults: { kind: "offset", per_color: true, needs_plate: true, active: true },
  })],
  ["Plates", () => crud({
    endpoint: "/api/plates", noun: "plate type", afterChange: refresh,
    columns: [{ label: "Plate type", get: (r) => r.name }, { label: "Rate per plate", num: true, get: (r) => money(r.rate) }],
    fields: [{ key: "name", label: "Plate type", required: true }, { key: "rate", label: "Rate per plate (₹)", type: "number", step: "0.01", required: true }, active],
    defaults: { active: true },
  })],
  ["Binding & finishing", () => crud({
    endpoint: "/api/finishing", noun: "finishing item", afterChange: refresh,
    columns: [{ label: "Item", get: (r) => r.name }, { label: "Group", get: (r) => r.group_name }, { label: "Charged", get: (r) => BASIS_TXT[r.basis] },
      { label: "Rate", num: true, get: (r) => money(r.rate) }, { label: "Minimum", num: true, get: (r) => money(r.min_charge) }],
    fields: [{ key: "name", label: "Item name", required: true }, { key: "group_name", label: "Group", help: "Items with the same group appear together on the quotation screen" },
      { key: "basis", label: "Charged", type: "select", options: BASES }, { key: "rate", label: "Rate (₹)", type: "number", step: "0.01", required: true },
      { key: "min_charge", label: "Minimum charge (₹)", type: "number", step: "0.01" }, active],
    defaults: { group_name: "Finishing", basis: "per_copy", active: true },
  })],
];

async function refresh() { try { const b = await get("/api/bootstrap"); state.masters = b.masters; } catch { /* ignore */ } }

export async function renderRates(view) {
  const holder = h("div");
  const tabs = h("div", { class: "toolbar", role: "tablist" });
  let current = 0;
  const show = async (i) => {
    current = i;
    tabs.querySelectorAll("button").forEach((b, j) => { b.classList.toggle("primary", j === i); b.setAttribute("aria-selected", String(j === i)); });
    clear(holder);
    const c = RATE_TABS[i][1]();
    add(holder, c.el);
    await c.load();
  };
  RATE_TABS.forEach(([label], i) => add(tabs, h("button", { class: "btn", role: "tab", onclick: () => show(i) }, label)));
  add(view, h("div", { class: "pagehead" }, h("h1", null, "Rates")),
    h("p", { class: "muted" }, "These rates drive every estimate. Changing a rate does not alter saved quotations unless you re-price them."),
    tabs, holder);
  await show(current);
}

// ------------------------------------------------------------------ users

const ROLES = [["manager", "Manager: everything"], ["desk", "Front desk: quotations, customers, jobs"],
  ["superintendent", "Superintendent: jobs and production (no prices)"], ["operator", "Machine operator: move jobs through production (no prices)"]];

export async function renderUsers(view) {
  const body = h("div", { class: "tablewrap" });
  async function load() {
    let users;
    try { users = await get("/api/users"); } catch (e) { return fail(e); }
    clear(body);
    add(body, h("table", null, h("thead", null, h("tr", null, ["Name", "Username", "Role", "Department", "Status", ""].map((t) => h("th", null, t)))),
      h("tbody", null, users.map((u) => h("tr", { style: u.active ? null : { opacity: ".55" } },
        h("td", null, u.name), h("td", null, u.username), h("td", null, (ROLES.find((r) => r[0] === u.role) || [0, u.role])[1].split(":")[0]),
        h("td", null, u.department || "—"), h("td", null, u.active ? "Active" : "Disabled"),
        h("td", { class: "right" }, h("button", { class: "btn small", onclick: () => edit(u) }, "Edit")))))));
  }
  const edit = (u) => formModal({
    title: u ? `Edit ${u.name}` : "Add user", values: u || { role: "desk", active: true },
    fields: [{ key: "name", label: "Full name", required: true }, ...(u ? [] : [{ key: "username", label: "Username", required: true, help: "Letters, digits and . _ @ -" }]),
      { key: "role", label: "Role", type: "select", options: ROLES },
      { key: "department", label: "Department", help: "For example Design, Plates, Press, Binding. Shown when jobs are handed over." },
      { key: "password", label: u ? "New password (leave blank to keep)" : "Password", type: "password", required: !u, help: "At least 8 characters" },
      ...(u ? [{ key: "active", label: "Can sign in", type: "checkbox" }] : [])],
    onSubmit: async (v) => {
      if (u) { if (!v.password) delete v.password; await put(`/api/users/${u.id}`, v); } else await post("/api/users", v);
      toast("Saved"); await load();
    },
  });
  add(view, h("div", { class: "pagehead" }, h("h1", null, "Users"), h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => edit(null) }, "Add user"))),
    h("div", { class: "card" }, body));
  await load();
}

// ------------------------------------------------------------------ settings

export async function renderSettings(view) {
  const s = await get("/api/settings");
  const text = (key, label, help) => [key, field(label, input("text", s[key] || ""), help)];
  const numF = (key, label, help, step = "0.01") => [key, field(label, input("number", s[key], { step, min: "0" }), help)];
  const parts = [
    text("company_name", "Press name"), text("company_address", "Address"), text("company_phone", "Phone"), text("company_email", "E-mail"), text("company_gstin", "GSTIN"),
    numF("gst_pct", "Default GST %", "Confirm the correct rate for your jobs with your accountant", "0.5"), text("hsn_default", "Default HSN code"),
    numF("default_margin_pct", "Default mark-up on cost %", "Starting value on each new quotation", "0.5"),
    numF("wastage_pct", "Default paper wastage %", "Added to every printed part unless overridden", "0.5"),
    numF("bleed_in", "Bleed (in)", "Added around each page when working out how many fit on a sheet", "0.005"),
    numF("gripper_in", "Gripper margin (in)", "Strip of the sheet the machine holds and cannot print on", "0.05"),
    numF("quote_valid_days", "Quotation valid for (days)", null, "1"),
  ];
  const inputs = Object.fromEntries(parts.map(([k, el]) => [k, el.querySelector("input")]));
  const round = h("input", { type: "checkbox", checked: s.round_to_rupee === "1" });
  const terms = h("textarea", { value: s.quote_terms || "" });
  const confirmed = h("input", { type: "checkbox", checked: s.rates_confirmed === "1" });
  const save = h("button", { class: "btn primary" }, "Save settings");
  save.addEventListener("click", async () => {
    const body = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value]));
    body.round_to_rupee = round.checked; body.quote_terms = terms.value; body.rates_confirmed = confirmed.checked;
    save.disabled = true;
    try { state.settings = await put("/api/settings", body); toast("Settings saved"); }
    catch (e) { fail(e); } finally { save.disabled = false; }
  });
  add(view, h("div", { class: "pagehead" }, h("h1", null, "Settings")),
    h("div", { class: "card" }, h("h2", null, "Press details & defaults"), h("div", { class: "row" }, parts.map(([, el]) => el)),
      h("label", { class: "check", style: { marginBottom: ".8rem" } }, round, "Round quotation totals to the nearest rupee"),
      field("Terms printed on quotations", terms),
      h("label", { class: "check", style: { marginBottom: ".8rem" } }, confirmed, "I have replaced the sample rates with our real rates (hides the warning banner)"),
      h("div", null, save)));
}
