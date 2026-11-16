import { state, get, post } from "./api.js";
import { h, add, clear, badge, formModal, toast, fail, num, fmtDateTime, emptyState, confirmBox } from "./ui.js";

export const REQ_STATUS = { awaiting_approval: "Needs manager's approval", pending: "Waiting for the store", partial: "Part issued", issued: "Issued", rejected: "Refused", cancelled: "Cancelled" };
const REQ_CLASS = { awaiting_approval: "urgent", pending: "plates", partial: "printing", issued: "ready", rejected: "cancelled", cancelled: "cancelled" };
export const reqBadge = (r) => badge(REQ_CLASS[r.status] || "plates", REQ_STATUS[r.status] || r.status);

const canIssue = () => ["manager", "storekeeper"].includes(state.user.role);
const isMgr = () => state.user.role === "manager";

/** Ask the store for material for a job. Re-asking for something already issued needs a reason and the manager's approval. */
export async function requestMaterial(jobId, jobLabel, after, preset = {}) {
  let items;
  try { items = (await get("/api/stock")).filter((i) => i.active && i.track_stock && i.category !== "service"); } catch (e) { return fail(e); }
  formModal({
    title: `Request material for ${jobLabel}`, submitText: "Send request to store",
    values: { item_id: preset.item_id ? String(preset.item_id) : "", qty: preset.qty || "", reason: "" },
    fields: [
      { key: "item_id", label: "Material (type to search)", type: "select", searchable: true, required: true, options: [["", "Choose material…"], ...items.map((i) => [String(i.id), `${i.name} (${num(i.on_hand)} ${i.unit} in stock)`])] },
      { key: "qty", label: "Quantity needed", type: "number", step: "any", min: 0, required: true },
      { key: "reason", label: "Reason", help: "Required if this material was already issued for the job. The manager has to authorise it before the store can give it out", full: true },
    ],
    onSubmit: async (v) => {
      const r = await post(`/api/jobs/${jobId}/material-requests`, { item_id: Number(v.item_id), qty: v.qty, reason: v.reason });
      toast(r.status === "awaiting_approval" ? "Sent. The manager must authorise it before the store can issue" : "Request sent to the store");
      if (after) await after();
    },
  });
}

export async function renderStore(view) {
  let tab = state.user.role === "manager" ? "approve" : "issue";
  let list = [];
  const body = h("div");
  const tabs = h("div", { class: "toolbar", role: "tablist" });

  const issue = (r) => formModal({
    title: `Issue ${r.name} to ${r.order_no}`, submitText: "Issue from store",
    values: { qty: r.remaining }, fields: [
      { key: "qty", label: `Quantity issued (${r.unit})`, type: "number", step: "any", min: 0, required: true,
        help: `${num(r.on_hand)} ${r.unit} in stock${r.location ? " · kept at " + r.location : ""}. Approved for ${num(r.remaining)} ${r.unit}` },
      { key: "note", label: "Note (optional)" }],
    onSubmit: async (v) => { await post(`/api/material-requests/${r.id}/issue`, v); toast("Issued and marked against the job"); await load(); },
  });
  const decide = (r, approve) => formModal({
    title: approve ? `Authorise more ${r.name}` : `Refuse ${r.name}`, submitText: approve ? "Authorise" : "Refuse request",
    values: { qty: r.qty }, fields: [
      ...(approve ? [{ key: "qty", label: `Quantity to allow (${r.unit})`, type: "number", step: "any", min: 0, required: true, help: `Asked for ${num(r.qty)} ${r.unit}. Reason given: ${r.reason}` }] : []),
      { key: "note", label: approve ? "Note (optional)" : "Why is it refused?", required: !approve }],
    onSubmit: async (v) => { await post(`/api/material-requests/${r.id}/decide`, { approve, qty: v.qty, note: v.note }); toast(approve ? "Authorised. The store can issue it now" : "Refused"); await load(); },
  });
  const cancel = async (r) => {
    if (!(await confirmBox("Cancel request", `Cancel the request for ${r.name} on ${r.order_no}?`, "Cancel request", true))) return;
    try { await post(`/api/material-requests/${r.id}/cancel`, {}); await load(); } catch (e) { fail(e); }
  };

  const draw = () => {
    clear(body);
    const shown = list.filter((r) => tab === "approve" ? r.status === "awaiting_approval" : tab === "issue" ? ["pending", "partial"].includes(r.status) : !["awaiting_approval", "pending", "partial"].includes(r.status));
    if (!shown.length) return add(body, emptyState(tab === "issue" ? "Nothing waiting for the store." : tab === "approve" ? "Nothing waiting for approval." : "No history yet."));
    add(body, h("div", { class: "card tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Request", "Job", "Material", "Asked", "Issued", "In stock", "Status", ""].map((t, i) => h("th", { class: i >= 3 && i <= 5 ? "num" : "" }, t)))),
      h("tbody", null, shown.map((r) => h("tr", null,
        h("td", null, h("b", null, r.number), h("div", { class: "small muted" }, `${fmtDateTime(r.requested_at)} · ${r.requested_name || ""}`)),
        h("td", null, h("a", { href: `#/jobs/${r.job_id}` }, r.order_no), h("div", { class: "small muted" }, r.job_title)),
        h("td", null, r.name, r.kind === "additional" ? [" ", badge("urgent", "Extra")] : null,
          r.reason && r.kind === "additional" ? h("div", { class: "small muted" }, "Reason: " + r.reason) : null,
          r.decision_note ? h("div", { class: "small muted" }, `${r.decided_name || "Manager"}: ${r.decision_note}`) : null,
          !r.item_id ? h("div", { class: "small flag" }, "Not linked to a stock item. The office must set it up in Items & stock") : null),
        h("td", { class: "num" }, `${num(r.qty)} ${r.unit}`),
        h("td", { class: "num" }, r.qty_issued ? `${num(r.qty_issued)} ${r.unit}` : "—"),
        h("td", { class: "num" }, r.item_id ? h("span", { class: r.on_hand < r.remaining ? "flag" : "" }, `${num(r.on_hand)} ${r.unit}`) : "—"),
        h("td", null, reqBadge(r), r.issued_name && r.qty_issued ? h("div", { class: "small muted" }, `${r.issued_name}, ${fmtDateTime(r.issued_at)}`) : null),
        h("td", { class: "right nowrap" },
          ["pending", "partial"].includes(r.status) && canIssue() && r.item_id ? h("button", { class: "btn small primary", onclick: () => issue(r) }, "Issue") : null,
          r.status === "awaiting_approval" && isMgr() ? [h("button", { class: "btn small primary", onclick: () => decide(r, true) }, "Authorise"), " ", h("button", { class: "btn small danger", onclick: () => decide(r, false) }, "Refuse")] : null,
          ["pending", "awaiting_approval"].includes(r.status) && !r.qty_issued && (isMgr() || state.user.role === "storekeeper" || r.requested_by === state.user.id) ? [" ", h("button", { class: "btn small", onclick: () => cancel(r) }, "Cancel")] : null)))))));
  };

  async function load() {
    try { list = await get("/api/store/requests?status=all"); } catch (e) { return fail(e); }
    const n = (s) => list.filter((r) => s.includes(r.status)).length;
    const labels = { approve: `Needs approval (${n(["awaiting_approval"])})`, issue: `To issue (${n(["pending", "partial"])})`, history: "History" };
    tabs.querySelectorAll("button").forEach((b) => { b.textContent = labels[b.dataset.tab]; b.classList.toggle("primary", b.dataset.tab === tab); });
    draw();
  }
  for (const k of ["issue", "approve", "history"]) add(tabs, h("button", { class: "btn", role: "tab", "data-tab": k, onclick: () => { tab = k; load(); } }, k));
  add(view, h("div", { class: "pagehead" }, h("div", null, h("div", { class: "eyebrow" }, "Workspace"), h("h1", null, "Store"),
    h("div", { class: "sub" }, "Material requests for confirmed jobs. Each paper is issued once against its job. Asking for more of the same material needs the manager's approval."))),
    tabs, body);
  await load();
}
