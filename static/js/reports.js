import { get } from "./api.js";
import { h, add, clear, input, money, num, fmtDate, fail, emptyState, printHeader } from "./ui.js";
import { csvDownload, hashQuery } from "./acc.js";

const TABS = [
  ["sales", "Sales register"], ["purchases", "Purchase register"], ["receivable", "Customers owe you"], ["payable", "You owe suppliers"],
  ["stock", "Stock summary"], ["gst", "GST summary"], ["pnl", "Profit & loss"], ["daybook", "Daybook"],
];
const th = (labels, numFrom = 99) => h("thead", null, h("tr", null, labels.map((t, i) => h("th", { class: i >= numFrom ? "num" : "" }, t))));
const td = (v, cls) => h("td", { class: cls || "" }, v);
const N = (v) => td(money(v), "num");
const sumRow = (label, span, vals) => h("tr", { style: { fontWeight: 700 } }, h("td", { colspan: span }, label), vals.map((v) => N(v)));
const wrap = (...kids) => h("div", { class: "card tablewrap" }, ...kids);

export async function renderReports(view) {
  const q = hashQuery();
  const tab = TABS.some((t) => t[0] === q.tab) ? q.tab : "sales";
  const from = input("date", q.from || ""), to = input("date", q.to || "");
  const out = h("div");
  const needsDates = !["receivable", "payable", "stock"].includes(tab);
  const go = (t, f, tt) => { location.hash = `#/reports?tab=${t}${f ? "&from=" + f : ""}${tt ? "&to=" + tt : ""}`; };
  const nav = h("div", { class: "toolbar no-print" }, TABS.map(([k, l]) => h("a", { class: "btn small" + (k === tab ? " primary" : ""), href: `#/reports?tab=${k}` }, l)));
  const range = needsDates ? h("div", { class: "toolbar no-print" }, "From ", from, " to ", to, h("button", { class: "btn small", onclick: () => go(tab, from.value, to.value) }, "Show"),
    h("span", { class: "small muted" }, "Blank dates mean: this financial year up to today")) : null;
  add(view, printHeader(), h("div", { class: "pagehead" }, h("div", null, h("div", { class: "eyebrow" }, "Accounts"), h("h1", null, "Reports")),
    h("div", { class: "actions no-print" }, h("button", { class: "btn", onclick: () => window.print() }, "Print"))), nav, range, out);

  const qs = new URLSearchParams({ ...(q.from && { from: q.from }), ...(q.to && { to: q.to }) }).toString();
  const period = (d) => h("p", { class: "muted small" }, `${fmtDate(d.from)} to ${fmtDate(d.to)}`);
  try {
    if (tab === "sales" || tab === "purchases") {
      const kind = tab === "sales" ? "sale" : "purchase";
      const d = await get(`/api/reports/register?kind=${kind}&${qs}`);
      add(out, period(d), d.rows.length ? wrap(h("table", null, th(["Date", "Number", "Party", "GSTIN", "Taxable", "CGST", "SGST", "IGST", "Total"], 4),
        h("tbody", null, d.rows.map((r) => h("tr", null, td(fmtDate(r.inv_date), "nowrap"), td(h("a", { href: `#/${tab}/${r.id}` }, r.number)), td(r.party_name), td(r.gstin || "—"),
          N(r.taxable), N(r.cgst), N(r.sgst), N(r.igst), N(r.total))), sumRow("Total", 4, [d.totals.taxable, d.totals.cgst, d.totals.sgst, d.totals.igst, d.totals.total]))),
        h("button", { class: "btn small no-print", onclick: () => csvDownload(`${tab}-register.csv`, ["Date", "Number", "Party", "GSTIN", "Taxable", "CGST", "SGST", "IGST", "Total"],
          d.rows.map((r) => [r.inv_date, r.number, r.party_name, r.gstin, r.taxable, r.cgst, r.sgst, r.igst, r.total])) }, "Download CSV")) : emptyState("No invoices in this period."));
    } else if (tab === "receivable" || tab === "payable") {
      const d = await get(`/api/reports/outstanding?kind=${tab}`);
      add(out, d.rows.length ? wrap(h("table", null, th(["Party", "Phone", "Balance", "0-30 days", "31-60", "61-90", "Over 90", "Other"], 2),
        h("tbody", null, d.rows.map((r) => h("tr", null, td(h("a", { href: `#/parties/${r.id}` }, r.name)), td(r.phone || "—"), N(r.balance), N(r.b0), N(r.b1), N(r.b2), N(r.b3), N(r.other))),
          sumRow("Total", 2, [d.totals.balance, d.totals.b0, d.totals.b1, d.totals.b2, d.totals.b3, d.totals.other]))),
        h("p", { class: "small muted" }, "Ages count from the invoice date. 'Other' is opening balance or money paid on account that is not tied to an invoice.")) : emptyState("Nothing outstanding."));
    } else if (tab === "stock") {
      const d = await get("/api/reports/stock");
      add(out, d.rows.length ? wrap(h("table", null, th(["Item", "Category", "In stock", "Buying price", "Stock value", "Selling price"], 2),
        h("tbody", null, d.rows.map((r) => h("tr", null, td(h("strong", null, r.name), r.low ? h("span", { class: "flag" }, "  Low") : null), td(r.category), td(`${num(r.on_hand)} ${r.unit}`, "num"), N(r.purchase_price), N(r.value), N(r.sale_price))),
          sumRow("Total stock value", 4, [d.total_value]))),
        h("button", { class: "btn small no-print", onclick: () => csvDownload("stock-summary.csv", ["Item", "Category", "Unit", "In stock", "Buying price", "Stock value", "Selling price"],
          d.rows.map((r) => [r.name, r.category, r.unit, r.on_hand, r.purchase_price, r.value, r.sale_price])) }, "Download CSV")) : emptyState("No stock items yet."));
    } else if (tab === "gst") {
      const d = await get(`/api/reports/gst?${qs}`);
      const block = (title, b) => h("div", { class: "card tablewrap" }, h("h2", null, title), h("table", null, th(["GST %", "Taxable", "CGST", "SGST", "IGST"], 1),
        h("tbody", null, b.rows.map((r) => h("tr", null, td(r.gst_rate + "%"), N(r.taxable), N(r.cgst), N(r.sgst), N(r.igst))), sumRow("Total", 1, [b.totals.taxable, b.totals.cgst, b.totals.sgst, b.totals.igst]))));
      add(out, period(d), block("Output tax (on sales)", d.output), block("Input tax (on purchases)", d.input),
        h("div", { class: "card tablewrap" }, h("h2", null, d.net.total >= 0 ? "GST payable" : "GST credit"), h("table", null, th(["", "CGST", "SGST", "IGST", "Net"], 1),
          h("tbody", null, h("tr", { style: { fontWeight: 700 } }, td("Output − input"), N(d.net.cgst), N(d.net.sgst), N(d.net.igst), N(d.net.total))))),
        d.hsn.length ? h("div", { class: "card tablewrap" }, h("h2", null, "HSN summary (sales)"), h("table", null, th(["HSN", "GST %", "Quantity", "Taxable", "Tax"], 2),
          h("tbody", null, d.hsn.map((r) => h("tr", null, td(r.hsn || "—"), td(r.gst_rate + "%"), td(num(r.qty), "num"), N(r.taxable), N(r.tax)))))) : null,
        h("p", { class: "small muted" }, "A working summary to help with GST returns. Check the figures with your accountant before filing."));
    } else if (tab === "pnl") {
      const d = await get(`/api/reports/pnl?${qs}`);
      const row = (l, v, strong) => h("tr", { style: strong ? { fontWeight: 700 } : null }, td(l), N(v));
      add(out, period(d), wrap(h("table", { style: { maxWidth: "460px" } }, h("tbody", null,
        row("Sales (before GST)", d.sales, true), row("Opening stock", d.opening_stock), row("+ Stock purchases (bills)", d.stock_purchases), row("+ Stock added outside bills (opening stock, counts)", d.other_additions), row("− Closing stock", d.closing_stock),
        row("Cost of goods sold", d.cost_of_goods), row("Gross profit", d.gross_profit, true), row("− Other expenses", d.expenses), row("Net profit", d.net_profit, true)))),
        h("p", { class: "small muted" }, d.note + " Expenses are purchase bills with no stock item (rent, electricity, wages and so on)."));
    } else if (tab === "daybook") {
      const d = await get(`/api/reports/daybook?${qs}`);
      add(out, period(d), d.rows.length ? wrap(h("table", null, th(["Date", "Type", "Number", "Party", "Amount", "Money in", "Money out"], 4),
        h("tbody", null, d.rows.map((r) => h("tr", { style: r.cancelled ? { opacity: ".5", textDecoration: "line-through" } : null }, td(fmtDate(r.date), "nowrap"), td(r.type), td(r.number), td(r.party), N(r.amount), N(r.in), N(r.out))),
          sumRow("Total", 5, [d.money_in, d.money_out])))) : emptyState("Nothing in this period."));
    }
  } catch (e) { fail(e); add(out, h("div", { class: "errbox" }, e.message)); }
}
