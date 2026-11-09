// Shared helpers for the accounting screens.
import { state, get } from "./api.js";

let statesCache = null;
export async function loadStates() {
  if (!statesCache) statesCache = await get("/api/states");
  return statesCache;
}
export const stateName = (code) => ((statesCache || []).find((s) => s.code === code) || {}).name || "";

export function companyStateCode() {
  const s = state.settings;
  if (s.company_state_code) return s.company_state_code;
  const g = (s.company_gstin || "").slice(0, 2);
  return /^\d\d$/.test(g) ? g : "";
}

const r2 = (x) => Math.round((x + Number.EPSILON) * 100) / 100;

// Mirrors the server's GST maths so the form can show a live preview. The server's figures are the ones saved.
export function calcInvoice(lines, intra) {
  const out = []; const tot = { taxable: 0, cgst: 0, sgst: 0, igst: 0 };
  for (const l of lines) {
    const taxable = r2((l.qty || 0) * (l.rate || 0) * (1 - (l.disc_pct || 0) / 100));
    const gst = r2(taxable * (l.gst_rate || 0) / 100);
    const cgst = intra ? r2(gst / 2) : 0; const sgst = intra ? r2(gst - cgst) : 0; const igst = intra ? 0 : gst;
    out.push({ taxable, cgst, sgst, igst, amount: r2(taxable + gst) });
    tot.taxable = r2(tot.taxable + taxable); tot.cgst = r2(tot.cgst + cgst); tot.sgst = r2(tot.sgst + sgst); tot.igst = r2(tot.igst + igst);
  }
  const raw = tot.taxable + tot.cgst + tot.sgst + tot.igst;
  tot.total = Math.round(raw); tot.round_off = r2(tot.total - raw);
  return { lines: out, totals: tot };
}

const ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"];
const TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];
const below100 = (n) => (n < 20 ? ONES[n] : TENS[Math.floor(n / 10)] + (n % 10 ? " " + ONES[n % 10] : ""));
const below1000 = (n) => (n >= 100 ? ONES[Math.floor(n / 100)] + " Hundred" + (n % 100 ? " " + below100(n % 100) : "") : below100(n));
// Indian grouping: crore, lakh, thousand.
export function inWords(amount) {
  let n = Math.floor(Math.abs(amount)); const paise = Math.round((Math.abs(amount) - n) * 100);
  if (n === 0 && paise === 0) return "Zero Rupees Only";
  const parts = [];
  for (const [div, name] of [[10000000, "Crore"], [100000, "Lakh"], [1000, "Thousand"]]) {
    const q = Math.floor(n / div); if (q) parts.push(below1000(q) + " " + name); n %= div;
  }
  if (n) parts.push(below1000(n));
  let s = (parts.join(" ") || "Zero") + " Rupees";
  if (paise) s += " and " + below100(paise) + " Paise";
  return s + " Only";
}

export const TYPE_LABEL = { customer: "Customer", supplier: "Supplier", both: "Customer & supplier" };
export const PAY_MODES = [["cash", "Cash"], ["upi", "UPI"], ["bank", "Bank transfer"], ["cheque", "Cheque"], ["card", "Card"], ["other", "Other"]];
export const PAY_BADGE = { paid: ["delivered", "Paid"], part: ["finishing", "Part paid"], unpaid: ["approved", "Unpaid"], cancelled: ["cancelled", "Cancelled"] };

export function hashQuery() {
  const q = location.hash.split("?")[1] || "";
  return Object.fromEntries(new URLSearchParams(q));
}
export function csvDownload(name, header, rows) {
  const esc = (v) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const text = [header, ...rows].map((r) => r.map(esc).join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" })); a.download = name; document.body.append(a); a.click(); a.remove();
}
