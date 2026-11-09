import { get, post, put, del } from "./api.js";
import { h, add, clear, field, select, input, formModal, toast, fail, money, fmtDate, debounce, emptyState, confirmBox, badge, printHeader } from "./ui.js";
import { loadStates, TYPE_LABEL, hashQuery, csvDownload } from "./acc.js";

const balText = (b) => (Math.abs(b) < 0.005 ? "Nil" : `${money(Math.abs(b))} ${b > 0 ? "to receive" : "to pay"}`);
const balClass = (b) => (b > 0.004 ? "pos" : b < -0.004 ? "neg" : "muted");

export async function renderParties(view) {
  const states = await loadStates();
  let list = [], text = "", type = "", showOff = false;
  const body = h("div");

  async function load() {
    try { list = await get("/api/parties" + (showOff ? "?all=1" : "")); } catch (e) { return fail(e); }
    draw();
  }

  const edit = (p) => formModal({
    title: p ? `Edit ${p.name}` : "Add party",
    values: p ? { ...p, active: !!p.active, balance_side: p.opening_balance < 0 ? "pay" : "receive", opening_abs: Math.abs(p.opening_balance) || "" }
      : { party_type: "customer", state_code: "", balance_side: "receive" },
    fields: [
      { key: "name", label: "Party name", required: true },
      { key: "party_type", label: "This party is a", type: "select", options: Object.entries(TYPE_LABEL) },
      { key: "contact_person", label: "Contact person" }, { key: "phone1", label: "Phone" }, { key: "email", label: "E-mail" },
      { key: "address", label: "Address", full: true }, { key: "pin", label: "PIN" },
      { key: "gstin", label: "GSTIN", help: "15 characters. Leave blank for an unregistered party" },
      { key: "state_code", label: "State (place of supply)", type: "select", options: [["", "Not set (treated as your own state)"], ...states.map((s) => [s.code, `${s.code} ${s.name}`])],
        help: "Decides CGST + SGST (same state) or IGST (other state)" },
      { key: "opening_abs", label: "Opening balance (Rs)", type: "number", step: "0.01", min: 0, help: "What was already pending when you started using this app" },
      { key: "balance_side", label: "Opening balance means", type: "select", options: [["receive", "They owe me (to receive)"], ["pay", "I owe them (to pay)"]] },
      { key: "notes", label: "Notes", type: "textarea", full: true },
      ...(p ? [{ key: "active", label: "In use", type: "checkbox" }] : []),
    ],
    onSubmit: async (v) => {
      const amt = Number(v.opening_abs) || 0;
      v.opening_balance = v.balance_side === "pay" ? -amt : amt;
      delete v.opening_abs; delete v.balance_side;
      if (p) await put(`/api/parties/${p.id}`, v); else await post("/api/parties", v);
      toast("Saved"); await load();
    },
  });

  const remove = async (p) => {
    if (!(await confirmBox("Remove party", `Remove ${p.name}? If they have invoices, payments or jobs they are switched off instead of deleted.`, "Remove", true))) return;
    try { const r = await del(`/api/parties/${p.id}`); toast(r.deleted ? "Deleted" : "Switched off (has history)"); await load(); } catch (e) { fail(e); }
  };

  function draw() {
    clear(body);
    const shown = list.filter((p) => (!type || p.party_type === type || p.party_type === "both") && (!text || (p.name + p.gstin + p.phone1).toLowerCase().includes(text.toLowerCase())));
    const recv = list.filter((p) => p.balance > 0).reduce((a, p) => a + p.balance, 0);
    const pay = list.filter((p) => p.balance < 0).reduce((a, p) => a - p.balance, 0);
    add(body, h("div", { class: "stats" },
      h("div", { class: "stat" }, h("div", { class: "lbl" }, "To receive"), h("div", { class: "n" }, money(recv))),
      h("div", { class: "stat" }, h("div", { class: "lbl" }, "To pay"), h("div", { class: "n" }, money(pay)))));
    if (!shown.length) return add(body, emptyState(list.length ? "Nothing matches." : "No parties yet. Add your first customer or supplier."));
    add(body, h("div", { class: "card tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Party", "Type", "GSTIN", "Phone", "Balance", ""].map((t, i) => h("th", { class: i === 4 ? "num" : "" }, t)))),
      h("tbody", null, shown.map((p) => h("tr", { style: p.active ? null : { opacity: ".55" } },
        h("td", null, h("a", { href: `#/parties/${p.id}` }, h("strong", null, p.name))),
        h("td", null, TYPE_LABEL[p.party_type] || p.party_type), h("td", { class: "nowrap" }, p.gstin || "—"), h("td", null, p.phone1 || "—"),
        h("td", { class: "num" }, h("span", { class: balClass(p.balance) }, balText(p.balance))),
        h("td", { class: "right nowrap" }, h("a", { class: "btn small", href: `#/parties/${p.id}` }, "Statement"), " ",
          h("button", { class: "btn small", onclick: () => edit(p) }, "Edit"), " ", h("button", { class: "btn small", onclick: () => remove(p) }, "Remove"))))))));
  }

  const search = h("input", { type: "search", placeholder: "Search name, GSTIN or phone", "aria-label": "Search parties", oninput: debounce(() => { text = search.value.trim(); draw(); }, 150) });
  const typeSel = select([["", "All parties"], ["customer", "Customers"], ["supplier", "Suppliers"]], "", { "aria-label": "Party type", onchange: () => { type = typeSel.value; draw(); } });
  const offCb = h("input", { type: "checkbox", onchange: () => { showOff = offCb.checked; load(); } });
  add(view,
    h("div", { class: "pagehead" }, h("div", null, h("div", { class: "eyebrow" }, "Accounts"), h("h1", null, "Parties"),
      h("div", { class: "sub" }, "Customers and suppliers, with what each owes you or you owe them.")),
      h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => edit(null) }, "+ Add party"))),
    h("div", { class: "toolbar" }, search, typeSel, h("label", { class: "check" }, offCb, "Show switched-off parties")), body);
  await load();
}

export async function renderPartyStatement(view, id) {
  const q = hashQuery();
  const from = q.from || "", to = q.to || "";
  const d = await get(`/api/parties/${id}/statement?${new URLSearchParams({ ...(from && { from }), ...(to && { to }) })}`);
  const fromI = input("date", d.from), toI = input("date", d.to);
  const go = () => { location.hash = `#/parties/${id}?from=${fromI.value}&to=${toI.value}`; };
  const link = (r) => (r.src === "sale" ? `#/sales/${r.id}` : r.src === "purchase" ? `#/purchases/${r.id}` : null);
  add(view,
    printHeader(),
    h("div", { class: "pagehead" }, h("div", null, h("div", { class: "eyebrow" }, "Party statement"), h("h1", null, d.party.name),
      h("div", { class: "sub" }, [d.party.gstin && `GSTIN ${d.party.gstin}`, d.party.phone1, `Now: ${balText(d.party.balance)}`].filter(Boolean).join(" · "))),
      h("div", { class: "actions no-print" }, h("a", { class: "btn", href: "#/parties" }, "Back"), " ",
        h("button", { class: "btn", onclick: () => csvDownload(`statement-${d.party.name}.csv`, ["Date", "Type", "Number", "Details", "Debit", "Credit", "Balance"],
          d.rows.map((r) => [r.date, r.type, r.number, r.ref, r.debit, r.credit, r.balance])) }, "Download CSV"), " ",
        h("button", { class: "btn primary", onclick: () => window.print() }, "Print"))),
    h("div", { class: "toolbar no-print" }, "From ", fromI, " to ", toI, h("button", { class: "btn small", onclick: go }, "Show")),
    h("div", { class: "card tablewrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Date", "Type", "Number", "Details", "Debit", "Credit", "Balance"].map((t, i) => h("th", { class: i > 3 ? "num" : "" }, t)))),
      h("tbody", null,
        h("tr", null, h("td", { colspan: 6 }, h("em", null, "Opening balance")), h("td", { class: "num" }, money(d.opening))),
        d.rows.map((r) => h("tr", null, h("td", { class: "nowrap" }, fmtDate(r.date)), h("td", null, r.type),
          h("td", null, link(r) ? h("a", { href: link(r) }, r.number) : r.number), h("td", null, r.ref),
          h("td", { class: "num" }, r.debit ? money(r.debit) : ""), h("td", { class: "num" }, r.credit ? money(r.credit) : ""), h("td", { class: "num" }, money(r.balance)))),
        h("tr", null, h("td", { colspan: 6 }, h("strong", null, "Closing balance (positive = they owe you)")), h("td", { class: "num" }, h("strong", null, money(d.closing))))))));
}
