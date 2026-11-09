import { state, get, post, put, isOffice, stageLabel } from "./api.js";
import { h, add, clear, badge, field, select, formModal, toast, fail, money, num, fmtDate, fmtDateTime, debounce, emptyState, logoImg, printHeader } from "./ui.js";

export const progressBar = (pct) => h("div", { class: "pbar", title: `${pct || 0}% of this stage done` }, h("span", { style: { width: `${Math.min(100, pct || 0)}%` } }));
const LEADS = ["manager", "desk", "superintendent"];
const peopleOpts = (people, blank) => [...(blank ? [["", blank]] : []), ...people.map((p) => [String(p.id), p.name + (p.department ? ` (${p.department})` : "")])];

const BOARD_STAGES = ["approved", "design_proof", "plates", "printing", "finishing", "ready"];
const CLOSED_STAGES = ["delivered", "billed", "cancelled"];

const flow = () => state.stages.filter((s) => s.key !== "cancelled").map((s) => s.key);
const nextStage = (key) => { const f = flow(); const i = f.indexOf(key); return i >= 0 && i < f.length - 1 ? f[i + 1] : null; };
const canMove = (to) => state.myStages.includes(to);

async function moveTo(jobId, stage, note = "", assign_to = "") {
  return post(`/api/jobs/${jobId}/stage`, { stage, note, assign_to });
}

// ------------------------------------------------------------------ board / list

export async function renderJobs(view, forced = "list") {
  const mode = forced; // "list" = Production jobs, "board" = Production line
  let showClosed = false, overdueOnly = false, mineOnly = false, unassignedOnly = false, text = "", jobs = [];
  const body = h("div");

  const card = (j) => {
    const nxt = nextStage(j.stage);
    return h("div", { class: "jobcard" + (j.priority === "urgent" ? " urgent" : "") + (j.overdue ? " overdue" : ""), tabindex: "0", role: "link",
      onclick: () => (location.hash = `#/jobs/${j.id}`), onkeydown: (e) => { if (e.key === "Enter") location.hash = `#/jobs/${j.id}`; } },
      h("div", { class: "no" }, j.order_no, j.priority === "urgent" ? h("span", { class: "flag" }, "  URGENT") : null),
      h("div", { class: "t" }, j.title), h("div", { class: "meta" }, j.customer_name),
      h("div", { class: "meta" }, `${num(j.copies)} copies`, j.delivery_date ? [" · due ", h("span", { class: j.overdue ? "flag" : "" }, fmtDate(j.delivery_date))] : null),
      h("div", { class: "meta who" }, j.assigned_name ? ["With ", h("strong", null, j.assigned_name)] : h("em", null, "Not assigned")),
      j.assigned_name && j.progress_pct ? progressBar(j.progress_pct) : null,
      nxt && canMove(nxt) ? h("button", { class: "btn small go", onclick: async (e) => {
        e.stopPropagation();
        try { await moveTo(j.id, nxt); toast(`${j.order_no} → ${stageLabel(nxt)}`); await load(); } catch (err) { fail(err); }
      } }, "→ " + stageLabel(nxt)) : null);
  };

  const renderBoard = () => {
    const keys = showClosed ? [...BOARD_STAGES, "delivered", "billed"] : BOARD_STAGES;
    add(body, h("div", { class: "board" }, keys.map((k) => {
      const items = jobs.filter((j) => j.stage === k);
      return h("section", { class: "col", "aria-label": stageLabel(k) }, h("h3", null, stageLabel(k), h("span", { class: "muted" }, items.length)),
        items.length ? items.map(card) : h("div", { class: "small muted", style: { padding: ".3rem" } }, "—"));
    })));
  };

  const renderList = () => {
    if (!jobs.length) return add(body, emptyState("No jobs to show."));
    const office = isOffice();
    add(body, h("div", { class: "card tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Order", "Job", "Customer", "Stage", "With", "Copies", "Due", office ? "Total" : null].filter((x) => x !== null).map((t) => h("th", { class: t === "Copies" || t === "Total" ? "num" : "" }, t)))),
      h("tbody", null, jobs.map((j) => h("tr", { class: "clickable", onclick: () => (location.hash = `#/jobs/${j.id}`) },
        h("td", { class: "nowrap" }, j.order_no, j.priority === "urgent" ? h("span", { class: "flag" }, " !") : null), h("td", null, j.title), h("td", null, j.customer_name),
        h("td", null, badge(j.stage, stageLabel(j.stage))), h("td", null, j.assigned_name || h("span", { class: "muted" }, "—"), j.assigned_name && j.progress_pct ? progressBar(j.progress_pct) : null),
        h("td", { class: "num" }, num(j.copies)),
        h("td", { class: "nowrap" }, h("span", { class: j.overdue ? "flag" : "" }, fmtDate(j.delivery_date))),
        office ? h("td", { class: "num" }, money(j.total)) : null))))));
  };

  async function load() {
    const qs = new URLSearchParams();
    if (text) qs.set("q", text);
    if (overdueOnly) qs.set("overdue", "1");
    if (mineOnly) qs.set("mine", "1");
    else if (unassignedOnly) qs.set("unassigned", "1");
    if (!showClosed && mode === "list") qs.set("open", "1");
    try { jobs = await get("/api/jobs?" + qs); } catch (e) { return fail(e); }
    jobs.forEach((j) => { if (j.overdue === undefined) j.overdue = false; });
    clear(body);
    mode === "board" ? renderBoard() : renderList();
  }

  const search = h("input", { type: "search", placeholder: "Search order, job or customer", "aria-label": "Search jobs", oninput: debounce(() => { text = search.value.trim(); load(); }) });
  const closedCb = h("input", { type: "checkbox", onchange: () => { showClosed = closedCb.checked; load(); } });
  const overdueCb = h("input", { type: "checkbox", onchange: () => { overdueOnly = overdueCb.checked; load(); } });
  const mineCb = h("input", { type: "checkbox", onchange: () => { mineOnly = mineCb.checked; load(); } });
  const unCb = h("input", { type: "checkbox", onchange: () => { unassignedOnly = unCb.checked; load(); } });
  add(view, 
    h("div", { class: "pagehead" },
      h("div", null, h("div", { class: "eyebrow" }, "Workspace"), h("h1", null, mode === "board" ? "Production line" : "Production jobs"),
        h("div", { class: "sub" }, mode === "board" ? "Every open job by stage. Move a job forward when its stage is done." : "Track every confirmed job from approval through delivery.")),
      isOffice() ? h("div", { class: "actions" }, h("a", { class: "btn primary", href: "#/quotes/new" }, "+ New quotation")) : null),
    h("div", { class: "toolbar" }, search,
      h("label", { class: "check" }, closedCb, "Show delivered / billed"), h("label", { class: "check" }, overdueCb, "Overdue only"),
      h("label", { class: "check" }, mineCb, "Only my jobs"), LEADS.includes(state.user.role) ? h("label", { class: "check" }, unCb, "Not assigned yet") : null),
    body,
    mode === "board" ? h("div", { class: "note" }, "Each stage hands over to the next: the person finishing a stage moves the job on, and the move is logged with their name and the time.") : null);
  await load();
}

// ------------------------------------------------------------------ job view

const MACHINE_FORM = [["Web Manugraph", /web manugraph/], ["Web Orient", /web orient/], ["Komori", /komori/], ["HMT 2 Color", /hmt 2/],
  ["HMT D/Demy", /d\/demy/], ["Dominent", /dominent/], ["RISO", /riso/], ["Laser", /laser/], ["Ryobi", /ryobi/], ["Screen Ptg", /screen/], ["Manugraph", /^manugraph/]];
const BINDING_FORM = [["Lamination Matt", /lamination matt/], ["Glossy", /lamination gloss/], ["S/Side", /single side/], ["D/Side", /both sides/],
  ["Knurling", /knurl/], ["Spot UV", /spot uv/], ["3D", /^3d/], ["Dripoff", /drip/], ["Foil", /foil/], ["Folding", /fold/], ["Creasing", /crease|creasing/],
  ["Stitching", /^stitch/], ["Perfect", /perfect/], ["Centre Pin", /cent(re|er) pin/], ["Case Binding", /case bind/], ["Register Binding", /register/],
  ["Padmaking", /padmak/], ["Shrinkwrap", /shrink/], ["Perforation", /perforat/], ["Numbering", /numbering/], ["Screen Printing colour", /screen print/],
  ["Die Cutting", /die cut/], ["Pasting", /pasting/]];

function fyOf(dateStr) {
  const [y, m] = (dateStr || "").split("-").map(Number);
  if (!y) return "";
  const start = m >= 4 ? y : y - 1;
  return `${start}-${String(start + 1).slice(2)}`;
}

function workOrderSheet(job, showMoney) {
  const w = job.work || {}, c = job.customer || {}, s = state.settings;
  const mark = (on) => (on ? "☑" : "☐");
  const machines = (w.machines || []).map((m) => m.toLowerCase());
  const binding = (w.binding || []).map((b) => b.toLowerCase());
  const matchedBinding = new Set();
  BINDING_FORM.forEach(([, rx], i) => binding.forEach((b, j) => { if (rx.test(b)) matchedBinding.add(j); }));
  const others = (w.binding || []).filter((_, j) => !matchedBinding.has(j)).concat(w.extras || []);
  const p = w.pages || {};
  const line = (label, value) => h("div", null, h("strong", null, label + ": "), value || "");
  const checks = (list, src) => h("div", { class: "checks" }, list.map(([label, rx]) => h("span", null, mark(src.some((x) => rx.test(x))) + " " + label)));
  return h("section", { class: "sheet print-only" },
    logoImg(), h("h1", null, s.company_name || "Work order"), h("div", { class: "sub" }, `WORK ORDER - YEAR ${fyOf((job.created_at || "").slice(0, 10))}`),
    h("div", { class: "hdr" },
      h("div", null, line("Order No", job.order_no), line("Date", fmtDate((job.created_at || "").slice(0, 10)))),
      h("div", null, line("Quotation Date", fmtDate(job.quotation_date)), line("Proof Date", fmtDate(job.proof_date)), line("Delivery Date", fmtDate(job.delivery_date)),
        showMoney ? line("GST % / HSN", `${job.gst_pct}% / ${job.hsn || ""}`) : null)),
    h("div", { style: { marginTop: ".5rem" } }, line("Customer's Name", c.name), line("Address", [c.address, c.pin].filter(Boolean).join(" - ")),
      line("E-mail", c.email), line("Contact Person", c.contact_person), line("Ph. No", [c.phone1, c.phone2].filter(Boolean).join(", "))),
    h("div", { class: "bar" }, "DESCRIPTION OF WORK"),
    line("Name of work", job.title), line("Size", w.size), line("Copies", num(job.copies)),
    h("table", { style: { marginTop: ".4rem" } }, h("thead", null, h("tr", null, ["Paper", "Copies"].map((t) => h("th", null, t)))),
      h("tbody", null, (w.papers || []).map((x) => h("tr", null, h("td", null, x.label), h("td", null, num(x.copies)))))),
    h("table", { style: { marginTop: ".4rem" } }, h("thead", null, h("tr", null, ["M Color", "2 Color", "S Color", "B&W", "Cover", "End Paper"].map((t) => h("th", null, t)))),
      h("tbody", null, h("tr", null, [p.m_color, p.two_color, p.s_color, p.bw, p.cover, p.end_paper].map((v) => h("td", null, v || "-"))))),
    line("Plates", ["Polymaster", "Laser"].map((n) => `${mark((w.plates || []).some((x) => x.toLowerCase().includes(n.toLowerCase())))} ${n}`).join("   ")),
    line("Design by Press", w.design ? "Yes" : "No"), line("Name of Designer", job.designer),
    h("div", { class: "bar" }, "TYPE OF MACHINE"), checks(MACHINE_FORM, machines),
    h("div", { class: "bar" }, "BINDING INSTRUCTIONS"), checks(BINDING_FORM, binding), line("Others", others.join(", ")),
    h("div", { style: { marginTop: ".6rem" } }, line("OK for Delivery", mark(job.ok_for_delivery)),
      showMoney ? [line("Advance Rs", job.advance ? money(job.advance) : ""), line("Receipt No", job.receipt_no), line("Bill No / Delivery Note No", job.bill_no)] : null),
    h("div", { class: "box" }, h("strong", null, "Extra Details: "), job.extra_details || ""),
    (w.parts || []).length ? h("table", null, h("thead", null, h("tr", null, ["Part", "Paper", "Pages", "Sheets to issue", "Plates", "Machine"].map((t) => h("th", null, t)))),
      h("tbody", null, w.parts.map((x) => h("tr", null, h("td", null, x.name), h("td", null, x.paper), h("td", null, num(x.pages)), h("td", null, num(x.sheets_gross)), h("td", null, x.plates || "-"), h("td", null, x.machine))))) : null,
    h("div", { class: "sig" }, h("span", null, "Superintendent"), h("span", null, "Manager")));
}

export async function renderJobView(view, id) {
  const [job, people] = await Promise.all([get(`/api/jobs/${id}`), get("/api/people")]);
  const office = isOffice();
  const lead = LEADS.includes(state.user.role);
  const holdsIt = job.assigned_to === state.user.id;
  const w = job.work || {};
  const reload = async () => { clear(view); await renderJobView(view, id); };

  const edit = () => formModal({
    title: `Edit ${job.order_no}`,
    values: { ...job, ok_for_delivery: !!job.ok_for_delivery },
    fields: [
      { key: "title", label: "Job name", required: true },
      { key: "priority", label: "Priority", type: "select", options: [["normal", "Normal"], ["urgent", "Urgent"]] },
      { key: "delivery_date", label: "Delivery date", type: "date" }, { key: "proof_date", label: "Proof date", type: "date" },
      { key: "designer", label: "Designer / DTP operator" },
      ...(office ? [{ key: "advance", label: "Advance received (₹)", type: "number", step: "0.01", min: 0 }, { key: "receipt_no", label: "Receipt no." },
        { key: "bill_no", label: "Bill / delivery note no." }, { key: "hsn", label: "HSN code" }, { key: "gst_pct", label: "GST %", type: "number", step: "0.5", min: 0 }] : []),
      { key: "ok_for_delivery", label: "OK for delivery", type: "checkbox" },
      { key: "extra_details", label: "Extra details", type: "textarea" },
    ],
    onSubmit: async (v) => {
      for (const k of ["advance", "gst_pct"]) if (v[k] === "") v[k] = 0;
      await put(`/api/jobs/${id}`, v); toast("Saved"); await reload();
    },
  });

  // stage controls
  const allowed = state.stages.filter((s) => canMove(s.key) && s.key !== job.stage);
  const noteIn = h("input", { type: "text", placeholder: "Note (optional)", maxlength: 200, "aria-label": "Stage note" });
  const handSel = select(peopleOpts(people, "Keep with the same person"), "");
  const stageSel = select(allowed.map((s) => [s.key, s.label]), (allowed.find((s) => s.key === nextStage(job.stage)) || allowed[0] || {}).key);
  const nxt = nextStage(job.stage);
  const doMove = async (to) => {
    if (to === "cancelled" && !confirm(`Cancel job ${job.order_no}?`)) return;
    try { await moveTo(id, to, noteIn.value.trim(), handSel.value); toast(`Moved to ${stageLabel(to)}`); await reload(); } catch (e) { fail(e); }
  };
  const stageCard = h("div", { class: "card no-print" }, h("h2", null, "Progress"),
    h("div", { class: "stepper", "aria-label": "Job stages" }, flow().map((k, i) => {
      const cur = flow().indexOf(job.stage);
      return h("span", { class: "step" + (k === job.stage ? " current" : i < cur ? " done" : "") }, stageLabel(k));
    }), job.stage === "cancelled" ? badge("cancelled", "Cancelled") : null),
    allowed.length ? h("div", { class: "row", style: { alignItems: "end" } },
      nxt && canMove(nxt) ? h("div", null, h("button", { class: "btn primary", style: { width: "100%", marginBottom: ".6rem" }, onclick: () => doMove(nxt) }, "Move to " + stageLabel(nxt))) : null,
      field("Or move to", stageSel), field("Hand over to", handSel), field("Note", noteIn),
      h("div", null, h("button", { class: "btn", style: { marginBottom: ".6rem" }, onclick: () => doMove(stageSel.value) }, "Move"))) :
      h("p", { class: "muted" }, "Your role cannot change this job's stage."));


  // who holds the job
  const handOver = () => formModal({
    title: `Hand over ${job.order_no}`, submitText: "Hand over", values: { user_id: job.assigned_to ? String(job.assigned_to) : "" },
    fields: [{ key: "user_id", label: "Hand over to", type: "select", options: peopleOpts(people, lead ? "Nobody (unassign)" : "Choose a person"), required: !lead },
      { key: "note", label: "Instruction for them (optional)", type: "textarea" }],
    onSubmit: async (v) => { await post(`/api/jobs/${id}/assign`, v); toast("Handed over"); await reload(); },
  });
  const reportProgress = () => formModal({
    title: "How much of this step is done?", submitText: "Save progress", values: { progress_pct: job.progress_pct || 0 },
    fields: [{ key: "progress_pct", label: "Done so far (%)", type: "number", min: 0, step: "5", required: true, help: "0 to 100, for the stage the job is in now" },
      { key: "note", label: "What has been done (optional)", type: "textarea" }],
    onSubmit: async (v) => { await post(`/api/jobs/${id}/progress`, v); toast("Progress saved"); await reload(); },
  });
  const holdCard = h("div", { class: "card no-print" }, h("h2", null, "Who has it"),
    job.assigned_name ? [h("p", { class: "holder" }, h("strong", null, job.assigned_name), job.assigned_dept ? ` · ${job.assigned_dept}` : "", h("span", { class: "muted" }, ` since ${fmtDateTime(job.assigned_at)}`)),
      h("div", { class: "pline" }, progressBar(job.progress_pct), h("span", null, `${job.progress_pct || 0}% of ${stageLabel(job.stage)} done`))] :
      h("p", { class: "muted" }, "Not assigned to anyone yet."),
    h("div", { class: "row", style: { marginTop: ".6rem", gap: ".5rem" } },
      lead || holdsIt ? h("button", { class: "btn primary", onclick: handOver }, job.assigned_name ? "Hand over to someone" : "Assign to someone") : null,
      lead || holdsIt ? h("button", { class: "btn", onclick: reportProgress }, "Update progress") : null));

  // paper needed vs issued from stock
  const issue = (m) => formModal({
    title: `Issue ${m.item_name}`, submitText: "Issue to job", values: { qty: Math.max(0, +(m.need - m.issued).toFixed(3)) },
    fields: [{ key: "qty", label: `Quantity taken (${m.unit})`, type: "number", step: "any", min: 0, required: true, help: `${num(m.on_hand)} ${m.unit} in stock` },
      { key: "note", label: "Note (optional)" }],
    onSubmit: async (v) => { await post(`/api/stock/${m.item_id}/move`, { kind: "issue", qty: v.qty, job_id: id, note: v.note }); toast("Issued"); await reload(); },
  });
  const mats = job.materials || [];
  const matCard = mats.length ? h("div", { class: "card no-print" }, h("h2", null, "Paper & materials"),
    h("div", { class: "tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Paper", "Needed", "Issued", "In stock", ""].map((t, i) => h("th", { class: i >= 1 && i <= 3 ? "num" : "" }, t)))),
      h("tbody", null, mats.map((m) => h("tr", null,
        h("td", null, m.paper, m.item_id ? null : h("div", { class: "small muted" }, "Not linked to a stock item", office ? [" · ", h("a", { href: "#/stock" }, "set up in Inventory")] : "")),
        h("td", { class: "num" }, m.item_id ? `${num(m.need)} ${m.unit}` : `${num(m.sheets)} sheets · ${m.kg} kg`),
        h("td", { class: "num" }, m.item_id ? h("span", { class: m.issued >= m.need ? "ok" : "" }, `${num(m.issued)} ${m.unit}`) : "—"),
        h("td", { class: "num" }, m.item_id ? h("span", { class: m.on_hand < m.need - m.issued ? "flag" : "" }, `${num(m.on_hand)} ${m.unit}`) : "—"),
        h("td", { class: "right" }, m.item_id ? h("button", { class: "btn small", onclick: () => issue(m) }, "Issue") : null))))))) : null;

  // spec
  const p = w.pages || {};
  const pagesTxt = [["Multi-colour", p.m_color], ["2 colour", p.two_color], ["Single colour", p.s_color], ["B&W", p.bw], ["Cover", p.cover], ["End paper", p.end_paper]]
    .filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`).join(" · ");
  const specCard = h("div", { class: "card no-print" }, h("h2", null, "Work details"),
    h("dl", { class: "kv" },
      h("dt", null, "Size"), h("dd", null, w.size || "—"), h("dt", null, "Copies"), h("dd", null, num(job.copies)),
      h("dt", null, "Pages"), h("dd", null, pagesTxt || "—"),
      h("dt", null, "Machines"), h("dd", null, (w.machines || []).join(", ") || "—"),
      h("dt", null, "Plates"), h("dd", null, (w.plates || []).join(", ") || "—"),
      h("dt", null, "Binding / finishing"), h("dd", null, (w.binding || []).join(", ") || "None"),
      w.extras && w.extras.length ? [h("dt", null, "Also"), h("dd", null, w.extras.join(", "))] : null,
      h("dt", null, "Designer"), h("dd", null, job.designer || (w.design ? "Design by press" : "—")),
      h("dt", null, "Extra details"), h("dd", { style: { whiteSpace: "pre-wrap" } }, job.extra_details || "—")),
    (w.parts || []).length ? h("div", { class: "tablewrap", style: { marginTop: ".75rem" } }, h("table", null,
      h("thead", null, h("tr", null, ["Part", "Paper", "Pages", "Sheets to issue", "Plates", "Machine"].map((t, i) => h("th", { class: i >= 2 && i <= 4 ? "num" : "" }, t)))),
      h("tbody", null, w.parts.map((x) => h("tr", null, h("td", null, x.name), h("td", null, x.paper), h("td", { class: "num" }, num(x.pages)),
        h("td", { class: "num" }, num(x.sheets_gross)), h("td", { class: "num" }, x.plates || "—"), h("td", null, x.machine)))))) : null);

  const dateRow = (label, v, late) => [h("dt", null, label), h("dd", null, h("span", { class: late ? "flag" : "" }, fmtDate(v) || "—"))];
  const infoCard = h("div", { class: "card no-print" }, h("h2", null, "Dates & billing"),
    h("dl", { class: "kv" },
      dateRow("Quotation date", job.quotation_date), dateRow("Proof date", job.proof_date), dateRow("Delivery date", job.delivery_date, job.overdue),
      h("dt", null, "OK for delivery"), h("dd", null, job.ok_for_delivery ? "Yes" : "No"),
      office ? [h("dt", null, "Total (incl. GST)"), h("dd", null, money(job.total)), h("dt", null, "Advance"), h("dd", null, money(job.advance) + (job.receipt_no ? ` (receipt ${job.receipt_no})` : "")),
        h("dt", null, "Balance"), h("dd", null, h("strong", null, money(job.balance))),
        h("dt", null, "GST / HSN"), h("dd", null, `${job.gst_pct}%${job.hsn ? " / " + job.hsn : ""}`), h("dt", null, "Bill / delivery note"), h("dd", null, job.bill_no || "—")] : null));

  // timeline
  const noteBox = h("textarea", { placeholder: "Add a note for the team (e.g. paper short by 20 sheets, plate remade)", maxlength: 1000, "aria-label": "Note" });
  const addNote = async () => {
    if (!noteBox.value.trim()) return;
    try { await post(`/api/jobs/${id}/note`, { note: noteBox.value }); await reload(); } catch (e) { fail(e); }
  };
  const evText = (e) => e.kind === "stage" ? `Moved to ${stageLabel(e.stage)}` : e.kind === "created" ? "Job created" : e.kind === "edit" ? "" : e.kind === "assign" ? "Hand-over" : e.kind === "progress" ? "Progress" : e.kind === "stock" ? "Stock" : "Note";
  const timeline = h("div", { class: "card no-print" }, h("h2", null, "Timeline"),
    h("div", { style: { marginBottom: ".75rem" } }, noteBox, h("button", { class: "btn small", style: { marginTop: ".4rem" }, onclick: addNote }, "Add note")),
    h("ul", { class: "timeline" }, job.events.map((e) => h("li", null,
      h("div", null, h("strong", null, evText(e)), e.note ? (evText(e) ? " — " : "") + e.note : ""),
      h("div", { class: "at" }, `${e.user_name || "System"} · ${fmtDateTime(e.at)}`)))));

  add(view, 
    h("div", { class: "pagehead no-print" },
      h("div", null, h("h1", null, `${job.order_no} · ${job.title}`),
        h("div", null, badge(job.stage, stageLabel(job.stage)), " ", job.priority === "urgent" ? h("span", { class: "flag" }, "URGENT ") : null, h("span", { class: "muted" }, job.customer_name))),
      h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => window.print() }, "Print work order"),
        office && job.quotation_id ? h("a", { class: "btn", href: `#/quotes/${job.quotation_id}` }, "Quotation " + (job.quotation_no || "")) : null,
        office ? h("a", { class: "btn", href: `#/sales/new?job=${job.id}` }, "Create invoice") : null,
        state.user.role !== "operator" ? h("button", { class: "btn", onclick: edit }, "Edit details") : null)),
    h("div", { class: "cols two" }, h("div", null, holdCard, stageCard, specCard), h("div", null, matCard, infoCard, timeline)),
    workOrderSheet(job, office));
}
